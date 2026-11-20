import json
import secrets
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cofre
import config
import cerebro
import ferramentas
import mobile_api
import mobile_bridge
import mobile_pairing
import seguranca
import sessao
from mobile_bridge import MobileReverseBridge
from tests.test_mobile_api import FakeDesktopRuntime, verify_mobile_response_signature


class MobileReverseBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raiz = Path(self.temp.name)
        self.pairing_file = raiz / "mobile_pairing.json"
        self.key_file = raiz / ".cofre.chave"

        patches = (
            patch.object(config, "ARQUIVO_MOBILE_PAIRING", self.pairing_file),
            patch.object(cofre, "ARQUIVO_CHAVE", self.key_file),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: setattr(seguranca, "SEGREDOS_MOBILE", ()))
        seguranca.parada.clear()
        sessao.bloquear()

        self.now_ts = 1_760_000_000.0
        self.bridge = MobileReverseBridge()
        old_bridge = mobile_bridge.get_bridge()
        mobile_bridge.set_bridge(self.bridge)
        self.addCleanup(lambda: mobile_bridge.set_bridge(old_bridge))

        self.runtime = FakeDesktopRuntime(started=True)
        self.server, self.url = mobile_api.create_mobile_server(
            runtime=self.runtime,
            host="127.0.0.1",
            port=0,
            now_fn=lambda: self.now_ts,
            bridge=self.bridge,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _pair(self, device_id="galaxy-a34"):
        return mobile_pairing.criar_ou_rotacionar(device_id=device_id)

    def _signed_get(self, path: str, device_id: str, secret: str, *, nonce: str | None = None, ts_ms: int | None = None):
        ts = str(int(self.now_ts * 1000) if ts_ms is None else ts_ms)
        nc = nonce or secrets.token_hex(16)
        sig = mobile_api.compute_command_signature(secret, ts, nc, "")
        req = Request(
            f"{self.url}{path}",
            headers={
                "X-Ultron-Device": device_id,
                "X-Ultron-Timestamp": ts,
                "X-Ultron-Nonce": nc,
                "X-Ultron-Signature": sig,
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8")
        except HTTPError as err:
            return err.code, dict(err.headers), err.read().decode("utf-8")

    def _signed_result(
        self,
        device_id: str,
        secret: str,
        payload_override: dict | None = None,
        *,
        nonce: str | None = None,
        ts_ms: int | None = None,
        sig_override: str | None = None,
    ):
        ts = str(int(self.now_ts * 1000) if ts_ms is None else ts_ms)
        nc = nonce or secrets.token_hex(16)
        body = {
            "device_id": device_id,
            "command_id": "cmd-123",
            "command": "OPEN_APP",
            "ok": True,
            "status": "executed",
            "message": "App aberto no celular: WhatsApp",
            "data": {"app": "whatsapp"},
            "timestamp": ts,
            "nonce": nc,
        }
        if payload_override:
            body.update(payload_override)
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        sig = sig_override or mobile_api.compute_command_signature(secret, ts, nc, raw)
        req = Request(
            f"{self.url}/api/mobile/result",
            data=raw.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Ultron-Device": device_id,
                "X-Ultron-Timestamp": ts,
                "X-Ultron-Nonce": nc,
                "X-Ultron-Signature": sig,
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8")
        except HTTPError as err:
            return err.code, dict(err.headers), err.read().decode("utf-8")

    def test_poll_returns_204_when_empty(self):
        pair = self._pair("pixel-9")
        st, _hdrs, raw = self._signed_get("/api/mobile/poll?wait_s=1", "pixel-9", pair["shared_secret"])
        self.assertEqual(st, 204)
        self.assertEqual(raw, "")

    def test_poll_and_result_round_trip_open_app(self):
        pair = self._pair("pixel-9")
        dev = "pixel-9"
        sec = pair["shared_secret"]
        outcome = {}

        def _dispatch():
            try:
                outcome["res"] = self.bridge.enqueue_and_wait("OPEN_APP", {"app": "whatsapp"}, timeout_s=5.0)
            except Exception as exc:
                outcome["err"] = exc

        t = threading.Thread(target=_dispatch, daemon=True)
        t.start()

        st_poll, hdr_poll, raw_poll = self._signed_get("/api/mobile/poll?wait_s=5", dev, sec)
        self.assertEqual(st_poll, 200)
        body_poll = json.loads(raw_poll)
        self.assertEqual(body_poll["device_id"], dev)
        self.assertEqual(body_poll["command"], "OPEN_APP")
        self.assertEqual(body_poll["args"], {"app": "whatsapp"})
        self.assertTrue(body_poll["command_id"])

        hdr_ts = hdr_poll.get("X-Ultron-Timestamp", "")
        hdr_nc = hdr_poll.get("X-Ultron-Nonce", "")
        hdr_sig = hdr_poll.get("X-Ultron-Signature", "")
        self.assertEqual(body_poll["timestamp"], hdr_ts)
        self.assertEqual(body_poll["nonce"], hdr_nc)
        self.assertTrue(hdr_sig.startswith("sha256="))
        self.assertTrue(verify_mobile_response_signature(raw_poll, hdr_sig, sec, hdr_ts, hdr_nc))

        st_res, hdr_res, raw_res = self._signed_result(
            dev,
            sec,
            {
                "command_id": body_poll["command_id"],
                "command": "OPEN_APP",
                "ok": True,
                "status": "executed",
                "message": "App aberto no celular: WhatsApp",
                "data": {"package": "com.whatsapp"},
            },
        )
        self.assertEqual(st_res, 200)
        self.assertTrue(json.loads(raw_res)["accepted"])
        self.assertTrue(
            verify_mobile_response_signature(
                raw_res,
                hdr_res.get("X-Ultron-Signature", ""),
                sec,
                hdr_res.get("X-Ultron-Timestamp", ""),
                hdr_res.get("X-Ultron-Nonce", ""),
            )
        )

        t.join(timeout=3)
        self.assertNotIn("err", outcome)
        self.assertTrue(outcome["res"]["ok"])
        self.assertEqual(outcome["res"]["message"], "App aberto no celular: WhatsApp")
        self.assertEqual(outcome["res"]["data"]["package"], "com.whatsapp")

    def test_poll_auth_rejections_and_replay(self):
        pair = self._pair("pixel-9")
        dev = "pixel-9"
        sec = pair["shared_secret"]

        # Bad signature
        req_bad = Request(
            f"{self.url}/api/mobile/poll?wait_s=1",
            headers={
                "X-Ultron-Device": dev,
                "X-Ultron-Timestamp": str(int(self.now_ts * 1000)),
                "X-Ultron-Nonce": "a" * 32,
                "X-Ultron-Signature": "0" * 64,
            },
            method="GET",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req_bad, timeout=5)
        self.assertEqual(ctx.exception.code, 401)

        # Expired timestamp (>60s)
        st_exp, _, _ = self._signed_get("/api/mobile/poll?wait_s=1", dev, sec, ts_ms=int((self.now_ts - 120) * 1000))
        self.assertEqual(st_exp, 401)

        # Replay of nonce
        reused = "b" * 32
        st1, _, _ = self._signed_get("/api/mobile/poll?wait_s=1", dev, sec, nonce=reused)
        self.assertEqual(st1, 204)
        st2, _, raw2 = self._signed_get("/api/mobile/poll?wait_s=1", dev, sec, nonce=reused)
        self.assertEqual(st2, 401)
        self.assertEqual(json.loads(raw2)["error"], "nonce_replay")

        # Invalid wait_s
        st_bad_wait, _, raw_bad_wait = self._signed_get("/api/mobile/poll?wait_s=abc", dev, sec)
        self.assertEqual(st_bad_wait, 400)
        self.assertEqual(json.loads(raw_bad_wait)["error"], "invalid_wait_s")

    def test_result_rejections_replay_device_mismatch_unknown_command(self):
        pair1 = self._pair("dev-1")
        pair2 = self._pair("dev-2")

        # Expired ts
        st_exp, _, _ = self._signed_result(
            "dev-1", pair1["shared_secret"], ts_ms=int((self.now_ts - 200) * 1000)
        )
        self.assertEqual(st_exp, 401)

        # Invalid signature
        st_sig, _, _ = self._signed_result("dev-1", pair1["shared_secret"], sig_override="f" * 64)
        self.assertEqual(st_sig, 401)

        # Unknown command_id
        fixed_nonce = "c" * 32
        st_unk, _, raw_unk = self._signed_result("dev-1", pair1["shared_secret"], nonce=fixed_nonce)
        self.assertEqual(st_unk, 404)
        self.assertEqual(json.loads(raw_unk)["error"], "unknown_or_expired_command")

        # Replay of same nonce
        st_rep, _, raw_rep = self._signed_result("dev-1", pair1["shared_secret"], nonce=fixed_nonce)
        self.assertEqual(st_rep, 401)
        self.assertEqual(json.loads(raw_rep)["error"], "nonce_replay")

        # Device mismatch: command queued for dev-1, result posted by dev-2
        pending_out = {}
        t = threading.Thread(
            target=lambda: pending_out.setdefault(
                "res", self.bridge.enqueue_and_wait("TORCH_ON", {}, device_id="dev-1", timeout_s=3.0)
            ),
            daemon=True,
        )
        t.start()
        st_p, _, raw_p = self._signed_get("/api/mobile/poll?wait_s=2", "dev-1", pair1["shared_secret"])
        self.assertEqual(st_p, 200)
        cmd_id = json.loads(raw_p)["command_id"]

        st_mm, _, raw_mm = self._signed_result(
            "dev-2",
            pair2["shared_secret"],
            {"command_id": cmd_id, "command": "TORCH_ON"},
        )
        self.assertEqual(st_mm, 403)
        self.assertEqual(json.loads(raw_mm)["error"], "device_mismatch")

        # Now dev-1 completes it cleanly
        st_ok, _, _ = self._signed_result(
            "dev-1",
            pair1["shared_secret"],
            {"command_id": cmd_id, "command": "TORCH_ON", "message": "Lanterna ligada"},
        )
        self.assertEqual(st_ok, 200)
        t.join(timeout=2)
        self.assertTrue(pending_out["res"]["ok"])

    def test_shutdown_wakes_active_long_poll_immediately(self):
        pair = self._pair("pixel-9")
        poll_res = {}

        def _run_poll():
            poll_res["out"] = self._signed_get("/api/mobile/poll?wait_s=25", "pixel-9", pair["shared_secret"])

        t = threading.Thread(target=_run_poll, daemon=True)
        t.start()
        time.sleep(0.15)
        t0 = time.monotonic()
        self.server.shutdown()
        elapsed = time.monotonic() - t0
        t.join(timeout=2)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(poll_res["out"][0], 204)

    def test_ferramentas_mobile_unpaired_and_timeout_and_success(self):
        # 1. Unpaired returns clear error without crashing or hallucinating
        res_unpaired = ferramentas.executar("celular_status", {}, lambda _p: True, origem="desktop")
        self.assertIn("pareado", res_unpaired.lower())

        # 2. Paired but offline / poll not active -> fast timeout (override wait constant for test speed)
        pair = self._pair("pixel-9")
        with patch.object(mobile_bridge, "DEFAULT_RESULT_TIMEOUT_S", 0.25):
            res_timeout = ferramentas.executar(
                "celular_controlar",
                {"acao": "lanterna_ligar"},
                lambda _p: True,
                origem="desktop",
            )
        self.assertIn("não respondeu", res_timeout.lower())

        # 3. Full tool round-trip with background mobile poller
        dev = "pixel-9"
        sec = pair["shared_secret"]
        stop_ev = threading.Event()
        seen_cmds = []

        def _mobile_worker():
            while not stop_ev.is_set():
                st, _, raw = self._signed_get("/api/mobile/poll?wait_s=1", dev, sec)
                if st == 200:
                    cmd_obj = json.loads(raw)
                    seen_cmds.append(cmd_obj)
                    self._signed_result(
                        dev,
                        sec,
                        {
                            "command_id": cmd_obj["command_id"],
                            "command": cmd_obj["command"],
                            "ok": True,
                            "status": "executed",
                            "message": f"Executado: {cmd_obj['command']}",
                            "data": {"battery": 88, "network": "Wi-Fi"}
                            if cmd_obj["command"] == "DEVICE_STATUS"
                            else {"events": [{"title": "Reunião", "start": "10:00"}]},
                        },
                    )
                    return

        w1 = threading.Thread(target=_mobile_worker, daemon=True)
        w1.start()
        out_status = ferramentas.executar("celular_status", {}, lambda _p: True, origem="desktop")
        w1.join(timeout=3)
        stop_ev.set()
        self.assertIn("88", out_status)
        self.assertEqual(seen_cmds[-1]["command"], "DEVICE_STATUS")

        stop_ev.clear()
        w2 = threading.Thread(target=_mobile_worker, daemon=True)
        w2.start()
        out_agenda = ferramentas.executar(
            "celular_consultar",
            {"consulta": "agenda", "dias": 5},
            lambda _p: True,
            origem="desktop",
        )
        w2.join(timeout=3)
        stop_ev.set()
        self.assertIn("Reunião", out_agenda)
        self.assertEqual(seen_cmds[-1]["command"], "READ_CALENDAR")
        self.assertEqual(seen_cmds[-1]["args"], {"days": 5})

    def test_sensitive_mobile_actions_always_confirm_even_when_unlocked(self):
        pair = self._pair("pixel-9")
        dev = "pixel-9"
        sec = pair["shared_secret"]

        # Simulate unlocked desktop session: sensitive mobile actions must STILL ask confirmation
        sessao.desbloquear("pin")
        self.addCleanup(sessao.bloquear)

        confirm_prompts = []

        def deny_confirm(msg, pedido):
            confirm_prompts.append(pedido)
            return False

        denied_out = ferramentas.executar(
            "celular_acao_sensivel",
            {"acao": "whatsapp", "destino": "Maria", "conteudo": "Oi!"},
            deny_confirm,
            origem="desktop",
        )
        self.assertEqual(len(confirm_prompts), 1)
        self.assertEqual(confirm_prompts[0]["risco"], seguranca.CRITICO)
        self.assertIn("cancelada", denied_out.lower())
        # Verify nothing was queued onto the bridge
        st_empty, _, _ = self._signed_get("/api/mobile/poll?wait_s=1", dev, sec)
        self.assertEqual(st_empty, 204)

        # Now approve confirmation -> reaches mobile worker cleanly
        def _approve(msg, pedido):
            confirm_prompts.append(pedido)
            return True

        def _worker():
            st, _, raw = self._signed_get("/api/mobile/poll?wait_s=3", dev, sec)
            if st == 200:
                c = json.loads(raw)
                self._signed_result(
                    dev,
                    sec,
                    {
                        "command_id": c["command_id"],
                        "command": c["command"],
                        "ok": True,
                        "status": "executed",
                        "message": "Mensagem WhatsApp enviada pelo celular",
                        "data": {},
                    },
                )

        wt = threading.Thread(target=_worker, daemon=True)
        wt.start()
        with patch.object(mobile_bridge, "SENSITIVE_RESULT_TIMEOUT_S", 5.0):
            ok_out = ferramentas.executar(
                "celular_acao_sensivel",
                {"acao": "whatsapp", "destino": "Maria", "conteudo": "Oi!"},
                _approve,
                origem="desktop",
            )
        wt.join(timeout=3)
        self.assertIn("WhatsApp", ok_out)

    def test_pc_open_app_resolves_installed_apps_and_blocks_unsafe_targets(self):
        from mobile_commands import CommandError, MobileCommandDispatcher

        launched_targets = []

        def fake_resolve(nome):
            n = seguranca.normalizar(nome).strip()
            if n == "rocket league":
                return ("Rocket League", "uri", "com.epicgames.launcher://apps/Sugar"), 1.0
            if n == "bad shell":
                return ("Windows PowerShell", "arquivo", r"C:\Windows\System32\powershell.exe"), 1.0
            return None, 0.0

        dispatcher = MobileCommandDispatcher(
            runtime=self.runtime,
            launch_app=launched_targets.append,
            resolve_installed_app=fake_resolve,
            get_version=lambda: "2.1.0-test",
        )

        # Enabled via allowlist.aceitar_apps_instalados=True
        with patch.object(seguranca, "allowlist", side_effect=lambda k, d=None: {"aceitar_apps_instalados": True, "programas": {}, "mobile_programas": {}}.get(k, d)):
            res = dispatcher.dispatch("pixel-9", "PC_OPEN_APP", {"app": "rocket league"})
            self.assertTrue(res["ok"])
            self.assertTrue(res["launched"])
            self.assertEqual(res["app"], "Rocket League")
            self.assertEqual(launched_targets[-1], "com.epicgames.launcher://apps/Sugar")

            with self.assertRaises(CommandError) as ctx_blocked:
                dispatcher.dispatch("pixel-9", "PC_OPEN_APP", {"app": "bad shell"})
            self.assertEqual(ctx_blocked.exception.status_code, 403)
            self.assertEqual(ctx_blocked.exception.error_code, "app_not_allowed")

        # Disabled when aceitar_apps_instalados=False
        with patch.object(seguranca, "allowlist", side_effect=lambda k, d=None: {"aceitar_apps_instalados": False, "programas": {}, "mobile_programas": {}}.get(k, d)):
            with self.assertRaises(CommandError) as ctx_off:
                dispatcher.dispatch("pixel-9", "PC_OPEN_APP", {"app": "rocket league"})
            self.assertEqual(ctx_off.exception.status_code, 403)
            self.assertEqual(ctx_off.exception.error_code, "app_not_allowed")

    def test_system_prompt_mentions_mobile_tools(self):
        prompt = cerebro._system()
        self.assertIn("celular_status", prompt)
        self.assertIn("celular_controlar", prompt)
        self.assertIn("celular_acao_sensivel", prompt)

    def test_fast_path_mobile_commands_never_refuse_and_distinguish_not_polling(self):
        pair = self._pair("pixel-9")
        dev = "pixel-9"
        sec = pair["shared_secret"]

        # Without any /api/mobile/poll from phone, diagnostic tells clearly phone never polled
        with patch.object(mobile_bridge, "DEFAULT_RESULT_TIMEOUT_S", 0.15):
            r1 = cerebro.processar("abra o whatsapp no meu celular", lambda _m, _p: True, origem="desktop")
            r2 = cerebro.processar("abra o whatsapp no meu celular", lambda _m, _p: True, origem="desktop")
        self.assertIn("/api/mobile/poll", r1)
        self.assertIn("/api/mobile/poll", r2)
        self.assertNotIn("limitada ao seu computador", r2.lower())

        # Also accepts float wait_s=1.0 on /api/mobile/poll and executes volume down cleanly
        def _worker():
            st, _, raw = self._signed_get("/api/mobile/poll?wait_s=2.0", dev, sec)
            if st == 200:
                c = json.loads(raw)
                self._signed_result(
                    dev,
                    sec,
                    {
                        "command_id": c["command_id"],
                        "command": c["command"],
                        "ok": True,
                        "status": "executed",
                        "message": "Volume do celular diminuído.",
                        "data": {"percent": 40},
                    },
                )

        wt = threading.Thread(target=_worker, daemon=True)
        wt.start()
        r_vol = cerebro.processar("abaixe o volume do meu celular", lambda _m, _p: True, origem="desktop")
        wt.join(timeout=3)
        self.assertIn("Volume do celular diminuído", r_vol)


if __name__ == "__main__":
    unittest.main()
