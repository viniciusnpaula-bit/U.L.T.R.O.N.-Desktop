"""Lifecycle and request coordination for the local Desktop panel."""
from __future__ import annotations

import importlib
import inspect
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from microphone_devices import enumerate_input_devices

import config
import sessao

# Limite de falhas de PIN e janela de espera (persistidos em dados/sessao.json).
UNLOCK_FALHAS_MAX = 5
UNLOCK_ESPERA_S = 30.0
ARQUIVO_SESSAO = getattr(config, "ARQUIVO_SESSAO", getattr(config, "DIR_DADOS", config.BASE / "dados") / "sessao.json")


class DesktopRuntime:
    """Runs one core voice loop and serializes Desktop commands through the core."""

    def __init__(self, start_voice: bool = True, stop_event: threading.Event | None = None):
        self.start_voice = start_voice
        self._events: queue.Queue[dict] = queue.Queue()
        self._commands: queue.Queue[tuple[str, str, str] | None] = queue.Queue()
        self._workflow_pending: dict[str, str] = {}
        self._workflow_lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._microphone_lock = threading.RLock()
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._started = False
        self._api_running = False
        self._shutdown_requested = False
        self._error: str | None = None
        self._voice_state = "iniciando" if start_voice else "desativado"
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
        self._speech_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._speech_thread: threading.Thread | None = None
        self._speech_lock = threading.Lock()
        self._recent_notifications: dict[str, float] = {}
        self._pending_notifications: set[str] = set()
        self._speaking_notification: str | None = None
        self._stop_hook = None
        self._voz_barge_in_hook = None

        self._unlock_lock = threading.Lock()
        self._unlock_falhas, self._unlock_espera_ate = self._ler_estado_unlock()
        self._session_thread: threading.Thread | None = None
        self._vigilancia_disco = None
        self._vigilancia_processos = None
        self._mobile_lock = threading.Lock()
        self._mobile_server = None
        self._mobile_thread: threading.Thread | None = None
        self._mobile_api_running = False
        self._mobile_api_url: str | None = None

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
            self._voice_state = "iniciando" if self.start_voice else "desativado"
            self._microphone_error = None
            if self.start_voice:
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
                if self._notification_callback not in notifiers:
                    notifiers.append(self._notification_callback)
            hooks = getattr(self._security, "ganchos_parada", None)
            if isinstance(hooks, list):
                self._stop_hook = self._on_emergency_stop
                if self._stop_hook not in hooks:
                    hooks.append(self._stop_hook)
            if self.start_voice:
                try:
                    self._registrar_barge_in_voz(importlib.import_module("voz"))
                except Exception:
                    pass
            with self._speech_lock:
                while True:
                    try:
                        self._speech_queue.get_nowait()
                    except queue.Empty:
                        break
                self._pending_notifications.clear()
                self._recent_notifications.clear()
                self._speaking_notification = None
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
                self._speech_thread = threading.Thread(
                    target=self._speech_loop, name="ultron-desktop-fala", daemon=True)
                self._speech_thread.start()
                self._voice_thread = threading.Thread(
                    target=self._voice_loop, name="ultron-desktop-voice", daemon=True)
                self._voice_thread.start()
            try:
                import vigilancia_disco
                self._vigilancia_disco = vigilancia_disco.VigilanciaDisco()
                self._vigilancia_disco.iniciar()
            except Exception as e:
                logging.getLogger("ultron.desktop").warning("Falha ao iniciar vigilancia_disco: %s", e)
            try:
                import vigilancia_processos
                self._vigilancia_processos = vigilancia_processos.VigilanciaProcessos()
                self._vigilancia_processos.iniciar()
            except Exception as e:
                logging.getLogger("ultron.desktop").warning("Falha ao iniciar vigilancia_processos: %s", e)

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
            if "notificar_voz" in parameters:
                kwargs["notificar_voz"] = False
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
        termo = str(busca or "").strip()[:300]
        try:
            fatos = memoria.buscar_fatos(termo, 50) if termo else memoria.fatos_com_id(50)
            return {"fatos": fatos or [], "limite": 50}
        except Exception:
            return {"fatos": [], "limite": 50}

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

    def agenda_listar(self) -> dict:
        import memoria
        return {"eventos": memoria.eventos_numerados(),
                "aviso": "Eventos e fluxos agendados só disparam com o ULTRON aberto."}

    def agenda_criar(self, texto, quando, repetir="") -> dict:
        import ferramentas
        import memoria
        minutos = memoria.minutos_de_recorrencia(repetir)
        due = ferramentas._quando_do_texto(quando)
        memoria.add_evento(due, texto, minutos)
        return {"mensagem": "Evento criado.", **self.agenda_listar()}

    def agenda_cancelar(self, numero=None, trecho=None) -> dict:
        import memoria
        mensagem = memoria.cancelar_evento(numero=numero, trecho=trecho or "")
        return {"mensagem": mensagem, **self.agenda_listar()}

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

    def skills_listar(self) -> dict:
        import skills
        return {
            "skills": [
                {"slug": s.slug, "nome": s.nome, "descricao": s.descricao,
                 "quando": s.quando, "estado": skills.estado(s)}
                for s in skills.listar()
            ],
            "pendentes": [
                {"slug": s.slug, "nome": s.nome, "quando": s.quando, "corpo": s.corpo}
                for s in skills.pendentes()
            ],
        }

    def skills_aprovar(self, nome: str) -> dict:
        import skills
        return {"ok": True, "slug": skills.aprovar(nome)}

    def skills_descartar(self, nome: str) -> dict:
        import skills
        skills.descartar(nome)
        return {"ok": True}

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
            self._cancelar_falas(parar_voz=True)
            with self._speech_lock:
                speech_thread = self._speech_thread
                if speech_thread is not None:
                    self._speech_queue.put(None)

            ouvido = self._ouvido
            deadline = time.monotonic() + 4.0
            while ouvido is not None and ouvido.capturando.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            for thread in (self._voice_thread, self._command_thread, self._session_thread):
                if thread is not None and thread is not threading.current_thread():
                    thread.join(timeout=4.5)
            if speech_thread is not None and speech_thread is not threading.current_thread():
                speech_thread.join(timeout=1.5)
            self._speech_thread = None
            self._session_thread = None
            if self._vigilancia_disco is not None:
                try:
                    self._vigilancia_disco.parar()
                except Exception:
                    pass
                self._vigilancia_disco = None
            if self._vigilancia_processos is not None:
                try:
                    self._vigilancia_processos.parar()
                except Exception:
                    pass
                self._vigilancia_processos = None
            self.stop_mobile_server()
            self._api_running = False
            self._started = False
            notifiers = getattr(self._cerebro, "NOTIFICADORES", None)
            if isinstance(notifiers, list) and self._notification_callback in notifiers:
                notifiers.remove(self._notification_callback)
            self._notification_callback = None
            hooks = getattr(self._security, "ganchos_parada", None)
            if isinstance(hooks, list) and self._stop_hook in hooks:
                hooks.remove(self._stop_hook)
            self._stop_hook = None
            try:
                self._remover_barge_in_voz(sys.modules.get("voz"))
            except Exception:
                pass

    def request_shutdown(self) -> None:
        self._shutdown_requested = True

    def set_api_running(self, running: bool) -> None:
        self._api_running = bool(running)

    def set_mobile_api_state(self, running: bool, url: str | None = None) -> None:
        self._mobile_api_running = bool(running)
        self._mobile_api_url = str(url) if (running and url) else None

    def ensure_mobile_server_running(self) -> bool:
        """Inicia o servidor LAN Mobile sob demanda quando houver pareamento ativo."""
        if not getattr(config, "MOBILE_ENABLED", True):
            return False
        with self._mobile_lock:
            if self._mobile_server is not None and self._mobile_api_running:
                return True
            import mobile_api
            import mobile_pairing
            if not mobile_pairing.tem_pareamento_ativo():
                return False
            srv, mobile_url = mobile_api.create_mobile_server(self)
            t = threading.Thread(target=srv.serve_forever, name="ultron-mobile-api", daemon=True)
            t.start()
            self._mobile_server = srv
            self._mobile_thread = t
            self.set_mobile_api_state(True, mobile_url)
            return True

    def stop_mobile_server(self) -> None:
        with self._mobile_lock:
            srv = self._mobile_server
            t = self._mobile_thread
            self._mobile_server = None
            self._mobile_thread = None
            self.set_mobile_api_state(False, None)
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass
        if t is not None and t is not threading.current_thread():
            t.join(timeout=3)

    def mobile_pairing_status(self) -> dict:
        import mobile_pairing
        dados = mobile_pairing.status_publico()
        dados["mobile_server_running"] = bool(self._mobile_api_running)
        dados["mobile_server_url"] = self._mobile_api_url
        return dados

    def mobile_pairing_rotate(
        self,
        device_id: str | None = None,
        killswitch_separado: bool = False,
    ) -> dict:
        import mobile_pairing
        resultado = mobile_pairing.criar_ou_rotacionar(
            device_id=device_id,
            killswitch_separado=bool(killswitch_separado),
        )
        try:
            self.ensure_mobile_server_running()
        except Exception as erro:
            self._registrar_falha("mobile_api.start", erro)
        resultado["mobile_server_running"] = bool(self._mobile_api_running)
        resultado["mobile_server_url"] = self._mobile_api_url
        self._log_seg("mobile_pairing_rotate", "ALLOW", "user_requested")
        return resultado

    def mobile_pairing_revoke(self, device_id: str | None = None) -> dict:
        import mobile_pairing
        resultado = mobile_pairing.revogar(device_id)
        if not resultado.get("configured"):
            self.stop_mobile_server()
        resultado["mobile_server_running"] = bool(self._mobile_api_running)
        self._log_seg("mobile_pairing_revoke", "ALLOW", "user_requested")
        return resultado

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
        self._commands.put((operation_id, "comando", text.strip()))
        return operation_id

    def submit_fluxo(self, fluxo_id: str) -> str:
        if not self._started or self._stop.is_set():
            raise RuntimeError("O ULTRON Desktop não está em execução.")
        if not isinstance(fluxo_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,39}", fluxo_id):
            raise ValueError("Identificador de fluxo inválido.")
        with self._workflow_lock:
            pendente = self._workflow_pending.get(fluxo_id)
            if pendente:
                return pendente
        import fluxos
        if fluxos.obter(fluxo_id) is None:
            raise LookupError(fluxo_id)
        with self._workflow_lock:
            pendente = self._workflow_pending.get(fluxo_id)
            if pendente:
                return pendente
            operation_id = uuid.uuid4().hex
            self._workflow_pending[fluxo_id] = operation_id
            self._commands.put((operation_id, "fluxo", fluxo_id))
            return operation_id

    def _executar_fluxo_direto(self, fluxo_id: str) -> str:
        import ferramentas
        return ferramentas.executar("executar_fluxo", {"fluxo": fluxo_id}, self._confirmar, "desktop")

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
            "admin_elevated": getattr(security, "eh_admin", lambda: False)(),
            "admin_mode": getattr(security, "modo_admin_ativo", lambda o: False)("desktop"),
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

    # ---- tentativas de PIN persistidas entre reinícios (dados/sessao.json)
    @staticmethod
    def _ler_estado_unlock() -> tuple[int, float]:
        try:
            value = json.loads(ARQUIVO_SESSAO.read_text(encoding="utf-8"))
            falhas = int(value.get("unlock_falhas", 0))
            espera = float(value.get("unlock_espera_ate", 0.0))
            return max(0, falhas), max(0.0, espera)
        except (OSError, ValueError, TypeError, AttributeError):
            return 0, 0.0

    @staticmethod
    def _gravar_estado_unlock(falhas: int, espera_ate: float) -> None:
        try:
            ARQUIVO_SESSAO.parent.mkdir(parents=True, exist_ok=True)
            temporary = ARQUIVO_SESSAO.with_suffix(".tmp")
            temporary.write_text(json.dumps({"unlock_falhas": int(falhas),
                                             "unlock_espera_ate": float(espera_ate)}),
                                 encoding="utf-8")
            temporary.replace(ARQUIVO_SESSAO)
        except OSError:
            pass          # sem arquivo o bloqueio continua valendo nesta execução

    def unlock_pin(self, pin: str) -> dict:
        if time.time() < self._unlock_espera_ate:
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
                    self._unlock_espera_ate = time.time() + UNLOCK_ESPERA_S
                self._gravar_estado_unlock(self._unlock_falhas, self._unlock_espera_ate)
            self._log_seg("unlock", "DENY", "pin_locked_out" if bloqueado else "pin_invalid_or_missing")
            return {"unlocked": False, "error": "too_many_attempts" if bloqueado else "pin_invalid"}
        with self._unlock_lock:
            self._unlock_falhas = 0
            self._unlock_espera_ate = 0.0
            self._gravar_estado_unlock(0, 0.0)
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
            "admin_elevated": getattr(self._security, "eh_admin", lambda: False)(),
            "admin_mode": getattr(self._security, "modo_admin_ativo", lambda o: False)("desktop"),
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
            full_text = str(self._security.redigir(str(text)))
        except Exception:
            full_text = "Notificação do ULTRON."
        self._events.put({"type": "notification", "message": full_text[:1000]})
        self._agendar_fala(full_text[:4000], notificacao=True)

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

    _DEDUP_NOTIFICACAO_S = 2.0

    @staticmethod
    def _normalizar_fala(texto: str) -> str:
        return " ".join(str(texto).split()).strip()

    def _parada_ativa(self) -> bool:
        parada = getattr(self._security, "parada", None)
        return bool(parada is not None and callable(getattr(parada, "is_set", None)) and parada.is_set())

    def _voz_habilitada(self, *, notificacao: bool = False) -> bool:
        if not self.start_voice or not self._started:
            return False
        if self._stop.is_set() or self._shutdown_requested or self._parada_ativa():
            return False
        if not bool(getattr(config, "VOZ_ATIVO", True)):
            return False
        voz_conf = str(getattr(config, "VOZ", "pt-BR-AntonioNeural") or "").strip().lower()
        if voz_conf in {"off", "desligada", "desligado", "none", "false", "0"}:
            return False
        voz_mod = sys.modules.get("voz")
        pref_fn = getattr(voz_mod, "preferencias", None)
        if callable(pref_fn):
            try:
                prefs = pref_fn() or {}
                if isinstance(prefs, dict):
                    if prefs.get("ativa") is False or prefs.get("ativo") is False:
                        return False
                    if notificacao and prefs.get("notificacoes") is False:
                        return False
            except Exception:
                pass
        if notificacao:
            if not bool(getattr(config, "VOZ_NOTIFICACOES", True)):
                return False
            pausado = getattr(self._main, "pausado", None)
            if pausado is not None and callable(getattr(pausado, "is_set", None)) and pausado.is_set():
                return False
        return True

    def _on_emergency_stop(self) -> None:
        self._cancelar_falas(parar_voz=True)

    def _registrar_barge_in_voz(self, voz_mod) -> None:
        registrar = getattr(voz_mod, "registrar_gancho_parada", None)
        if not callable(registrar):
            return
        if self._voz_barge_in_hook is None:
            self._voz_barge_in_hook = lambda: self._cancelar_falas(parar_voz=False)
        registrar(self._voz_barge_in_hook)

    def _remover_barge_in_voz(self, voz_mod) -> None:
        remover = getattr(voz_mod, "remover_gancho_parada", None)
        if callable(remover) and self._voz_barge_in_hook is not None:
            remover(self._voz_barge_in_hook)
        self._voz_barge_in_hook = None

    def _cancelar_falas(self, *, parar_voz: bool = False) -> None:
        with self._speech_lock:
            while True:
                try:
                    self._speech_queue.get_nowait()
                except queue.Empty:
                    break
            self._pending_notifications.clear()
            self._recent_notifications.clear()
        if parar_voz:
            voz_mod = sys.modules.get("voz")
            parar = getattr(voz_mod, "parar_fala", None)
            if callable(parar):
                try:
                    parar()
                except Exception:
                    pass

    def _falar_resposta(self, texto: str) -> None:
        """Fala uma resposta ou aviso; roda em segundo plano para o painel não esperar o áudio."""
        try:
            import voz
            voz.falar(texto)
        except Exception as erro:
            try:
                self._security.log.warning(f"Voz da resposta/aviso falhou: {type(erro).__name__}")
            except Exception:
                self._registrar_falha("voz.falar", erro)

    def _speech_loop(self) -> None:
        while True:
            item = self._speech_queue.get()
            if item is None:
                return
            origem, texto = item
            notificacao = origem == "notificacao"
            chave = self._normalizar_fala(texto) if notificacao else None
            if notificacao and chave:
                with self._speech_lock:
                    self._pending_notifications.discard(chave)
            if not self._voz_habilitada(notificacao=notificacao):
                continue
            if notificacao and chave:
                with self._speech_lock:
                    self._speaking_notification = chave
            try:
                self._falar_resposta(texto)
            finally:
                if notificacao:
                    with self._speech_lock:
                        self._speaking_notification = None

    def _agendar_fala(self, texto, *, notificacao: bool = False) -> None:
        """Só fala texto de verdade (confirmações devolvem True/False/None)."""
        if not isinstance(texto, str) or not texto.strip():
            return
        if not self._voz_habilitada(notificacao=notificacao):
            return
        chave = self._normalizar_fala(texto)
        if not chave:
            return
        with self._speech_lock:
            if not self._voz_habilitada(notificacao=notificacao):
                return
            if notificacao:
                agora = time.monotonic()
                expiradas = [k for k, ts in self._recent_notifications.items()
                             if agora - ts > self._DEDUP_NOTIFICACAO_S]
                for k in expiradas:
                    self._recent_notifications.pop(k, None)
                if chave == self._speaking_notification or chave in self._pending_notifications:
                    return
                ultimo = self._recent_notifications.get(chave)
                if ultimo is not None and (agora - ultimo) < self._DEDUP_NOTIFICACAO_S:
                    return
                self._recent_notifications[chave] = agora
                self._pending_notifications.add(chave)
            if self._speech_thread is None or not self._speech_thread.is_alive():
                self._speech_thread = threading.Thread(
                    target=self._speech_loop, name="ultron-desktop-fala", daemon=True)
                self._speech_thread.start()
            self._speech_queue.put(("notificacao" if notificacao else "resposta", texto))

    def _command_loop(self) -> None:
        while True:
            item = self._commands.get()
            if item is None:
                return
            operation_id, tipo, valor = item
            workflow_id = valor if tipo == "fluxo" else None
            if self._stop.is_set():
                response = "Comando cancelado pelo encerramento do ULTRON Desktop."
            elif workflow_id is not None:
                try:
                    response = self._executar_fluxo_direto(workflow_id)
                except Exception:
                    self._error = "Falha ao executar um fluxo do Desktop."
                    try:
                        self._security.log.error(self._error)
                    except Exception:
                        pass
                    response = self._error
            else:
                try:
                    response = self._cerebro.processar(valor, self._confirmar, "desktop")
                except Exception:
                    self._error = "Falha ao processar um comando do Desktop."
                    try:
                        self._security.log.error(self._error)
                    except Exception:
                        pass
                    response = self._error
            # O painel já mostrou os comandos digitados; registra o acionamento
            # do fluxo sem pedir ao modelo para interpretar seu identificador.
            texto_usuario = f"Executar fluxo: {workflow_id}" if workflow_id else valor
            self._registrar_conversa("user", texto_usuario, "texto", emitir=False)
            self._registrar_conversa("assistant", response, "texto", emitir=False)
            evento = {"type": "command_result", "operation_id": operation_id,
                      "response": response}
            if workflow_id is not None:
                evento["workflow_id"] = workflow_id
            self._events.put(evento)
            if workflow_id is not None:
                with self._workflow_lock:
                    if self._workflow_pending.get(workflow_id) == operation_id:
                        self._workflow_pending.pop(workflow_id, None)
            self._agendar_fala(response)

    # ---- Bloco 1: Arquivos, Downloads e Disco
    def obter_estado_bloco1(self) -> dict:
        import disco_ops
        import seguranca
        cfg = disco_ops.carregar_config_bloco1()
        status_monitores = self._vigilancia_disco.status() if self._vigilancia_disco else {"ativo": False}
        return {
            "config": cfg,
            "status_monitores": status_monitores,
            "admin_elevated": seguranca.eh_admin(),
            "admin_mode": seguranca.modo_admin_ativo("desktop"),
        }

    def atualizar_config_bloco1(self, dados: dict) -> dict:
        import disco_ops
        nova_cfg = disco_ops.salvar_config_bloco1(dados)
        return {"sucesso": True, "config": nova_cfg}

    def executar_acao_bloco1(self, acao: str, params: dict | None = None) -> dict:
        import disco_ops
        params = params or {}
        acoes = {
            "organizar_pdf": lambda: disco_ops.organizar_pdf_downloads(params.get("pasta", "~/Downloads"), params.get("aplicar", True)),
            "extrair_instalador": lambda: disco_ops.extrair_e_limpar_instalador(params.get("arquivo", ""), params.get("destino", ""), params.get("apagar_origem", False)),
            "limpar_duplicados": lambda: disco_ops.limpar_duplicados(params.get("pasta", ""), params.get("executar", False)),
            "limpar_disco": lambda: disco_ops.limpar_disco(params.get("executar", True), params.get("incluir_docker", True), params.get("incluir_builds", True)),
            "converter_imagens": lambda: disco_ops.converter_imagens(params.get("alvo", ""), params.get("formato", "png"), params.get("apagar_original", False)),
            "arquivar_projetos": lambda: disco_ops.arquivar_projetos_antigos(params.get("pasta", ""), params.get("meses", 6), params.get("executar", False)),
            "backup_incremental": lambda: disco_ops.executar_backup_incremental(params.get("origem", ""), params.get("destino", "")),
            "arquivar_capturas": lambda: disco_ops.arquivar_capturas_desktop(params.get("dias", 7), params.get("executar", True)),
            "corrigir_permissoes": lambda: disco_ops.corrigir_permissoes_pasta(params.get("pasta", ""), params.get("remover_readonly", True), params.get("corrigir_acl", True)),
            "ejetar_usb": lambda: disco_ops.ejetar_usb_ocioso(params.get("unidade", ""), params.get("minutos_ocioso", 5)),
        }
        fn = acoes.get(acao)
        if not fn:
            return {"sucesso": False, "erro": f"Ação desconhecida: {acao}"}
        try:
            resultado = fn()
            return {"sucesso": True, "resultado": resultado}
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}

    # ---- Bloco 2: Processos, Memória e Hardware
    def obter_estado_bloco2(self) -> dict:
        import processos_ops
        import seguranca
        cfg = processos_ops.carregar_config_bloco2()
        status_monitores = self._vigilancia_processos.status() if self._vigilancia_processos else {"ativo": False}
        return {
            "config": cfg,
            "status_monitores": status_monitores,
            "admin_elevated": seguranca.eh_admin(),
            "admin_mode": seguranca.modo_admin_ativo("desktop"),
            "temperatura_cpu": processos_ops._obter_temperatura_cpu(),
            "plano_ativo": processos_ops._obter_plano_energia_ativo(),
        }

    def atualizar_config_bloco2(self, dados: dict) -> dict:
        import processos_ops
        nova_cfg = processos_ops.salvar_config_bloco2(dados)
        return {"sucesso": True, "config": nova_cfg}

    def executar_acao_bloco2(self, acao: str, params: dict | None = None) -> dict:
        import processos_ops
        params = params or {}
        acoes = {
            "suspender_abas": lambda: processos_ops.suspender_abas_pesadas(params.get("limite_mb", 500), params.get("desuspender", False), params.get("simular", False)),
            "matar_travados": lambda: processos_ops.encerrar_processos_travados(params.get("matar", True)),
            "plano_energia": lambda: processos_ops.gerenciar_plano_energia(params.get("modo", "auto"), params.get("esquema", "")),
            "otimizar_cpu": lambda: processos_ops.otimizar_cpu_foco(params.get("em_reuniao_ou_jogo"), params.get("aplicar", True)),
            "proteger_temperatura": lambda: processos_ops.proteger_temperatura(params.get("limite_celsius", 82), params.get("simular", False)),
            "guardiao_startup": lambda: processos_ops.guardiao_startup(params.get("acao", "auditar"), params.get("item", "")),
            "otimizar_janela_ativa": lambda: processos_ops.otimizar_janela_ativa(params.get("aplicar", True)),
            "limpar_ram": lambda: processos_ops.limpar_ram_ociosa(params.get("agressivo", False)),
            "ajustar_display": lambda: processos_ops.ajustar_display(params.get("brilho"), params.get("temperatura_k"), params.get("taxa_hz"), params.get("modo", "auto")),
            "bluetooth_ocioso": lambda: processos_ops.desconectar_bluetooth_ocioso(params.get("minutos_ocioso", 5), params.get("executar", True)),
        }
        fn = acoes.get(acao)
        if not fn:
            return {"sucesso": False, "erro": f"Ação desconhecida: {acao}"}
        try:
            resultado = fn()
            return {"sucesso": True, "resultado": resultado}
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}

