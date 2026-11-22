"""Tests for Windows autostart helper and desktop API endpoint."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import desktop_api
import desktop_autostart


class _FakeRuntime:
    def __init__(self):
        self.calls: list[bool] = []
        self.installed = False

    def set_autostart(self, enabled: bool) -> dict:
        self.calls.append(enabled)
        self.installed = bool(enabled)
        return {"autostart_installed": self.installed}


class DesktopAutostartTests(unittest.TestCase):
    def test_install_check_and_remove_in_temp_appdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(desktop_autostart.is_installed(tmp))
            entry = desktop_autostart.install(tmp, Path(tmp) / "pythonw.exe", Path(tmp) / "desktop.py")
            self.assertTrue(entry.is_file())
            self.assertTrue(desktop_autostart.is_installed(tmp))
            content = entry.read_text(encoding="utf-16")
            self.assertIn("desktop.py", content)
            self.assertTrue(desktop_autostart.remove(tmp))
            self.assertFalse(desktop_autostart.is_installed(tmp))

    def test_api_autostart_post_valid_and_invalid_payloads(self):
        runtime = _FakeRuntime()
        token = "t" * 32
        server, base_url = desktop_api.create_server(runtime, token, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def post(payload):
                req = urllib.request.Request(
                    f"{base_url}/api/v1/autostart",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "X-ULTRON-Token": token,
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))

            status, data = post({"enabled": True})
            self.assertEqual(status, 200)
            self.assertEqual(data, {"autostart_installed": True})

            status, data = post({"enabled": False})
            self.assertEqual(status, 200)
            self.assertEqual(data, {"autostart_installed": False})
            self.assertEqual(runtime.calls, [True, False])

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                post({"enabled": "yes"})
            self.assertEqual(ctx.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()

    def test_runtime_set_autostart_uses_desktop_autostart(self):
        from desktop_runtime import DesktopRuntime

        rt = DesktopRuntime.__new__(DesktopRuntime)
        rt._log_seg = lambda *args, **kwargs: None

        with patch.object(desktop_autostart, "install") as mock_install, \
                patch.object(desktop_autostart, "remove") as mock_remove, \
                patch.object(desktop_autostart, "is_installed", side_effect=[True, False]):
            res_on = rt.set_autostart(True)
            res_off = rt.set_autostart(False)

        self.assertEqual(res_on, {"autostart_installed": True})
        self.assertEqual(res_off, {"autostart_installed": False})
        self.assertEqual(mock_install.call_count, 1)
        self.assertEqual(mock_remove.call_count, 1)


if __name__ == "__main__":
    unittest.main()
