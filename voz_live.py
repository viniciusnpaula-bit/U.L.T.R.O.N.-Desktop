"""Modo de voz bidirecional em tempo real (Gemini Live API via WebSocket).

Arquitetura de segurança e confiabilidade:
- A chave de API trafega apenas no cabeçalho HTTP `x-goog-api-key` (nunca na URL)
  e todos os logs passam por `seguranca.redigir()`.
- Reutiliza o fluxo PCM 16 kHz limpo (AEC + HPF) do `AudioFrontEnd` (`afe.py`),
  sem abrir o microfone duas vezes.
- Reproduz PCM 24 kHz via `voz.ReprodutorPcmStream` com corte imediato no barge-in
  (tanto local via AFE quanto remoto via `serverContent.interrupted`).
- Toda chamada de ferramenta (`toolCall`) passa obrigatoriamente por
  `ferramentas.executar(..., confirmar, origem="voz_live")` -> `seguranca.autorizar()`.
- Em caso de falha de rede, falta de cota ou chave ausente no modo `auto`, retorna
  limpamente para fallback ao pipeline clássico (STT -> LLM -> TTS).
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import queue
import threading
import time
from typing import Callable

import config
import seguranca
import sessao

GEMINI_LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.BidiGenerateContent/BidiGenerateContent"
)

_MAPA_TIPOS_GEMINI = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "object": "OBJECT",
    "array": "ARRAY",
}

_sessao_ativa_lock = threading.Lock()
_sessao_ativa: "SessaoGeminiLive | None" = None


def sessao_live_ativa() -> bool:
    with _sessao_ativa_lock:
        return bool(_sessao_ativa is not None and _sessao_ativa.conectada)


def parar_sessao_live_ativa() -> None:
    with _sessao_ativa_lock:
        atual = _sessao_ativa
    if atual is not None:
        atual.parar()


def live_disponivel() -> bool:
    """True quando há chave Gemini e biblioteca `websockets` disponíveis."""
    chave = str(getattr(config, "CHAVES", {}).get("gemini") or "").strip()
    if not chave:
        return False
    try:
        import websockets  # noqa: F401
        return True
    except Exception:
        return False


def modo_voz_efetivo() -> str:
    """Retorna 'live' ou 'classico' conforme config.VOZ_MODO e disponibilidade."""
    modo = str(getattr(config, "VOZ_MODO", "auto") or "auto").strip().lower()
    if modo == "classico":
        return "classico"
    if modo in ("live", "auto") and live_disponivel():
        return "live"
    return "classico"


def normalizar_modelo_live(modelo: str | None = None) -> str:
    bruto = str(modelo or getattr(config, "GEMINI_LIVE_MODEL", "") or "").strip()
    if not bruto:
        bruto = "models/gemini-2.5-flash-native-audio-preview-12-2025"
    if not bruto.startswith("models/"):
        bruto = f"models/{bruto}"
    return bruto


def converter_schemas_gemini(schemas_openai: list[dict]) -> list[dict]:
    """Converte o catálogo de ferramentas OpenAI de `ferramentas.schemas()` para Gemini Live."""
    declaracoes: list[dict] = []
    for item in schemas_openai or []:
        fn = item.get("function") if isinstance(item, dict) else None
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        params = fn.get("parameters") or {}
        props_orig = params.get("properties") or {}
        props_out = {}
        for k, spec in props_orig.items():
            if not isinstance(spec, dict):
                continue
            tipo = _MAPA_TIPOS_GEMINI.get(str(spec.get("type", "string")).lower(), "STRING")
            props_out[str(k)] = {
                "type": tipo,
                "description": str(spec.get("description") or k)[:240],
            }
        decl = {
            "name": str(fn["name"]),
            "description": str(fn.get("description") or fn["name"])[:300],
        }
        if props_out:
            decl["parameters"] = {
                "type": "OBJECT",
                "properties": props_out,
                "required": [str(r) for r in (params.get("required") or []) if str(r) in props_out],
            }
        declaracoes.append(decl)
    return declaracoes


def montar_payload_setup(
    *,
    model: str | None = None,
    voice_name: str | None = None,
    system_text: str | None = None,
    tool_schemas: list[dict] | None = None,
) -> dict:
    """Monta a mensagem inicial `setup` do protocolo Gemini BidiGenerateContent."""
    if system_text is None:
        try:
            import personalidade
            base = personalidade.frase_do_sistema()
        except Exception:
            base = f"Você é o U.L.T.R.O.N., assistente pessoal em português do Brasil."
        system_text = (
            f"{base}\n"
            "Responda em português do Brasil de forma natural, concisa e objetiva para voz em tempo real. "
            "Todas as ações no PC são autorizadas localmente pelo sistema de segurança do U.L.T.R.O.N.; "
            "nunca tente contornar recusas de segurança nem solicite PIN por voz."
        )
    if tool_schemas is None:
        try:
            import ferramentas
            tool_schemas = ferramentas.schemas()
        except Exception:
            tool_schemas = []

    declaracoes = converter_schemas_gemini(tool_schemas)
    voz_escolhida = str(voice_name or getattr(config, "GEMINI_LIVE_VOICE", "Charon") or "Charon").strip()
    setup_body: dict = {
        "model": normalizar_modelo_live(model),
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voz_escolhida}
                }
            },
        },
        "systemInstruction": {
            "parts": [{"text": system_text[:6000]}],
        },
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }
    if declaracoes:
        setup_body["tools"] = [{"functionDeclarations": declaracoes}]
    return {"setup": setup_body}


class SessaoGeminiLive:
    """Gerencia uma sessão de áudio bidirecional Gemini Live com barge-in e ferramentas seguras."""

    def __init__(
        self,
        *,
        confirmar: Callable[[str, dict], bool],
        ouvido=None,
        on_estado: Callable[[str, str | None], None] | None = None,
        on_conversa: Callable[[str, str, str], None] | None = None,
        api_key: str | None = None,
        model: str | None = None,
        voice_name: str | None = None,
        reprodutor=None,
        ws_connect: Callable | None = None,
        executar_ferramenta: Callable | None = None,
        stop_event: threading.Event | None = None,
        pausado_event: threading.Event | None = None,
        tool_schemas: list[dict] | None = None,
        system_text: str | None = None,
    ):
        self._confirmar = confirmar
        self._ouvido = ouvido
        self._on_estado = on_estado
        self._on_conversa = on_conversa
        self._api_key = str(api_key if api_key is not None else getattr(config, "CHAVES", {}).get("gemini", "")).strip()
        self._model = normalizar_modelo_live(model)
        self._voice_name = str(voice_name or getattr(config, "GEMINI_LIVE_VOICE", "Charon") or "Charon").strip()
        self._reprodutor = reprodutor
        self._ws_connect = ws_connect
        self._executar_ferramenta = executar_ferramenta
        self._stop_event = stop_event
        self._pausado_event = pausado_event
        self._tool_schemas = tool_schemas
        self._system_text = system_text

        self._parar_local = threading.Event()
        self._fila_entrada: queue.Queue[bytes] = queue.Queue(maxsize=96)
        self._canceladas_tool_ids: set[str] = set()
        self._lock_estado = threading.Lock()
        self.conectada = False
        self.ultimo_erro: str | None = None
        self.turnos_processados = 0
        self.interrupcoes = 0
        self.ferramentas_executadas = 0

    def _publicar_estado(self, estado: str, erro: str | None = None) -> None:
        if callable(self._on_estado):
            try:
                self._on_estado(estado, erro)
            except Exception:
                pass

    def _publicar_conversa(self, papel: str, texto: str) -> None:
        limpo = str(texto or "").strip()
        if not limpo:
            return
        seguro = seguranca.redigir(limpo)
        try:
            import memoria
            memoria.salvar_msg("user" if papel == "user" else "assistant", seguro)
        except Exception:
            pass
        if callable(self._on_conversa):
            try:
                self._on_conversa(papel, seguro, "voz_live")
            except Exception:
                pass

    def _deve_parar(self) -> bool:
        if self._parar_local.is_set():
            return True
        if self._stop_event is not None and self._stop_event.is_set():
            return True
        if self._pausado_event is not None and self._pausado_event.is_set():
            return True
        if not sessao.estado().get("desbloqueada"):
            return True
        if str(getattr(config, "VOZ_MODO", "auto") or "auto").strip().lower() == "classico":
            return True
        return False

    def alimentar_audio(self, pcm_16k_bytes: bytes) -> None:
        """Recebe frames PCM 16 kHz limpos do AFE (chamado de thread de áudio)."""
        if not pcm_16k_bytes or self._parar_local.is_set():
            return
        if self._pausado_event is not None and self._pausado_event.is_set():
            return
        try:
            self._fila_entrada.put_nowait(bytes(pcm_16k_bytes))
        except queue.Full:
            try:
                self._fila_entrada.get_nowait()
                self._fila_entrada.put_nowait(bytes(pcm_16k_bytes))
            except queue.Empty:
                pass

    def _ao_barge_in_local(self, _tipo: str, _pcm) -> None:
        """Corte imediato (<10 ms) da saída 24 kHz quando o AFE detecta interrupção local."""
        self.interrupcoes += 1
        if self._reprodutor is not None:
            try:
                self._reprodutor.limpar()
            except Exception:
                pass

    def parar(self) -> None:
        self._parar_local.set()
        if self._reprodutor is not None:
            try:
                self._reprodutor.limpar()
            except Exception:
                pass

    async def _abrir_websocket(self):
        headers = {"x-goog-api-key": self._api_key}
        if self._ws_connect is not None:
            return self._ws_connect(GEMINI_LIVE_WS_URL, headers)
        import websockets
        sig = inspect.signature(websockets.connect)
        if "additional_headers" in sig.parameters:
            return websockets.connect(
                GEMINI_LIVE_WS_URL,
                additional_headers=headers,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
                max_size=8 * 1024 * 1024,
            )
        return websockets.connect(
            GEMINI_LIVE_WS_URL,
            extra_headers=headers,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        )

    async def _executar_tool_calls(self, ws, function_calls: list[dict]) -> None:
        exec_fn = self._executar_ferramenta
        if exec_fn is None:
            import ferramentas
            exec_fn = ferramentas.executar

        respostas = []
        for fc in function_calls:
            call_id = str(fc.get("id") or "")
            nome = str(fc.get("name") or "").strip()
            args = fc.get("args") if isinstance(fc.get("args"), dict) else {}
            if call_id and call_id in self._canceladas_tool_ids:
                self._canceladas_tool_ids.discard(call_id)
                continue
            self._publicar_estado("processando")
            if getattr(seguranca, "parada", None) and seguranca.parada.is_set():
                resultado = "Cancelado pela parada de emergência."
            else:
                try:
                    resultado = await asyncio.to_thread(
                        exec_fn, nome, args, self._confirmar, "voz_live"
                    )
                    resultado = str(resultado)
                except Exception as erro:
                    resultado = f"Erro ao executar {nome}: {type(erro).__name__}"
            self.ferramentas_executadas += 1
            if call_id and call_id in self._canceladas_tool_ids:
                self._canceladas_tool_ids.discard(call_id)
                continue
            respostas.append({
                "id": call_id,
                "name": nome,
                "response": {"result": seguranca.redigir(resultado)[:4000]},
            })

        if respostas and not self._parar_local.is_set():
            payload = {"toolResponse": {"functionResponses": respostas}}
            await ws.send(json.dumps(payload, ensure_ascii=False))
            self._publicar_estado("live_ouvindo")

    async def _loop_envio(self, ws) -> None:
        while not self._deve_parar():
            try:
                pcm = self._fila_entrada.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            if not pcm:
                continue
            payload = {
                "realtimeInput": {
                    "mediaChunks": [
                        {
                            "mimeType": "audio/pcm;rate=16000",
                            "data": base64.b64encode(pcm).decode("ascii"),
                        }
                    ]
                }
            }
            await ws.send(json.dumps(payload))

    async def _loop_recebimento(self, ws) -> None:
        buf_usuario: list[str] = []
        buf_assistente: list[str] = []
        tarefas_tools: set[asyncio.Task] = set()

        try:
            while not self._deve_parar():
                try:
                    bruto = await asyncio.wait_for(ws.recv(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if bruto is None:
                    break
                if isinstance(bruto, bytes):
                    bruto = bruto.decode("utf-8", errors="ignore")
                try:
                    msg = json.loads(bruto)
                except (TypeError, ValueError):
                    continue
                if not isinstance(msg, dict):
                    continue

                if "setupComplete" in msg:
                    self.conectada = True
                    self._publicar_estado("live_ouvindo")
                    continue

                if "toolCallCancellation" in msg:
                    ids = (msg.get("toolCallCancellation") or {}).get("ids") or []
                    for cid in ids:
                        self._canceladas_tool_ids.add(str(cid))
                    continue

                if "toolCall" in msg:
                    fcs = (msg.get("toolCall") or {}).get("functionCalls") or []
                    if fcs:
                        task = asyncio.create_task(self._executar_tool_calls(ws, fcs))
                        tarefas_tools.add(task)
                        task.add_done_callback(tarefas_tools.discard)
                    continue

                sc = msg.get("serverContent")
                if not isinstance(sc, dict):
                    continue

                if sc.get("interrupted"):
                    self.interrupcoes += 1
                    if self._reprodutor is not None:
                        self._reprodutor.limpar()
                    buf_assistente.clear()
                    self._publicar_estado("live_ouvindo")
                    continue

                in_tr = sc.get("inputTranscription")
                if isinstance(in_tr, dict) and in_tr.get("text"):
                    buf_usuario.append(str(in_tr["text"]))

                out_tr = sc.get("outputTranscription")
                if isinstance(out_tr, dict) and out_tr.get("text"):
                    buf_assistente.append(str(out_tr["text"]))

                model_turn = sc.get("modelTurn")
                if isinstance(model_turn, dict):
                    for part in model_turn.get("parts") or []:
                        if not isinstance(part, dict):
                            continue
                        inline = part.get("inlineData")
                        if isinstance(inline, dict) and inline.get("data"):
                            mime = str(inline.get("mimeType") or "").lower()
                            if "audio" in mime or "pcm" in mime or not mime:
                                try:
                                    pcm_out = base64.b64decode(inline["data"])
                                except Exception:
                                    pcm_out = b""
                                if pcm_out and self._reprodutor is not None:
                                    self._publicar_estado("live_falando")
                                    self._reprodutor.escrever(pcm_out)

                if sc.get("turnComplete"):
                    texto_u = "".join(buf_usuario).strip()
                    texto_a = "".join(buf_assistente).strip()
                    buf_usuario.clear()
                    buf_assistente.clear()
                    if texto_u:
                        self._publicar_conversa("user", texto_u)
                    if texto_a:
                        self._publicar_conversa("assistant", texto_a)
                    if texto_u or texto_a:
                        self.turnos_processados += 1
                        try:
                            sessao.tocar()
                        except Exception:
                            pass
                    self._publicar_estado("live_ouvindo")
        finally:
            for t in list(tarefas_tools):
                t.cancel()
            if tarefas_tools:
                await asyncio.gather(*tarefas_tools, return_exceptions=True)

    async def executar_async(self) -> str:
        """Conecta e mantém a sessão Gemini Live até encerrar ou falhar.

        Retorna:
          - 'parado': encerramento limpo (pausa, bloqueio, shutdown ou troca para modo clássico)
          - 'fallback': erro de conexão, autenticação ou cota (permite fallback ao pipeline clássico)
        """
        if not self._api_key:
            self.ultimo_erro = "Chave GEMINI_API_KEY ausente para o modo Live."
            return "fallback"

        global _sessao_ativa
        reprodutor_criado = False
        if self._reprodutor is None:
            import voz
            self._reprodutor = voz.ReprodutorPcmStream(sample_rate=24000)
            reprodutor_criado = True

        self._parar_local.clear()
        self._publicar_estado("conectando_live")

        consumidor_registrado = False
        barge_in_anterior = None
        if self._ouvido is not None:
            if hasattr(self._ouvido, "registrar_consumidor_audio"):
                consumidor_registrado = bool(self._ouvido.registrar_consumidor_audio(self.alimentar_audio))
            barge_in_anterior = getattr(self._ouvido, "on_barge_in_extra", None)
            self._ouvido.on_barge_in_extra = self._ao_barge_in_local

        gancho_emergencia = self.parar
        if gancho_emergencia not in seguranca.ganchos_parada:
            seguranca.ganchos_parada.append(gancho_emergencia)

        with _sessao_ativa_lock:
            _sessao_ativa = self

        try:
            self._reprodutor.iniciar()
            ctx = await self._abrir_websocket()
            async with ctx as ws:
                setup_payload = montar_payload_setup(
                    model=self._model,
                    voice_name=self._voice_name,
                    system_text=self._system_text,
                    tool_schemas=self._tool_schemas,
                )
                await ws.send(json.dumps(setup_payload, ensure_ascii=False))
                self.conectada = True
                self._publicar_estado("live_ouvindo")

                t_envio = asyncio.create_task(self._loop_envio(ws))
                t_recv = asyncio.create_task(self._loop_recebimento(ws))
                done, pending = await asyncio.wait(
                    {t_envio, t_recv},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for d in done:
                    exc = d.exception()
                    if exc is not None and not isinstance(exc, asyncio.CancelledError):
                        raise exc
            return "parado" if self._deve_parar() else "fallback"
        except Exception as erro:
            msg_segura = seguranca.redigir(f"{type(erro).__name__}: {erro}")[:180]
            self.ultimo_erro = msg_segura
            seguranca.log.warning(f"[voz_live] sessão encerrada com fallback ({msg_segura})")
            return "fallback"
        finally:
            self.conectada = False
            with _sessao_ativa_lock:
                if _sessao_ativa is self:
                    _sessao_ativa = None
            if gancho_emergencia in seguranca.ganchos_parada:
                seguranca.ganchos_parada.remove(gancho_emergencia)
            if self._ouvido is not None:
                if consumidor_registrado and hasattr(self._ouvido, "remover_consumidor_audio"):
                    self._ouvido.remover_consumidor_audio(self.alimentar_audio)
                self._ouvido.on_barge_in_extra = barge_in_anterior
            if reprodutor_criado and self._reprodutor is not None:
                self._reprodutor.fechar()
            elif self._reprodutor is not None:
                self._reprodutor.limpar()

    def executar(self) -> str:
        """Wrapper síncrono para rodar a sessão dentro da thread de voz (`main.modo_voz`)."""
        return asyncio.run(self.executar_async())
