"""Lifecycle and request coordination for the local Desktop panel."""
from __future__ import annotations

import importlib
import inspect
import json
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path

from microphone_devices import enumerate_input_devices

import config
import sessao

# Limite de falhas de PIN e janela de espera (em memória, zerada ao reiniciar).
UNLOCK_FALHAS_MAX = 5
UNLOCK_ESPERA_S = 30.0


class DesktopRuntime:
    """Runs one core voice loop and serializes Desktop commands through the core."""

    def __init__(self, start_voice: bool = True):
        self.start_voice = start_voice
        self._events: queue.Queue[dict] = queue.Queue()
        self._commands: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._microphone_lock = threading.RLock()
        self._stop = threading.Event()
        self._started = False
        self._api_running = False
        self._shutdown_requested = False
        self._error: str | None = None
        self._voice_state = "iniciando"
        self._microphone_error: str | None = None
        self._main = None
        self._security = None
        self._cerebro = None
        self._ouvido = None
        self._turns: list[dict] = []
        self._turns_lock = threading.Lock()
        try:
            import atualizacao
            self._updater = atualizacao.UpdateManager(Path(__file__).resolve().parent,
                                                      repo=os.environ.get("ULTRON_UPDATE_REPO"),
                                                      log=self._log_update)
        except Exception:
            self._updater = None
        self._microphone_preference = self._load_microphone_preference()
        self._microphone_device_id = self._microphone_preference["id"] if self._microphone_preference else None
        self._microphone_device_index = None
        self._command_thread: threading.Thread | None = None
        self._voice_thread: threading.Thread | None = None
        self._notification_callback = None

        self._unlock_lock = threading.Lock()
        self._unlock_falhas = 0
        self._unlock_espera_ate = 0.0
        self._session_thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._started:
                return
            self._stop.clear()
            self._main = importlib.import_module("main")
            self._security = importlib.import_module("seguranca")
            self._cerebro = importlib.import_module("cerebro")
            self._main.pausado.clear()
            self._shutdown_requested = False
            self._voice_state = "iniciando"
            self._microphone_error = None
            try:
                if self._microphone_preference:
                    self._resolve_microphone_preference()
                else:
                    self._resolve_default_microphone()
            except Exception:
                self._microphone_device_index = -1
                self._microphone_error = "Não foi possível acessar a lista de entradas de microfone. Verifique a permissão de microfone do Windows."
                self._voice_state = "erro"
            notifiers = getattr(self._cerebro, "NOTIFICADORES", None)
            if isinstance(notifiers, list):
                self._notification_callback = self._notify
                notifiers.append(self._notification_callback)
            self._command_thread = threading.Thread(
                target=self._command_loop, name="ultron-desktop-commands", daemon=True)
            self._command_thread.start()
            self._started = True
            self._error = None
            if self._inatividade_limite() > 0:
                self._session_thread = threading.Thread(
                    target=self._session_monitor, name="ultron-desktop-sessao", daemon=True)
                self._session_thread.start()
            if self.start_voice:
                self._voice_thread = threading.Thread(
                    target=self._voice_loop, name="ultron-desktop-voice", daemon=True)
                self._voice_thread.start()

    # ---- bloqueio por inatividade (ULTRON_SESSAO_MINUTOS)
    def _inatividade_limite(self) -> float:
        """Segundos sem uso até bloquear; 0 desliga o monitor."""
        try:
            return max(0.0, float(getattr(config, "SESSAO_MINUTOS", 15) or 0)) * 60
        except (TypeError, ValueError):
            return 15 * 60

    def _verificar_inatividade(self) -> bool:
        """Bloqueia a sessão se passou do limite. True quando acabou de bloquear."""
        limite = self._inatividade_limite()
        if limite <= 0:
            return False
        estado = sessao.estado()
        if not estado.get("desbloqueada"):
            return False
        desde = estado.get("ultima_atividade") or estado.get("desde") or 0.0
        if time.time() - desde < limite:
            return False
        sessao.bloquear()
        self._log_seg("lock", "ALLOW", "inactivity_timeout")
        self._events.put({"type": "session_locked", "motivo": "inatividade"})
        return True

    def _session_monitor(self) -> None:
        while not self._stop.wait(5.0):
            try:
                self._verificar_inatividade()
            except Exception:
                pass

    def _voice_loop(self) -> None:
        try:
            kwargs = {
                "bandeja": False,
                "entrada_teclado": False,
                "stop_event": self._stop,
                "ouvido_pronto": self._set_ouvido,
            }
            parameters = inspect.signature(self._main.modo_voz).parameters
            if "microphone_device_index" in parameters:
                kwargs["microphone_device_index"] = self._microphone_device_index
            if "microphone_device_id" in parameters:
                kwargs["microphone_device_id"] = self._microphone_device_id
            if "conversa" in parameters:
                kwargs["conversa"] = self._registrar_conversa
            if "converter_confirmacao" in parameters:
                kwargs["converter_confirmacao"] = self._confirmar_interpretacao
            try:
                if "estado_voz" in inspect.signature(self._main.modo_voz).parameters:
                    kwargs["estado_voz"] = self._set_voice_state
            except (TypeError, ValueError):
                pass
            self._main.modo_voz(**kwargs)
        except Exception:
            self._error = "Falha ao iniciar ou manter a escuta do ULTRON."
            self._set_voice_state("erro", self._error)

    MAX_TURNOS = 15   # últimas mensagens mantidas na sessão (voz e texto)

    def _registrar_conversa(self, papel: str, texto: str, origem: str = "voz",
                            emitir: bool = True) -> None:
        """Registra um turno do bate-papo. Nunca guarda PIN, chave ou token.

        `emitir=False` guarda o turno para a reconciliação do painel sem publicar
        `conversation_turn`: no comando digitado a interface já mostrou o turno
        na hora, e reemitir criaria duplicata.
        """
        if papel not in {"user", "assistant"} or not texto:
            return
        try:
            seguro = self._security.redigir(str(texto)) if self._security else str(texto)
        except Exception:
            seguro = "—"
        turno = {
            "type": "conversation_turn",
            "role": papel,
            "text": str(seguro)[:2000],
            "source": str(origem)[:16],
            "at": time.time(),
        }
        if emitir:
            self._events.put(turno)
        with self._turns_lock:
            self._turns.append({key: turno[key] for key in ("role", "text", "source", "at")})
            if len(self._turns) > self.MAX_TURNOS:
                del self._turns[:-self.MAX_TURNOS]

    # ---- voz e personalidade (Fase 2)
    def voz_info(self) -> dict:
        try:
            import voz
            return {"preferencias": voz.preferencias(), "ativas": voz.voz_ativa(),
                    "vozes": voz.vozes_disponiveis()}
        except Exception as erro:
            self._registrar_falha("voz.info", erro)
            return {"preferencias": {}, "ativas": {}, "vozes": [], "erro": "Módulo de voz indisponível."}

    def voz_salvar(self, valores: dict) -> dict:
        import voz
        return voz.salvar_preferencias(valores or {})

    def voz_restaurar(self) -> dict:
        import voz
        return voz.restaurar_preferencias()

    def voz_testar(self, texto: str = "") -> dict:
        """Fala uma frase curta. Avisa que o áudio sai pelo PC, não para a nuvem."""
        import voz
        frase = (texto or "").strip()[:120] or "Ultrason, teste de voz concluído."
        resultado = voz.testar_voz(frase)
        resultado["aviso"] = "O texto é enviado ao serviço de voz (Edge TTS) só para gerar o áudio."
        return resultado

    def microfone_testar(self) -> dict:
        import voz
        resultado = voz.testar_microfone(1.2)
        resultado["aviso"] = "O teste só mede o nível local; nada é gravado nem enviado."
        return resultado

    # ---- cofre de credenciais
    def cofre_status(self) -> dict:
        import cofre
        return cofre.status()

    def cofre_guardar(self, nome: str, valor: str) -> dict:
        import cofre
        cofre.guardar(nome, valor)
        return cofre.status()

    def cofre_remover(self, nome: str) -> dict:
        import cofre
        cofre.remover(nome)
        return cofre.status()

    def cofre_testar(self, nome: str) -> dict:
        """Testa a chave fazendo uma chamada mínima ao provedor (sem gastar tokens)."""
        import cofre, config
        if nome not in cofre.PROVEDORES:
            raise ValueError("Só provedores de IA podem ser testados aqui.")
        chave = cofre.obter(nome) or config.CHAVES.get(nome, "")
        if not chave:
            return {"ok": False, "mensagem": f"{nome}: nenhuma chave configurada."}
        try:
            from openai import OpenAI
            cliente = OpenAI(api_key=chave, base_url=config.URLS[nome], timeout=15)
            modelos = [m.id for m in cliente.models.list().data][:3]
            return {"ok": True, "mensagem": f"{nome}: chave aceita ({len(modelos)} modelo(s) visíveis)."}
        except Exception as erro:
            nome_erro = type(erro).__name__
            return {"ok": False, "mensagem": f"{nome}: a chave foi recusada ou a rede falhou ({nome_erro})."}

    # ---- memória (Fase 3)
    def fatos_listar(self, busca: str = "") -> dict:
        import memoria
        return {"fatos": memoria.buscar_fatos(busca, 50) if busca else memoria.fatos_com_id(50),
                "limite": 50}

    def fatos_corrigir(self, id_, texto) -> dict:
        import memoria
        memoria.corrigir_fato(id_, texto)
        return self.fatos_listar()

    def fatos_apagar(self, id_=None, trecho=None) -> dict:
        import memoria
        if id_ is not None:
            memoria.apagar_fato_por_id(id_)
        elif trecho:
            memoria.apagar_fato(trecho)
        return self.fatos_listar()

    def lembretes_listar(self) -> dict:
        import memoria
        return {"lembretes": memoria.lembretes_numerados(),
                "aviso": "Lembretes só são avisados com o ULTRON aberto."}

    def lembrete_cancelar(self, numero=None, trecho=None) -> dict:
        import memoria
        mensagem = memoria.cancelar_lembrete(numero=numero, trecho=trecho or "")
        return {"mensagem": mensagem, **self.lembretes_listar()}

    def fluxos_listar(self) -> dict:
        import fluxos
        return {"fluxos": fluxos.listar()}

    def personalidade_info(self) -> dict:
        import personalidade
        return {"atual": personalidade.carregar(),
                "perfis": personalidade.perfis_disponiveis(),
                "jeitos": personalidade.jeitos_disponiveis()}

    def personalidade_salvar(self, valores: dict) -> dict:
        import personalidade
        return personalidade.salvar(valores or {})

    def personalidade_restaurar(self) -> dict:
        import personalidade
        return personalidade.restaurar_padrao()

    def personalidade_previa(self) -> dict:
        """Mostra a instrução que a IA recebe com o perfil atual (sem chamar provedor)."""
        import personalidade
        return {"instrucao": personalidade.frase_do_sistema(), "atual": personalidade.carregar()}

    def _confirmar_interpretacao(self, fala: str, incerteza: dict, timeout: float = 20.0) -> bool:
        """Pede confirmação ao painel quando o reconhecimento ficou ambíguo.

        Usa o MESMO canal de confirmações (request_id + evento), com prazo. Sem
        resposta (ou painel fechado) o resultado é recusa: nada é executado.
        """
        request_id = uuid.uuid4().hex
        pendente = {"event": threading.Event(), "approved": False, "expired": False,
                    "pedido": {"risco": "MEDIO"}, "requires_pin": False, "pin": None}
        with self._pending_lock:
            self._pending[request_id] = pendente
        self._events.put({
            "type": "speech_confirm",
            "request_id": request_id,
            "fala": str(fala)[:300],
            "alternativas": [str(a)[:300] for a in list(incerteza.get("opcoes") or [])[:3]],
            "motivo": str(incerteza.get("motivo") or "")[:200],
        })
        try:
            return bool(pendente["event"].wait(timeout) and pendente["approved"])
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _log_update(self, mensagem: str) -> None:
        try:
            if self._security:
                self._security.log.info(str(mensagem)[:300])
            else:
                print(f"[atualizacao] {mensagem}"[:300])
        except Exception:
            pass

    def _registrar_falha(self, onde: str, erro: Exception | None = None) -> None:
        """Registra só o rótulo interno e o TIPO do erro (nunca texto do usuário)."""
        tipo = type(erro).__name__ if erro is not None else "?"
        try:
            if self._security is not None:
                self._security.log.warning(f"falha interna em {onde} ({tipo})")
            else:
                print(f"[aviso] falha interna em {onde} ({tipo})")
        except Exception:
            pass

    def update_info(self) -> dict:
        if self._updater is None:
            return {"current_version": "desconhecida", "status": "indisponivel"}
        return self._updater.describe()

    def check_update(self) -> dict:
        if self._updater is None:
            return {"status": "indisponivel", "message": "Módulo de atualização não carregado."}
        return self._updater.check()

    def apply_update(self, restart_after: bool = False) -> dict:
        if self._updater is None:
            return {"status": "indisponivel", "message": "Módulo de atualização não carregado."}
        return self._updater.apply(restart_after=restart_after)

    def update_and_restart(self) -> dict:
        """Passo 2 do botão: aplica o que já foi verificado e, se necessário, reinicia.

        Fluxo: se ainda não há pacote em staging, baixa e verifica; aplica o que dá
        na hora; se sobrar arquivo em uso, dispara o script de troca e encerra o app.
        """
        if self._updater is None:
            return {"status": "indisponivel", "message": "Módulo de atualização não carregado."}
        job = self._updater._job or {}
        if job.get("status") not in {"pronto"}:
            job = self._updater.apply(restart_after=True)
            return {"status": "baixando", "job": job}
        if job.get("needs_restart"):
            disparado = self._updater.launch_apply()
            if disparado:
                self.request_shutdown()
            return {"status": "reiniciando" if disparado else "erro",
                    "message": "Aplicando e reiniciando…" if disparado else "Não consegui iniciar a troca de arquivos.",
                    "job": job}
        return {"status": "aplicado", "message": job.get("message") or "Atualização aplicada.",
                "job": job}

    def launch_update(self) -> bool:
        return bool(self._updater and self._updater.launch_apply())

    def rollback_update(self) -> bool:
        return bool(self._updater and self._updater.rollback())

    def conversation_turns(self) -> list[dict]:
        with self._turns_lock:
            return list(self._turns)

    def limpar_conversa(self) -> int:
        """Esvazia o bate-papo da sessão. Devolve quantas mensagens saíram."""
        with self._turns_lock:
            removidas = len(self._turns)
            self._turns.clear()
        return removidas

    def _set_voice_state(self, state: str, error: str | None = None) -> None:
        self._voice_state = str(state)[:40]
        if state == "erro" and error:
            try:
                safe_error = self._security.redigir(str(error))
            except Exception:
                safe_error = "Falha ao acessar ou reconhecer o microfone."
            self._microphone_error = safe_error[:180]
        else:
            self._microphone_error = None

    def _set_ouvido(self, ouvido) -> None:
        if hasattr(ouvido, "set_device") and (
            ouvido.device_index != self._microphone_device_index or
            getattr(ouvido, "device_id", None) != self._microphone_device_id
        ):
            ouvido.set_device(self._microphone_device_index, self._microphone_device_id)
        self._ouvido = ouvido

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if not self._started:
                return
            self._main.pausado.set()
            self._stop.set()
            with self._pending_lock:
                for pending in self._pending.values():
                    pending["approved"] = False
                    pending["pin"] = None
                    pending["event"].set()
            self._commands.put(None)

            ouvido = self._ouvido
            deadline = time.monotonic() + 4.0
            while ouvido is not None and ouvido.capturando.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            for thread in (self._voice_thread, self._command_thread, self._session_thread):
                if thread is not None and thread is not threading.current_thread():
                    thread.join(timeout=4.5)
            self._session_thread = None
            self._api_running = False
            self._started = False
            notifiers = getattr(self._cerebro, "NOTIFICADORES", None)
            if isinstance(notifiers, list) and self._notification_callback in notifiers:
                notifiers.remove(self._notification_callback)
            self._notification_callback = None

    def request_shutdown(self) -> None:
        self._shutdown_requested = True

    def set_api_running(self, running: bool) -> None:
        self._api_running = bool(running)

    def set_microphone_paused(self, paused: bool) -> bool:
        with self._microphone_lock:
            if not self._started:
                return False
            if paused:
                self._main.pausado.set()
                ouvido = self._ouvido
                deadline = time.monotonic() + 4.0
                while ouvido is not None and ouvido.capturando.is_set() and time.monotonic() < deadline:
                    time.sleep(0.01)
                return ouvido is None or not ouvido.capturando.is_set()
            if self._stop.is_set():
                return False
            self._main.pausado.clear()
            return True

    @staticmethod
    def _microphone_settings_path() -> Path:
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "ULTRON" / "microphone.json"

    @classmethod
    def _load_microphone_preference(cls):
        try:
            value = json.loads(cls._microphone_settings_path().read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("id"), str) and isinstance(value.get("name"), str):
                return {"id": value["id"][:512], "name": value["name"][:256]}
        except (OSError, ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _audio_inputs():
        return enumerate_input_devices()

    def _resolve_microphone_preference(self, inputs=None):
        _audio, inputs = self._audio_inputs() if inputs is None else (None, inputs)
        selected = next((device for device in inputs if device["id"] == self._microphone_preference["id"]), None)
        self._microphone_device_index = selected["index"] if selected else -1
        self._microphone_device_id = self._microphone_preference["id"]
        if selected is None:
            self._microphone_error = f"O microfone selecionado não está disponível: {self._microphone_preference['name']}. Escolha outra entrada antes de retomar a escuta."
            self._voice_state = "erro"
        return selected

    def _resolve_default_microphone(self):
        audio, inputs = self._audio_inputs()
        default = next((device for device in inputs if device["index"] == audio.default.device[0]), None)
        self._microphone_device_index = default["index"] if default else -1
        self._microphone_device_id = None
        if default is None:
            self._microphone_error = "Nenhuma entrada padrão de microfone está disponível. Conecte ou selecione um dispositivo de entrada."
            self._voice_state = "erro"
        return default

    def list_microphones(self):
        audio, inputs = self._audio_inputs()
        selected = next((device for device in inputs if self._microphone_preference and
                         device["id"] == self._microphone_preference["id"]), None)
        default_index = audio.default.device[0]
        default = next((device for device in inputs if device["index"] == default_index), None)
        if self._microphone_preference:
            selected_available = selected is not None
            selected_name = selected["name"] if selected else self._microphone_preference["name"]
            target_index = selected["index"] if selected else -1
        else:
            selected_available = default is not None
            selected_name = default["name"] if default else "Padrão do sistema"
            target_index = default["index"] if default else -1
        self._apply_microphone_device(target_index, self._microphone_preference["id"] if self._microphone_preference else None)
        devices = [{"id": None, "name": "Padrão do sistema"}]
        devices.extend({"id": device["id"], "name": device["name"]} for device in inputs)
        return {"devices": devices, "selected_id": self._microphone_preference["id"] if self._microphone_preference else None,
                "selected_name": selected_name, "selected_available": selected_available,
                "active_name": selected_name if selected_available else None}

    def select_microphone(self, device_id):
        if device_id is not None and (not isinstance(device_id, str) or len(device_id) > 512):
            raise ValueError("Identificador de microfone inválido.")
        audio, inputs = self._audio_inputs()
        selected = next((device for device in inputs if device["id"] == device_id), None) if device_id else None
        if device_id is not None and selected is None:
            raise LookupError("O microfone escolhido não está disponível. Atualize a lista e selecione uma entrada conectada.")
        target_index = selected["index"] if selected else next(
            (item["index"] for item in inputs if item["index"] == audio.default.device[0]), -1)
        if target_index == -1:
            raise LookupError("Não há entrada padrão de áudio disponível. Conecte um microfone ou escolha outra entrada.")
        preference = {"id": selected["id"], "name": selected["name"]} if selected else None
        with self._microphone_lock:
            was_paused = bool(self._started and self._main.pausado.is_set())
            if self._started:
                self._main.pausado.set()
                ouvido = self._ouvido
                deadline = time.monotonic() + 4.0
                while ouvido is not None and ouvido.capturando.is_set() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if ouvido is not None and ouvido.capturando.is_set():
                    raise RuntimeError("A captura atual não foi liberada; tente novamente.")
            settings = self._microphone_settings_path()
            try:
                settings.parent.mkdir(parents=True, exist_ok=True)
                temporary = settings.with_suffix(".tmp")
                temporary.write_text(json.dumps(preference or {"id": None, "name": "Padrão do sistema"}, ensure_ascii=False), encoding="utf-8")
                temporary.replace(settings)
            except OSError as exc:
                if self._started and not was_paused and not self._stop.is_set():
                    self._main.pausado.clear()
                raise RuntimeError("Não foi possível salvar a preferência do microfone no perfil local do Windows.") from exc
            self._microphone_preference = preference
            self._apply_microphone_device(target_index, device_id)
            self._microphone_error = None
            self._voice_state = "iniciando"
            if self._started and not was_paused and not self._stop.is_set():
                self._main.pausado.clear()
        return {"selected_id": device_id, "selected_name": selected["name"] if selected else "Padrão do sistema",
                "selected_available": True, "active_name": selected["name"] if selected else
                next(item["name"] for item in inputs if item["index"] == target_index)}

    def _apply_microphone_device(self, device_index, device_id=None):
        with self._microphone_lock:
            current = getattr(self._ouvido, "device_index", self._microphone_device_index)
            current_id = getattr(self._ouvido, "device_id", self._microphone_device_id)
            if self._microphone_device_index == device_index and current == device_index and current_id == device_id:
                return
            was_paused = bool(self._started and self._main.pausado.is_set())
            if self._started and not was_paused:
                self._main.pausado.set()
            ouvido = self._ouvido
            deadline = time.monotonic() + 4.0
            while ouvido is not None and ouvido.capturando.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            if ouvido is not None and ouvido.capturando.is_set():
                raise RuntimeError("A captura atual não foi liberada para atualizar o microfone.")
            self._microphone_device_index = device_index
            self._microphone_device_id = device_id
            if ouvido is not None and hasattr(ouvido, "set_device"):
                ouvido.set_device(device_index, device_id)
            if device_index == -1:
                name = self._microphone_preference["name"] if self._microphone_preference else "Padrão do sistema"
                self._microphone_error = f"O microfone selecionado não está disponível: {name}. Escolha outra entrada antes de retomar a escuta."
                self._voice_state = "erro"
            elif self._microphone_error and "não está disponível" in self._microphone_error:
                self._microphone_error = None
                self._voice_state = "iniciando"
            if self._started and not was_paused and not self._stop.is_set():
                self._main.pausado.clear()

    def submit_command(self, text: str) -> str:
        if not self._started or self._stop.is_set():
            raise RuntimeError("O ULTRON Desktop não está em execução.")
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("O comando deve conter de 1 a 4000 caracteres.")
        operation_id = uuid.uuid4().hex
        self._commands.put((operation_id, text.strip()))
        return operation_id

    # ---- sessão local (ed0): Hello, PIN e bloqueio
    def _log_seg(self, acao: str, decisao: str, motivo: str) -> None:
        try:
            security = self._security or importlib.import_module("seguranca")
            security.log_seg("desktop", acao, "-", decisao, motivo)
        except Exception:
            pass

    def _biometria(self):
        try:
            return importlib.import_module("biometria")
        except Exception:
            return None

    def unlock_info(self) -> dict:
        bio = self._biometria()
        try:
            hello = bio.disponivel() if bio else {"disponivel": False, "motivo": "Windows Hello indisponível"}
        except Exception:
            hello = {"disponivel": False, "motivo": "Windows Hello indisponível"}
        try:
            security = self._security or importlib.import_module("seguranca")
        except Exception:
            security = None
        try:
            pin_configurado = bool(security.pin_configurado())
        except Exception:
            pin_configurado = False
        try:
            irreversiveis = sorted(getattr(security, "IRREVERSIVEIS", ()))
        except Exception:
            irreversiveis = []
        info = {
            "session": sessao.estado(),
            "hello": hello,
            "pin_configurado": pin_configurado,
            "irreversiveis": irreversiveis,
            "versao": self.update_info().get("current_version", "desconhecida"),
        }
        try:
            import memoria
            info["historico"] = memoria.status_criptografia()
        except Exception:
            pass          # 5it ainda não existe: a tela mostra só "histórico local"
        return info

    def undo_list(self, limite: int = 10) -> dict:
        limite = max(1, min(int(limite), 20))
        try:
            diario = importlib.import_module("desfazer")
            itens = diario.listar(limite)
        except Exception as erro:
            print(f"[aviso] diário de desfazer indisponível: {type(erro).__name__}")
            return {"itens": [], "limite": limite, "indisponivel": True}
        return {"itens": itens, "limite": limite}

    def unlock_hello(self) -> dict:
        bio = self._biometria()
        try:
            hello = bio.disponivel() if bio else {"disponivel": False}
        except Exception:
            hello = {"disponivel": False}
        if not hello.get("disponivel"):
            self._log_seg("unlock", "DENY", "hello_unavailable")
            return {"unlocked": False, "error": "hello_unavailable"}
        try:
            verificado = bio.verificar() is True
        except bio.Ocupado:
            return {"unlocked": False, "error": "busy"}
        except Exception:
            verificado = False
        if not verificado:
            self._log_seg("unlock", "DENY", "hello_not_verified")
            return {"unlocked": False, "error": "not_verified"}
        estado = sessao.desbloquear("hello")
        self._log_seg("unlock", "ALLOW", "hello_verified")
        return {"unlocked": True, "method": "hello", "session": estado}

    def unlock_pin(self, pin: str) -> dict:
        if time.monotonic() < self._unlock_espera_ate:
            self._log_seg("unlock", "DENY", "pin_locked_out")
            return {"unlocked": False, "error": "too_many_attempts"}
        try:
            security = self._security or importlib.import_module("seguranca")
            tem_pin = bool(security.pin_configurado())
        except Exception:
            security = None
            tem_pin = False
        if not tem_pin:
            self._log_seg("unlock", "DENY", "no_method_configured")
            return {"unlocked": False, "error": "no_method_configured"}
        try:
            valido = bool(security.pin_valido(pin))
        except Exception:
            valido = False
        if not valido:
            with self._unlock_lock:
                self._unlock_falhas += 1
                bloqueado = self._unlock_falhas >= UNLOCK_FALHAS_MAX
                if bloqueado:
                    self._unlock_falhas = 0
                    self._unlock_espera_ate = time.monotonic() + UNLOCK_ESPERA_S
            self._log_seg("unlock", "DENY", "pin_locked_out" if bloqueado else "pin_invalid_or_missing")
            return {"unlocked": False, "error": "too_many_attempts" if bloqueado else "pin_invalid"}
        with self._unlock_lock:
            self._unlock_falhas = 0
            self._unlock_espera_ate = 0.0
        estado = sessao.desbloquear("pin")
        self._log_seg("unlock", "ALLOW", "pin_verified")
        return {"unlocked": True, "method": "pin", "session": estado}

    def lock(self) -> dict:
        sessao.bloquear()
        self._log_seg("lock", "ALLOW", "session_locked")
        return {"locked": True}

    def get_snapshot(self) -> dict:
        autostart = False
        try:
            autostart = importlib.import_module("desktop_autostart").is_installed()
        except Exception:
            autostart = False
        metrics = {}
        try:
            psutil = importlib.import_module("psutil")
            metrics = {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "ram_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage(os.path.abspath(os.sep)).percent,
            }
        except Exception:
            pass
        palco_atual = None
        try:
            import palco
            palco_atual = palco.estado()
        except Exception:
            palco_atual = None
        return {
            **metrics,
            "core_running": bool(self._started and not self._stop.is_set()),
            "api_running": self._api_running,
            "microphone_paused": bool(self._main is not None and self._main.pausado.is_set()),
            "speaking": bool(getattr(sys.modules.get("voz"), "falando", None) and sys.modules["voz"].falando.is_set()),
            "microphone_state": self._voice_state,
            "microphone_error": self._microphone_error,
            "microphone_capturing": bool(self._ouvido is not None and self._ouvido.capturando.is_set()),
            "microphone_level": int(getattr(self._ouvido, "nivel_atual", 0)) if self._ouvido else 0,
            "microphone_threshold": int(getattr(self._ouvido, "limiar", 0)) if self._ouvido else 0,
            "microphone_device": self._microphone_preference["name"] if self._microphone_preference else "Padrão do sistema",
            "microphone_device_available": self._microphone_device_index != -1,
            "autostart_installed": autostart,
            "shutdown_requested": self._shutdown_requested,
            "error": self._error,
            "palco": palco_atual,
            "session_desbloqueada": bool(sessao.estado()["desbloqueada"]),
        }

    def fechar_palco(self) -> dict:
        """Fecha o palco da interface e limpa o estado compartilhado."""
        import palco
        return palco.fechar()

    def _notify(self, text: str) -> None:
        try:
            safe_text = self._security.redigir(str(text))[:1000]
        except Exception:
            safe_text = "Notificação do ULTRON."
        self._events.put({"type": "notification", "message": safe_text})

    def poll_events(self) -> list[dict]:
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        try:
            import palco
            events.extend(palco.eventos())
        except Exception:
            pass
        return events

    def answer_confirmation(self, request_id: str, approved: bool, pin: str | None = None) -> bool:
        if not isinstance(request_id, str) or type(approved) is not bool:
            return False
        if pin is not None and not isinstance(pin, str):
            return False
        with self._pending_lock:
            pending = self._pending.get(request_id)
            if pending is None or pending["expired"] or pending["event"].is_set():
                return False
            pending["approved"] = approved
            pending["pin"] = pin if approved else None
            pending["event"].set()
            return True

    def _confirmar(self, message: str, pedido: dict):
        request_id = uuid.uuid4().hex
        risk = str(pedido.get("risco", "")).upper()
        desbloqueada = sessao.estado()["desbloqueada"]
        requires_pin = (risk == "CRITICO" or bool(pedido.get("exige_pin"))) and not desbloqueada
        pending = {
            "event": threading.Event(),
            "approved": False,
            "pin": None,
            "expired": False,
            "pedido": pedido,
            "requires_pin": requires_pin,
        }
        with self._pending_lock:
            self._pending[request_id] = pending
        self._events.put({
            "type": "confirmation_request",
            "request_id": request_id,
            "message": str(message)[:1000],
            "risk": risk,
            "requires_pin": requires_pin,
        })
        try:
            timeout = max(0.0, float(self._security.timeout("confirmacao_teclado")))
        except Exception:
            timeout = 20.0
        answered = pending["event"].wait(timeout)
        with self._pending_lock:
            if not answered:
                pending["expired"] = True
            self._pending.pop(request_id, None)
            approved = pending["approved"] if answered else False
            pin = pending["pin"]
            pending["pin"] = None
        if not answered or not approved:
            return False if answered else None
        if requires_pin:
            try:
                valid = bool(pin) and bool(self._security.pin_valido(pin))
            except Exception:
                valid = False
            if not valid:
                try:
                    self._security.log_seg(
                        pedido.get("origem", "desktop"), pedido.get("acao", ""), risk,
                        "DENY", "pin_invalid_or_missing")
                except Exception:
                    pass
                return False
        return True

    def _falar_resposta(self, texto: str) -> None:
        """Fala uma resposta digitada; roda em segundo plano para o painel não esperar o áudio."""
        try:
            import voz
            voz.falar(texto)
        except Exception as erro:
            try:
                self._security.log.warning(f"Voz da resposta digitada falhou: {type(erro).__name__}")
            except Exception:
                pass

    def _agendar_fala(self, texto) -> None:
        """Só fala texto de verdade (confirmações devolvem True/False/None)."""
        if not isinstance(texto, str) or not texto.strip() or self._stop.is_set():
            return
        threading.Thread(target=self._falar_resposta, args=(texto,),
                         name="ultron-desktop-fala", daemon=True).start()

    def _command_loop(self) -> None:
        while True:
            item = self._commands.get()
            if item is None:
                return
            operation_id, text = item
            if self._stop.is_set():
                response = "Comando cancelado pelo encerramento do ULTRON Desktop."
            else:
                try:
                    response = self._cerebro.processar(text, self._confirmar, "desktop")
                except Exception:
                    self._error = "Falha ao processar um comando do Desktop."
                    try:
                        self._security.log.error(self._error)
                    except Exception:
                        pass
                    response = self._error
            # O painel já mostrou estes turnos ao digitar; guardamos para a
            # reconciliação periódica não apagar a conversa digitada.
            self._registrar_conversa("user", text, "texto", emitir=False)
            self._registrar_conversa("assistant", response, "texto", emitir=False)
            self._events.put({"type": "command_result", "operation_id": operation_id,
                              "response": response})
            self._agendar_fala(response)

