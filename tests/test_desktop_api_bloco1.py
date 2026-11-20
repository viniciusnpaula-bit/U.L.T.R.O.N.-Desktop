import json
import secrets
import threading
import unittest
from urllib.request import Request, urlopen
from unittest.mock import patch, MagicMock

import desktop_api
from desktop_api import create_server


class FakeRuntime:
    def __init__(self):
        self.snapshot = {
            "core_running": True, "api_running": True, "microphone_paused": False,
            "autostart_installed": False, "shutdown_requested": False, "error": None,
            "admin_elevated": True, "admin_mode": True,
        }
        self.events = []
        self.bloco1_config = {"downloads_pdf_ativo": True, "disco_limite_pct": 80}
        self.bloco1_status = {"ativo": True}

    def get_snapshot(self):
        return self.snapshot

    def unlock_info(self):
        return {"session": {"desbloqueada": True}, "admin_elevated": True, "admin_mode": True}

    def obter_estado_bloco1(self):
        return {
            "config": self.bloco1_config,
            "status_monitores": self.bloco1_status,
            "admin_elevated": True,
            "admin_mode": True
        }

    def atualizar_config_bloco1(self, dados):
        self.bloco1_config.update(dados)
        return {"sucesso": True, "config": self.bloco1_config}

    def executar_acao_bloco1(self, acao, params):
        return {"sucesso": True, "acao": acao, "resultado": "ok"}


class TestDesktopApiBloco1(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.token = secrets.token_hex(16)
        self.server, self.origin_url = create_server(self.runtime, self.token, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"{self.origin_url}/api/v1/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

    def _request(self, method, path, data=None):
        url = self.base_url + path
        headers = {
            "X-ULTRON-Token": self.token,
            "Host": f"127.0.0.1:{self.port}"
        }
        body = json.dumps(data).encode("utf-8") if data is not None else None
        if body:
            headers["Content-Type"] = "application/json"
        req = Request(url, data=body, headers=headers, method=method)
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_status_contem_admin_elevated_e_mode(self):
        status, data = self._request("GET", "status")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("admin_elevated"))
        self.assertTrue(data.get("admin_mode"))

    def test_get_bloco1(self):
        status, data = self._request("GET", "bloco1")
        self.assertEqual(status, 200)
        self.assertIn("config", data)
        self.assertIn("status_monitores", data)

    def test_post_bloco1_atualiza_config(self):
        status, data = self._request("POST", "bloco1", {"downloads_pdf_ativo": False})
        self.assertEqual(status, 200)
        self.assertFalse(data["config"]["downloads_pdf_ativo"])

    def test_post_bloco1_executar(self):
        status, data = self._request("POST", "bloco1/executar", {"acao": "organizar_pdf", "params": {}})
        self.assertEqual(status, 200)
        self.assertTrue(data.get("sucesso"))
