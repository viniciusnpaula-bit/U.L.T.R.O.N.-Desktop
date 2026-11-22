"""Authenticated loopback-only HTTP API for ULTRON Desktop."""
from __future__ import annotations

import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent
_PACOTE = _RAIZ / "electron" / "package.json"


def _obter_versao() -> str:
    try:
        dados = json.loads(_PACOTE.read_text(encoding="utf-8"))
        versao = str(dados.get("version") or "").strip()
        if versao:
            return versao
    except (OSError, ValueError, AttributeError):
        pass
    return "3.0.0"



_PREFIX = "/api/v1/"
_MAX_BODY = 8192
_MAX_COMMAND = 4000
_FLUXO_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
_MAX_BUSCA = 300
_GET_ROUTES = {
    _PREFIX + "health",
    _PREFIX + "unlock",
    _PREFIX + "status",
    _PREFIX + "events",
    _PREFIX + "microphones",
    _PREFIX + "voz",
    _PREFIX + "cofre",
    _PREFIX + "fatos",
    _PREFIX + "fluxos",
    _PREFIX + "lembretes",
    _PREFIX + "agenda",
    _PREFIX + "personalidade",
    _PREFIX + "personalidade/previa",
    _PREFIX + "skills",
    _PREFIX + "update",
    _PREFIX + "update/check",
    _PREFIX + "undo",
    _PREFIX + "conversation",
    _PREFIX + "bloco1",
    _PREFIX + "bloco2",
    _PREFIX + "mobile/pairing",
}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


# Porta preferida: o launcher (ULTRON.exe) usa esta porta para saber quando o painel
# está pronto. Continua sendo só loopback; se estiver ocupada, uma porta livre é usada.
PREFERRED_PORT = 3900


def create_server(runtime, token: str, host: str = "127.0.0.1", port: int = PREFERRED_PORT):
    if host != "127.0.0.1":
        raise ValueError("A API do ULTRON só pode usar 127.0.0.1.")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("O token da API deve ser aleatório e ter pelo menos 32 caracteres.")

    class Handler(BaseHTTPRequestHandler):
        server_version = f"ULTRONDesktop/{_obter_versao()}"
        sys_version = ""

        def log_message(self, _format, *_args):
            # The standard access log can include local identifiers and is not needed here.
            return

        def _drenar_corpo(self, limite: int = 16 * 1024, espera: float = 0.2):
            """Descarta o resto do corpo antes de fechar a conexão.

            Sem isso o Windows devolve RST ao cliente (há bytes da requisição que
            ninguém leu) e a resposta de recusa — 401, 403, 413 — pode se perder
            no caminho. O limite evita ficar lendo um corpo enorme de propósito.
            """
            if getattr(self, "_corpo_lido", False):
                return
            self._corpo_lido = True
            try:
                restante = int(self.headers.get("Content-Length", "") or 0)
            except ValueError:
                return
            restante = max(0, min(restante, limite))
            if not restante:
                return
            try:
                self.connection.settimeout(espera)
                while restante > 0:
                    pedaco = self.rfile.read(min(8192, restante))
                    if not pedaco:
                        break
                    restante -= len(pedaco)
            except OSError:
                pass
            finally:
                try:
                    self.connection.settimeout(None)
                except OSError:
                    pass

        def _send(self, status: int, data: dict):
            self._drenar_corpo()
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host", "") != expected_host:
                self._send(403, {"error": "local_host_required"})
                return False
            origin = self.headers.get("Origin")
            expected_origin = f"http://{expected_host}"
            if origin is not None and origin != expected_origin:
                self._send(403, {"error": "local_origin_required"})
                return False
            provided = self.headers.get("X-ULTRON-Token", "")
            if not hmac.compare_digest(provided, token):
                self._send(401, {"error": "unauthorized"})
                return False
            return True

        def _path(self):
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment:
                return None
            return parsed.path

        def _read_json(self):
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send(415, {"error": "application_json_required"})
                return None
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self._send(400, {"error": "invalid_content_length"})
                return None
            if length < 0:
                self._send(400, {"error": "invalid_content_length"})
                return None
            if length > _MAX_BODY:
                self._send(413, {"error": "request_too_large"})
                return None
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                self._corpo_lido = True
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._corpo_lido = True
                self._send(400, {"error": "invalid_json"})
                return None
            if not isinstance(value, dict):
                self._send(400, {"error": "json_object_required"})
                return None
            return value

        @staticmethod
        def _cancelar_payload_valido(body) -> bool:
            if not isinstance(body, dict) or not set(body) <= {"numero", "trecho"}:
                return False
            numero = body.get("numero")
            trecho = body.get("trecho")
            if numero is not None and (type(numero) is not int or numero < 1):
                return False
            if trecho is not None and not isinstance(trecho, str):
                return False
            return numero is not None or bool(str(trecho or "").strip())

        def do_GET(self):
            if not self._authorized():
                return
            parsed = urlsplit(self.path)
            if parsed.fragment:
                self._send(400, {"error": "fragment_not_supported"})
                return
            path = parsed.path
            if path not in _GET_ROUTES:
                self._send(404, {"error": "not_found"})
                return
            if parsed.query:
                if path != _PREFIX + "fatos":
                    self._send(400, {"error": "query_not_supported"})
                    return
                try:
                    params = parse_qs(parsed.query, keep_blank_values=True, errors="replace")
                except Exception:
                    self._send(400, {"error": "invalid_query"})
                    return
                if set(params.keys()) - {"busca"}:
                    self._send(400, {"error": "invalid_query"})
                    return
                valores = params.get("busca", [])
                if len(valores) > 1:
                    self._send(400, {"error": "invalid_query"})
                    return
                termo = valores[0] if valores else ""
                if len(termo) > _MAX_BUSCA:
                    self._send(400, {"error": "query_too_long"})
                    return
                if "\x00" in termo:
                    self._send(400, {"error": "invalid_query"})
                    return
                busca_limpa = termo.strip()
                try:
                    if busca_limpa:
                        self._send(200, runtime.fatos_listar(busca=busca_limpa))
                    else:
                        self._send(200, runtime.fatos_listar())
                except TypeError:
                    self._send(200, runtime.fatos_listar())
                return
            try:
                if path == _PREFIX + "health":
                    self._send(200, {"ok": True, "version": _obter_versao()})
                elif path == _PREFIX + "unlock":
                    self._send(200, runtime.unlock_info())
                elif path == _PREFIX + "status":
                    self._send(200, runtime.get_snapshot())
                elif path == _PREFIX + "events":
                    self._send(200, {"events": runtime.poll_events()})
                elif path == _PREFIX + "microphones":
                    self._send(200, runtime.list_microphones())
                elif path == _PREFIX + "voz":
                    self._send(200, runtime.voz_info())
                elif path == _PREFIX + "cofre":
                    self._send(200, runtime.cofre_status())
                elif path == _PREFIX + "fatos":
                    self._send(200, runtime.fatos_listar())
                elif path == _PREFIX + "fluxos":
                    self._send(200, runtime.fluxos_listar())
                elif path == _PREFIX + "lembretes":
                    self._send(200, runtime.lembretes_listar())
                elif path == _PREFIX + "agenda":
                    self._send(200, runtime.agenda_listar())
                elif path == _PREFIX + "personalidade":
                    self._send(200, runtime.personalidade_info())
                elif path == _PREFIX + "personalidade/previa":
                    self._send(200, runtime.personalidade_previa())
                elif path == _PREFIX + "skills":
                    self._send(200, runtime.skills_listar())
                elif path == _PREFIX + "update":
                    self._send(200, runtime.update_info())
                elif path == _PREFIX + "update/check":
                    self._send(200, runtime.check_update())
                elif path == _PREFIX + "undo":
                    self._send(200, runtime.undo_list())
                elif path == _PREFIX + "conversation":
                    # Bate-papo: turnos da sessão (texto já redigido pelo runtime).
                    self._send(200, {"turns": runtime.conversation_turns()})
                elif path == _PREFIX + "bloco1":
                    self._send(200, runtime.obter_estado_bloco1())
                elif path == _PREFIX + "bloco2":
                    self._send(200, runtime.obter_estado_bloco2())
                elif path == _PREFIX + "mobile/pairing":
                    self._send(200, runtime.mobile_pairing_status())
                else:
                    self._send(404, {"error": "not_found"})
            except Exception:
                self._send(500, {"error": "internal_error"})

        def do_POST(self):
            if not self._authorized():
                return
            path = self._path()
            if path is None:
                self._send(400, {"error": "query_not_supported"})
                return
            body = self._read_json()
            if body is None:
                return
            try:
                if path == _PREFIX + "unlock":
                    metodo = body.get("method")
                    if metodo == "hello" and set(body) == {"method"}:
                        self._send(200, runtime.unlock_hello())
                    elif (metodo == "pin" and set(body) == {"method", "pin"}
                          and isinstance(body["pin"], str) and 1 <= len(body["pin"]) <= 64):
                        self._send(200, runtime.unlock_pin(body["pin"]))
                    else:
                        self._send(400, {"error": "invalid_unlock_payload"})
                elif path == _PREFIX + "lock":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    self._send(200, runtime.lock())
                elif path == _PREFIX + "commands":
                    if set(body) != {"text"}:
                        self._send(400, {"error": "invalid_command_payload"})
                        return
                    text = body["text"]
                    if not isinstance(text, str) or not text.strip() or len(text) > _MAX_COMMAND:
                        self._send(400, {"error": "invalid_command_text"})
                        return
                    operation_id = runtime.submit_command(text)
                    self._send(202, {"operation_id": operation_id})
                elif path == _PREFIX + "fluxos/executar":
                    if set(body) != {"id"} or not isinstance(body.get("id"), str) or not _FLUXO_ID.fullmatch(body["id"]):
                        self._send(400, {"error": "invalid_workflow_payload"})
                        return
                    try:
                        operation_id = runtime.submit_fluxo(body["id"])
                    except LookupError:
                        self._send(404, {"error": "workflow_not_found"})
                        return
                    self._send(202, {"operation_id": operation_id})
                elif path == _PREFIX + "microphone":
                    if set(body) != {"paused"} or type(body["paused"]) is not bool:
                        self._send(400, {"error": "invalid_microphone_payload"})
                        return
                    paused = body["paused"]
                    if not runtime.set_microphone_paused(paused):
                        self._send(409, {"error": "microphone_state_not_confirmed"})
                        return
                    self._send(200, {"paused": paused})
                elif path == _PREFIX + "microphone/device":
                    if set(body) != {"device_id"} or (body["device_id"] is not None and not isinstance(body["device_id"], str)):
                        self._send(400, {"error": "invalid_microphone_device_payload"})
                        return
                    try:
                        self._send(200, runtime.select_microphone(body["device_id"]))
                    except LookupError:
                        self._send(409, {"error": "microphone_device_unavailable"})
                elif path == _PREFIX + "confirmations":
                    allowed = {"request_id", "approved", "pin"}
                    if not {"request_id", "approved"}.issubset(body) or set(body) - allowed:
                        self._send(400, {"error": "invalid_confirmation_payload"})
                        return
                    if not isinstance(body["request_id"], str) or type(body["approved"]) is not bool:
                        self._send(400, {"error": "invalid_confirmation_payload"})
                        return
                    pin = body.get("pin")
                    if pin is not None and not isinstance(pin, str):
                        self._send(400, {"error": "invalid_confirmation_payload"})
                        return
                    accepted = runtime.answer_confirmation(body["request_id"], body["approved"], pin)
                    if not accepted:
                        self._send(404, {"error": "confirmation_not_pending"})
                        return
                    self._send(200, {"accepted": True})
                elif path == _PREFIX + "emergency-stop":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    import seguranca
                    seguranca.parar_tudo()
                    self._send(200, {"stopped": True})
                elif path == _PREFIX + "autostart":
                    if set(body) != {"enabled"} or type(body["enabled"]) is not bool:
                        self._send(400, {"error": "invalid_autostart_payload"})
                        return
                    self._send(200, runtime.set_autostart(body["enabled"]))
                elif path == _PREFIX + "palco/fechar":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    self._send(200, runtime.fechar_palco())
                elif path == _PREFIX + "voz":
                    if set(body) - {"voz", "pitch", "rate"}:
                        self._send(400, {"error": "invalid_voz_payload"})
                        return
                    self._send(200, runtime.voz_salvar(body))
                elif path == _PREFIX + "voz/restaurar":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    self._send(200, runtime.voz_restaurar())
                elif path == _PREFIX + "voz/testar":
                    if set(body) - {"texto"}:
                        self._send(400, {"error": "invalid_voz_test_payload"})
                        return
                    self._send(200, runtime.voz_testar(str(body.get("texto") or "")))
                elif path == _PREFIX + "microfone/testar":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    self._send(200, runtime.microfone_testar())
                elif path == _PREFIX + "fluxos":
                    self._send(200, runtime.fluxos_listar())
                elif path == _PREFIX + "lembretes":
                    self._send(200, runtime.lembretes_listar())
                elif path == _PREFIX + "lembretes/cancelar":
                    if not self._cancelar_payload_valido(body):
                        self._send(400, {"error": "invalid_lembrete_payload"})
                        return
                    self._send(200, runtime.lembrete_cancelar(body.get("numero"), body.get("trecho")))
                elif path == _PREFIX + "agenda/cancelar":
                    if not self._cancelar_payload_valido(body):
                        self._send(400, {"error": "invalid_agenda_payload"})
                        return
                    self._send(200, runtime.agenda_cancelar(body.get("numero"), body.get("trecho")))
                elif path == _PREFIX + "agenda":
                    permitido = {"texto", "quando", "repetir"}
                    if (not set(body) <= permitido
                            or not isinstance(body.get("texto"), str)
                            or not 1 <= len(body["texto"].strip()) <= 300
                            or not isinstance(body.get("quando"), str)
                            or not body["quando"].strip()
                            or ("repetir" in body and not isinstance(body["repetir"], str))):
                        self._send(400, {"error": "invalid_agenda_payload"})
                        return
                    try:
                        self._send(200, runtime.agenda_criar(
                            body["texto"].strip(), body["quando"].strip(), body.get("repetir") or ""))
                    except ValueError:
                        self._send(400, {"error": "invalid_agenda_payload"})
                elif path == _PREFIX + "fatos":
                    permitido = {"id", "texto", "trecho"}
                    if not set(body) <= permitido or not ({"id"} & set(body)):
                        self._send(400, {"error": "invalid_fato_payload"})
                        return
                    if "texto" in body:
                        self._send(200, runtime.fatos_corrigir(body["id"], str(body["texto"])[:300]))
                    else:
                        self._send(200, runtime.fatos_apagar(body.get("id")))
                elif path == _PREFIX + "personalidade":
                    permitido = {"perfil", "tom", "ton", "tamanho", "tratamento", "tratamentos",
                                 "extras", "jeito", "jeitos", "perfis", "usuario", "saudacao"}
                    if set(body) - permitido:
                        self._send(400, {"error": "invalid_personalidade_payload"})
                        return
                    if "usuario" in body and not isinstance(body["usuario"], dict):
                        self._send(400, {"error": "invalid_personalidade_payload"})
                        return
                    if "saudacao" in body and type(body["saudacao"]) is not bool:
                        self._send(400, {"error": "invalid_personalidade_payload"})
                        return
                    if "jeito" in body and not isinstance(body["jeito"], str):
                        self._send(400, {"error": "invalid_personalidade_payload"})
                        return
                    self._send(200, runtime.personalidade_salvar(body))
                elif path == _PREFIX + "personalidade/restaurar":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    self._send(200, runtime.personalidade_restaurar())
                elif path == _PREFIX + "skills/approve":
                    if set(body) != {"nome"} or not isinstance(body.get("nome"), str):
                        self._send(400, {"error": "invalid_skills_payload"})
                        return
                    try:
                        self._send(200, runtime.skills_aprovar(body["nome"]))
                    except ValueError as e:
                        self._send(409, {"error": "conflict", "detail": str(e)})
                elif path == _PREFIX + "skills/discard":
                    if set(body) != {"nome"} or not isinstance(body.get("nome"), str):
                        self._send(400, {"error": "invalid_skills_payload"})
                        return
                    self._send(200, runtime.skills_descartar(body["nome"]))
                elif path == _PREFIX + "update/apply":
                    if set(body) - {"restart_after"} or ("restart_after" in body and type(body["restart_after"]) is not bool):
                        self._send(400, {"error": "invalid_update_payload"})
                        return
                    self._send(202, runtime.update_and_restart())
                elif path == _PREFIX + "update/launch":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    if not runtime.launch_update():
                        self._send(409, {"error": "update_not_prepared"})
                        return
                    self._send(200, {"launched": True})
                elif path == _PREFIX + "update/rollback":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    if not runtime.rollback_update():
                        self._send(409, {"error": "no_backup_available"})
                        return
                    self._send(200, {"rolled_back": True})
                elif path == _PREFIX + "cofre":
                    import cofre
                    if set(body) != {"nome", "valor"}:
                        self._send(400, {"error": "invalid_cofre_payload"})
                        return
                    nome, valor = body["nome"], body["valor"]
                    if (not isinstance(nome, str) or not isinstance(valor, str)
                            or nome not in cofre.CREDENCIAIS or not 1 <= len(valor) <= 400):
                        self._send(400, {"error": "invalid_cofre_payload"})
                        return
                    self._send(200, runtime.cofre_guardar(nome, valor))
                elif path == _PREFIX + "cofre/remover":
                    import cofre
                    if set(body) != {"nome"} or body["nome"] not in cofre.CREDENCIAIS:
                        self._send(400, {"error": "invalid_cofre_payload"})
                        return
                    self._send(200, runtime.cofre_remover(body["nome"]))
                elif path == _PREFIX + "cofre/testar":
                    import cofre
                    if set(body) != {"nome"} or body["nome"] not in cofre.PROVEDORES:
                        self._send(400, {"error": "not_testable"})
                        return
                    self._send(200, runtime.cofre_testar(body["nome"]))
                elif path == _PREFIX + "conversation/clear":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    self._send(200, {"cleared": runtime.limpar_conversa()})
                elif path == _PREFIX + "bloco1":
                    if not isinstance(body, dict):
                        self._send(400, {"error": "invalid_bloco1_payload"})
                        return
                    self._send(200, runtime.atualizar_config_bloco1(body))
                elif path == _PREFIX + "bloco1/executar":
                    if not isinstance(body, dict) or not isinstance(body.get("acao"), str):
                        self._send(400, {"error": "invalid_bloco1_executar_payload"})
                        return
                    self._send(200, runtime.executar_acao_bloco1(body["acao"], body.get("params") or {}))
                elif path == _PREFIX + "bloco2":
                    if not isinstance(body, dict):
                        self._send(400, {"error": "invalid_bloco2_payload"})
                        return
                    self._send(200, runtime.atualizar_config_bloco2(body))
                elif path == _PREFIX + "bloco2/executar":
                    if not isinstance(body, dict) or not isinstance(body.get("acao"), str):
                        self._send(400, {"error": "invalid_bloco2_executar_payload"})
                        return
                    self._send(200, runtime.executar_acao_bloco2(body["acao"], body.get("params") or {}))
                elif path == _PREFIX + "mobile/pairing/rotate":
                    allowed = {"device_id", "killswitch_separado"}
                    if set(body) - allowed:
                        self._send(400, {"error": "invalid_mobile_pairing_payload"})
                        return
                    device_id = body.get("device_id")
                    if device_id is not None and not isinstance(device_id, str):
                        self._send(400, {"error": "invalid_mobile_pairing_payload"})
                        return
                    ks_sep = body.get("killswitch_separado", False)
                    if type(ks_sep) is not bool:
                        self._send(400, {"error": "invalid_mobile_pairing_payload"})
                        return
                    self._send(200, runtime.mobile_pairing_rotate(device_id=device_id, killswitch_separado=ks_sep))
                elif path == _PREFIX + "mobile/pairing/revoke":
                    if set(body) - {"device_id"}:
                        self._send(400, {"error": "invalid_mobile_pairing_payload"})
                        return
                    device_id = body.get("device_id")
                    if device_id is not None and not isinstance(device_id, str):
                        self._send(400, {"error": "invalid_mobile_pairing_payload"})
                        return
                    self._send(200, runtime.mobile_pairing_revoke(device_id=device_id))
                elif path == _PREFIX + "shutdown":
                    if body:
                        self._send(400, {"error": "empty_payload_required"})
                        return
                    runtime.request_shutdown()
                    self._send(202, {"shutdown_requested": True})
                else:
                    self._send(404, {"error": "not_found"})
            except ValueError:
                self._send(400, {"error": "invalid_request"})
            except RuntimeError:
                self._send(409, {"error": "operation_unavailable"})
            except Exception:
                self._send(500, {"error": "internal_error"})

        def _method_not_allowed(self):
            if not self._authorized():
                return
            self._send(405, {"error": "method_not_allowed"})

        do_PUT = _method_not_allowed
        do_DELETE = _method_not_allowed
        do_OPTIONS = _method_not_allowed

    try:
        server = _Server((host, port), Handler)
    except OSError:
        if port == 0:
            raise
        # Porta preferida ocupada: qualquer porta livre do loopback serve.
        server = _Server((host, 0), Handler)
    actual_host, actual_port = server.server_address[:2]
    return server, f"http://{actual_host}:{actual_port}"
