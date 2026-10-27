import json
import secrets
import sys
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop_api import create_server


class FakeRuntime:
    def __init__(self):
        self.snapshot = {
            "core_running": True, "api_running": True, "microphone_paused": False,
            "autostart_installed": False, "shutdown_requested": False, "error": None,
        }
        self.events = [{"type": "notification", "message": "online"}]
        self.commands = []
        self.confirmations = []
        self.pause_requests = []
        self.shutdown_requested = False
        self.pause_result = True
        self.microphones = {"devices": [{"id": None, "name": "Padrão do sistema"},
                                         {"id": "input-1", "name": "Webcam Mic"}],
                            "selected_id": None, "selected_name": "Padrão do sistema",
                            "selected_available": True, "active_name": "Padrão do sistema"}
        self.selected_microphone = None
        self.palco_closed = False
        self.fatos = [{"id": 1, "texto": "gosta de café"}]
        self.fatos_apagados = []
        self.conversation_cleared = False
        self.personalidade = {
            "perfil": "ultron", "tratamento": "senhor", "jeito": "equilibrado",
            "usuario": {"nome": "", "apelido": "", "idade": "", "genero": "", "sobre": ""},
            "saudacao": True, "tratamentos": {"ultron": "senhor", "jarvis": "senhor"},
        }
        self.personalidade_salva = []

    def get_snapshot(self):
        return self.snapshot

    def conversation_turns(self):
        return [{"role": "user", "text": "oi", "source": "voz", "at": 1.0}]

    def limpar_conversa(self):
        self.conversation_cleared = True
        return 1

    def poll_events(self):
        events, self.events = self.events, []
        return events

    def submit_command(self, text):
        self.commands.append(text)
        return "operation-1"

    def set_microphone_paused(self, paused):
        self.pause_requests.append(paused)
        return self.pause_result

    def list_microphones(self):
        return self.microphones

    def select_microphone(self, device_id):
        if device_id is not None and device_id not in {device["id"] for device in self.microphones["devices"]}:
            raise LookupError("unavailable")
        self.selected_microphone = device_id
        return {"selected": device_id}

    def answer_confirmation(self, request_id, approved, pin=None):
        self.confirmations.append((request_id, approved, pin))
        return True

    def request_shutdown(self):
        self.shutdown_requested = True
        self.snapshot["shutdown_requested"] = True

    def fechar_palco(self):
        self.palco_closed = True
        return {"ok": True, "mensagem": "Palco fechado."}

    def fatos_listar(self):
        return {"fatos": list(self.fatos)}

    def fatos_corrigir(self, id, texto):
        self.fatos = [fato for fato in self.fatos if fato["id"] != id]
        self.fatos.append({"id": id, "texto": texto})
        return {"ok": True, "fato": {"id": id, "texto": texto}}

    def fatos_apagar(self, id):
        self.fatos = [fato for fato in self.fatos if fato["id"] != id]
        self.fatos_apagados.append(id)
        return {"ok": True, "apagado": id}

    def personalidade_info(self):
        return {
            "atual": dict(self.personalidade),
            "perfis": [{"id": "ultron", "rotulo": "U.L.T.R.O.N.", "tratamento": "senhor"}],
            "jeitos": [{"id": "equilibrado", "rotulo": "Equilibrado", "descricao": "O padrão.", "tom": "direto"}],
        }

    def personalidade_salvar(self, valores):
        self.personalidade_salva.append(dict(valores))
        self.personalidade.update(valores)
        return dict(self.personalidade)

    def personalidade_previa(self):
        return {"instrucao": "Personalidade de teste.", "atual": dict(self.personalidade)}

    def personalidade_restaurar(self):
        self.personalidade_salva.append({"restaurar": True})
        return dict(self.personalidade)


class DesktopApiTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.token = secrets.token_urlsafe(32)
        self.server, self.url = create_server(self.runtime, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def call(self, path, method="GET", data=None, raw=None, headers=None, use_token=True):
        payload = raw if raw is not None else (None if data is None else json.dumps(data).encode())
        request_headers = {} if headers is None else dict(headers)
        if use_token:
            request_headers.setdefault("X-ULTRON-Token", self.token)
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
        req = Request(self.url + path, data=payload, headers=request_headers, method=method)
        try:
            with urlopen(req, timeout=2) as response:
                return response.status, json.loads(response.read().decode())
        except HTTPError as error:
            body = error.read().decode()
            error.close()
            return error.code, json.loads(body)

    def test_health_status_and_events_require_token_and_return_expected_data(self):
        status, health = self.call("/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["version"], "1.18.0")
        status, snapshot = self.call("/api/v1/status")
        self.assertEqual(status, 200)
        self.assertFalse(snapshot["microphone_paused"])
        status, events = self.call("/api/v1/events")
        self.assertEqual(status, 200)
        self.assertEqual(events["events"], [{"type": "notification", "message": "online"}])

    def test_conversation_route_returns_voice_turns_only_with_token(self):
        status, _ = self.call("/api/v1/conversation", use_token=False)
        self.assertEqual(status, 401)
        status, data = self.call("/api/v1/conversation")
        self.assertEqual(status, 200)
        self.assertEqual(data["turns"][0]["role"], "user")
        self.assertEqual(data["turns"][0]["source"], "voz")

    def test_clear_conversation_route_requires_token_and_empty_body(self):
        status, _ = self.call("/api/v1/conversation/clear", method="POST", data={}, use_token=False)
        self.assertEqual(status, 401)
        self.assertFalse(self.runtime.conversation_cleared)
        status, _ = self.call("/api/v1/conversation/clear", method="POST", data={"all": True})
        self.assertEqual(status, 400)
        self.assertFalse(self.runtime.conversation_cleared)
        status, data = self.call("/api/v1/conversation/clear", method="POST", data={})
        self.assertEqual(status, 200)
        self.assertEqual(data, {"cleared": 1})
        self.assertTrue(self.runtime.conversation_cleared)

    def test_missing_or_wrong_token_is_rejected_without_work(self):
        status, _ = self.call("/api/v1/commands", method="POST", data={"text": "hello"}, use_token=False)
        self.assertEqual(status, 401)
        status, _ = self.call("/api/v1/commands", method="POST", data={"text": "hello"},
                              headers={"X-ULTRON-Token": "wrong"})
        self.assertEqual(status, 401)
        self.assertEqual(self.runtime.commands, [])

    def test_exact_host_validation_rejects_remote_or_mismatched_hosts(self):
        status, _ = self.call("/api/v1/health", headers={"Host": "example.com"})
        self.assertEqual(status, 403)
        status, _ = self.call("/api/v1/health", headers={"Origin": "https://example.com"})
        self.assertEqual(status, 403)

    def test_invalid_content_type_utf8_json_and_oversized_body_are_rejected(self):
        status, _ = self.call("/api/v1/commands", method="POST", raw=b"{}",
                              headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _ = self.call("/api/v1/commands", method="POST", raw=b"\xff")
        self.assertEqual(status, 400)
        status, _ = self.call("/api/v1/commands", method="POST", raw=b"{" )
        self.assertEqual(status, 400)
        status, _ = self.call("/api/v1/commands", method="POST", raw=b" " * 8193)
        self.assertEqual(status, 413)
        self.assertEqual(self.runtime.commands, [])

    def test_commands_enforce_text_limit_and_queue_valid_text(self):
        status, _ = self.call("/api/v1/commands", method="POST", data={"text": " "})
        self.assertEqual(status, 400)
        status, _ = self.call("/api/v1/commands", method="POST", data={"text": "x" * 4001})
        self.assertEqual(status, 400)
        status, result = self.call("/api/v1/commands", method="POST", data={"text": "hello"})
        self.assertEqual(status, 202)
        self.assertEqual(result["operation_id"], "operation-1")
        self.assertEqual(self.runtime.commands, ["hello"])

    def test_microphone_and_confirmation_payloads_are_validated(self):
        status, _ = self.call("/api/v1/microphone", method="POST", data={"paused": "yes"})
        self.assertEqual(status, 400)
        status, result = self.call("/api/v1/microphone", method="POST", data={"paused": True})
        self.assertEqual(status, 200)
        self.assertEqual(result["paused"], True)
        self.assertEqual(self.runtime.pause_requests, [True])
        status, _ = self.call("/api/v1/confirmations", method="POST",
                              data={"request_id": "r1", "approved": "yes", "pin": "2468"})
        self.assertEqual(status, 400)
        status, result = self.call("/api/v1/confirmations", method="POST",
                                   data={"request_id": "r1", "approved": True, "pin": "2468"})
        self.assertEqual(status, 200)
        self.assertNotIn("pin", result)
        self.assertEqual(self.runtime.confirmations, [("r1", True, "2468")])

    def test_microphone_devices_are_listed_and_selection_is_validated(self):
        status, result = self.call("/api/v1/microphones")
        self.assertEqual(status, 200)
        self.assertEqual(result, self.runtime.microphones)
        status, result = self.call("/api/v1/microphone/device", method="POST", data={"device_id": None})
        self.assertEqual(status, 200)
        self.assertIsNone(self.runtime.selected_microphone)
        status, result = self.call("/api/v1/microphone/device", method="POST", data={"device_id": "input-1"})
        self.assertEqual(status, 200)
        self.assertEqual(result["selected"], "input-1")
        self.assertEqual(self.runtime.selected_microphone, "input-1")
        status, _ = self.call("/api/v1/microphone/device", method="POST", data={"device_id": 3})
        self.assertEqual(status, 400)
        status, _ = self.call("/api/v1/microphone/device", method="POST", data={"device_id": "disconnected"})
        self.assertEqual(status, 409)

    def test_emergency_stop_and_ordered_shutdown_are_routed(self):
        calls = []
        security = type("Security", (), {"parar_tudo": staticmethod(lambda: calls.append("stop"))})
        with patch.dict(sys.modules, {"seguranca": security}):
            status, _ = self.call("/api/v1/emergency-stop", method="POST", data={})
        self.assertEqual(status, 200)
        self.assertEqual(calls, ["stop"])
        status, result = self.call("/api/v1/shutdown", method="POST", data={})
        self.assertEqual(status, 202)
        self.assertTrue(result["shutdown_requested"])
        self.assertTrue(self.runtime.shutdown_requested)

    def test_palco_close_requires_empty_payload_and_reaches_the_runtime(self):
        status, _ = self.call("/api/v1/palco/fechar", method="POST", data={"x": 1})
        self.assertEqual(status, 400)
        self.assertFalse(self.runtime.palco_closed)
        status, result = self.call("/api/v1/palco/fechar", method="POST", data={})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertTrue(self.runtime.palco_closed)

    def test_post_only_routes_are_not_reachable_by_get(self):
        for path in ("/api/v1/lembretes/cancelar", "/api/v1/cofre/remover",
                     "/api/v1/cofre/testar"):
            status, body = self.call(path)
            self.assertEqual(status, 404, path)
            self.assertEqual(body["error"], "not_found")

    def test_get_fatos_lists_and_post_corrects_or_deletes(self):
        status, data = self.call("/api/v1/fatos")
        self.assertEqual(status, 200)
        self.assertEqual(data["fatos"][0]["id"], 1)

        status, result = self.call("/api/v1/fatos", method="POST",
                                   data={"id": 1, "texto": "gosta de chá"})
        self.assertEqual(status, 200)
        self.assertEqual(result["fato"]["texto"], "gosta de chá")

        status, result = self.call("/api/v1/fatos", method="POST", data={"id": 1})
        self.assertEqual(status, 200)
        self.assertEqual(result["apagado"], 1)
        self.assertEqual(self.runtime.fatos_apagados, [1])

    def test_personalidade_info_and_previa_expose_the_new_panel(self):
        status, data = self.call("/api/v1/personalidade")
        self.assertEqual(status, 200)
        self.assertEqual(data["atual"]["jeito"], "equilibrado")
        self.assertEqual(data["jeitos"][0]["id"], "equilibrado")
        status, data = self.call("/api/v1/personalidade/previa")
        self.assertEqual(status, 200)
        self.assertIn("instrucao", data)

    def test_personalidade_accepts_jeito_usuario_and_saudacao(self):
        status, data = self.call("/api/v1/personalidade", method="POST", data={
            "perfil": "jarvis",
            "jeito": "mordomo",
            "usuario": {"nome": "Pedro", "idade": "32"},
            "saudacao": False,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["jeito"], "mordomo")
        self.assertFalse(data["saudacao"])
        self.assertEqual(self.runtime.personalidade_salva[-1]["usuario"]["nome"], "Pedro")

    def test_personalidade_rejects_unknown_keys_and_wrong_types(self):
        for corpo in (
            {"perfil": "ultron", "inventado": True},
            {"usuario": "não é objeto"},
            {"saudacao": 1},
            {"jeito": 3},
        ):
            status, erro = self.call("/api/v1/personalidade", method="POST", data=corpo)
            self.assertEqual(status, 400, corpo)
            self.assertEqual(erro["error"], "invalid_personalidade_payload")
        self.assertEqual(self.runtime.personalidade_salva, [])

    def test_personalidade_restaurar_requires_empty_payload(self):
        status, _ = self.call("/api/v1/personalidade/restaurar", method="POST", data={"x": 1})
        self.assertEqual(status, 400)
        status, _ = self.call("/api/v1/personalidade/restaurar", method="POST", data={})
        self.assertEqual(status, 200)
        self.assertEqual(self.runtime.personalidade_salva, [{"restaurar": True}])

    def test_unknown_route_and_internal_errors_are_safe(self):
        status, _ = self.call("/api/v1/unknown")
        self.assertEqual(status, 404)
        self.runtime.get_snapshot = lambda: (_ for _ in ()).throw(RuntimeError("secret traceback"))
        status, error = self.call("/api/v1/status")
        self.assertEqual(status, 500)
        self.assertNotIn("traceback", json.dumps(error).lower())
        self.assertNotIn("secret", json.dumps(error).lower())

    def test_server_rejects_non_loopback_bind_address(self):
        with self.assertRaises(ValueError):
            create_server(self.runtime, self.token, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
