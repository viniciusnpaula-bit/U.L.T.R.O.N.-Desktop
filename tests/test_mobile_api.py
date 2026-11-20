import hashlib
import hmac
import json
import secrets
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cofre
import config
import desktop_api
import mobile_api
import mobile_pairing
import seguranca
import sessao
import skills
from mobile_commands import MobileCommandDispatcher


def verify_mobile_response_signature(
    raw_body: str,
    signature_header: str,
    shared_secret: str,
    timestamp: str = "",
    nonce: str = "",
) -> bool:
    """Espelho exato de DesktopPairingService.verifyResponseSignature() do Mobile."""
    if not shared_secret.strip() or not signature_header.strip():
        return False
    provided = signature_header.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[7:]
    provided = provided.lower()
    body_only = hmac.new(
        shared_secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256
    ).hexdigest().lower()
    if hmac.compare_digest(provided, body_only):
        return True
    if timestamp or nonce:
        envelope = hmac.new(
            shared_secret.encode("utf-8"),
            f"{timestamp}.{nonce}.{raw_body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().lower()
        if hmac.compare_digest(provided, envelope):
            return True
    return False


class FakeDesktopRuntime:
    def __init__(self, started: bool = True):
        self._started = started
        self.submitted = []
        self._mobile_api_running = False
        self._mobile_api_url = None

    def submit_command(self, text: str) -> str:
        self.submitted.append(text)
        return f"op-{len(self.submitted)}"

    def set_mobile_api_state(self, running: bool, url: str | None = None) -> None:
        self._mobile_api_running = running
        self._mobile_api_url = url

    def mobile_pairing_status(self) -> dict:
        data = mobile_pairing.status_publico()
        data["mobile_server_running"] = self._mobile_api_running
        data["mobile_server_url"] = self._mobile_api_url
        return data

    def mobile_pairing_rotate(self, device_id=None, killswitch_separado=False) -> dict:
        return mobile_pairing.criar_ou_rotacionar(
            device_id=device_id,
            killswitch_separado=killswitch_separado,
        )

    def mobile_pairing_revoke(self, device_id=None) -> dict:
        return mobile_pairing.revogar(device_id=device_id)


class MobileApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raiz = Path(self.temp.name)
        self.pairing_file = raiz / "mobile_pairing.json"
        self.key_file = raiz / ".cofre.chave"
        self.skills_base = raiz / "skills"
        self.skills_pend = self.skills_base / ".pendentes"
        self.skills_uso = self.skills_base / ".uso.json"

        patches = (
            patch.object(config, "ARQUIVO_MOBILE_PAIRING", self.pairing_file),
            patch.object(cofre, "ARQUIVO_CHAVE", self.key_file),
            patch.object(skills, "BASE", self.skills_base),
            patch.object(skills, "PENDENTES", self.skills_pend),
            patch.object(skills, "USO", self.skills_uso),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        skills.invalidar()
        self.addCleanup(skills.invalidar)
        self.addCleanup(lambda: setattr(seguranca, "SEGREDOS_MOBILE", ()))
        seguranca.parada.clear()
        sessao.bloquear()

        self.now_ts = 1_760_000_000.0
        self.launched = []
        self.media_keys = []
        self.clipboard = "texto inicial"
        self.lock_calls = 0
        self.runtime = FakeDesktopRuntime(started=True)

        def fake_launch(target):
            self.launched.append(target)

        def fake_media(key):
            self.media_keys.append(key)

        def fake_copy(text):
            self.clipboard = text

        def fake_paste():
            return self.clipboard

        def fake_lock():
            self.lock_calls += 1

        self.dispatcher = MobileCommandDispatcher(
            runtime=self.runtime,
            launch_app=fake_launch,
            send_media=fake_media,
            clipboard_copy=fake_copy,
            clipboard_paste=fake_paste,
            lock_workstation=fake_lock,
            get_version=lambda: "2.1.0-test",
        )
        self.server, self.url = mobile_api.create_mobile_server(
            runtime=self.runtime,
            host="127.0.0.1",
            port=0,
            now_fn=lambda: self.now_ts,
            dispatcher=self.dispatcher,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _pair(self, device_id="galaxy-a34", killswitch_separado=False):
        return mobile_pairing.criar_ou_rotacionar(
            device_id=device_id,
            killswitch_separado=killswitch_separado,
        )

    def _raw_post(self, path: str, raw_body: str, headers: dict):
        req = Request(
            f"{self.url}{path}",
            data=raw_body.encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status, resp.read().decode("utf-8"), dict(resp.headers.items())
        except HTTPError as err:
            return err.code, err.read().decode("utf-8"), dict(err.headers.items())

    def _send_command(
        self,
        *,
        device_id: str,
        secret: str,
        command: str,
        args: dict | None = None,
        ts_ms: int | None = None,
        nonce: str | None = None,
        header_device: str | None = None,
        override_sig: str | None = None,
    ):
        ts = str(int(self.now_ts * 1000) if ts_ms is None else ts_ms)
        nc = nonce or secrets.token_hex(16)
        raw_body = json.dumps(
            {
                "device_id": device_id,
                "command": command,
                "args": {} if args is None else args,
                "timestamp": ts,
                "nonce": nc,
            },
            separators=(",", ":"),
        )
        sig = override_sig or mobile_api.compute_command_signature(secret, ts, nc, raw_body)
        headers = {
            "X-Ultron-Device": header_device or device_id,
            "X-Ultron-Timestamp": ts,
            "X-Ultron-Nonce": nc,
            "X-Ultron-Signature": sig,
        }
        return self._raw_post("/api/mobile/command", raw_body, headers)

    def _send_killswitch(
        self,
        *,
        secret: str,
        ts_iso: str | None = None,
        command: str = "LOCK_WORKSTATION",
        source: str = "ULTRON_MOBILE",
        reason: str = "manual",
        override_sig: str | None = None,
    ):
        ts = ts_iso or datetime.fromtimestamp(self.now_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        raw_body = json.dumps(
            {
                "command": command,
                "source": source,
                "reason": reason,
                "timestamp": ts,
            },
            separators=(",", ":"),
        )
        sig = override_sig or ("sha256=" + mobile_api.compute_raw_signature(secret, raw_body))
        return self._raw_post(
            "/killswitch",
            raw_body,
            {
                "X-Ultron-Signature": sig,
                "X-Ultron-Timestamp": ts,
            },
        )

    @staticmethod
    def _header(headers: dict, name: str) -> str:
        target = name.lower()
        for k, v in headers.items():
            if k.lower() == target:
                return str(v)
        return ""

    def test_fail_closed_sem_pareamento_configurado(self):
        st_cmd, raw_cmd, _ = self._send_command(
            device_id="galaxy-a34",
            secret="a" * 32,
            command="PING",
        )
        self.assertEqual(st_cmd, 503)
        self.assertEqual(json.loads(raw_cmd)["error"], "pairing_not_configured")

        st_ks, raw_ks, _ = self._send_killswitch(secret="a" * 32)
        self.assertEqual(st_ks, 503)
        self.assertEqual(json.loads(raw_ks)["error"], "killswitch_not_configured")
        self.assertEqual(self.lock_calls, 0)

    def test_ping_e_status_assinatura_valida_e_verificacao_resposta(self):
        pair = self._pair("galaxy-a34")
        for cmd in ("ping", "PING", "STATUS"):
            status, raw, headers = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command=cmd,
            )
            self.assertEqual(status, 200)
            data = json.loads(raw)
            self.assertTrue(data["ok"])
            self.assertEqual(data["version"], "2.1.0-test")
            self.assertIn("cpu_percent", data)
            self.assertIn("ram_percent", data)
            self.assertIn("uptime_seconds", data)
            self.assertIn("session", data)
            self.assertTrue(
                verify_mobile_response_signature(
                    raw_body=raw,
                    signature_header=self._header(headers, "X-Ultron-Signature"),
                    shared_secret=pair["shared_secret"],
                    timestamp=self._header(headers, "X-Ultron-Timestamp"),
                    nonce=self._header(headers, "X-Ultron-Nonce"),
                )
            )

    def test_assinatura_invalida_e_dispositivo_incorreto(self):
        pair = self._pair("galaxy-a34")
        st_bad, raw_bad, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PING",
            override_sig="0" * 64,
        )
        self.assertEqual(st_bad, 401)
        self.assertEqual(json.loads(raw_bad)["error"], "invalid_signature")

        st_unpaired, raw_unpaired, _ = self._send_command(
            device_id="outro-celular",
            secret=pair["shared_secret"],
            command="PING",
        )
        self.assertEqual(st_unpaired, 401)
        self.assertEqual(json.loads(raw_unpaired)["error"], "unauthorized_device")

        st_mismatch, raw_mismatch, _ = self._send_command(
            device_id="outro-celular",
            header_device="galaxy-a34",
            secret=pair["shared_secret"],
            command="PING",
        )
        self.assertEqual(st_mismatch, 403)
        self.assertEqual(json.loads(raw_mismatch)["error"], "device_mismatch")

    def test_bloqueio_replay_de_nonce(self):
        pair = self._pair("galaxy-a34")
        nonce = secrets.token_hex(16)
        st1, _, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PING",
            nonce=nonce,
        )
        self.assertEqual(st1, 200)

        st2, raw2, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PING",
            nonce=nonce,
        )
        self.assertEqual(st2, 401)
        self.assertEqual(json.loads(raw2)["error"], "nonce_replay")

    def test_timestamp_expirado_passado_futuro_e_invalido(self):
        pair = self._pair("galaxy-a34")
        for delta_ms in (-65_000, 65_000):
            st, raw, _ = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command="PING",
                ts_ms=int(self.now_ts * 1000) + delta_ms,
            )
            self.assertEqual(st, 401)
            self.assertEqual(json.loads(raw)["error"], "timestamp_expired")

        nc = secrets.token_hex(16)
        raw_body = json.dumps({"device_id": "galaxy-a34", "command": "PING", "args": {}, "timestamp": "abc", "nonce": nc})
        st_nan, _, _ = self._raw_post(
            "/api/mobile/command",
            raw_body,
            {
                "X-Ultron-Device": "galaxy-a34",
                "X-Ultron-Timestamp": "abc",
                "X-Ultron-Nonce": nc,
                "X-Ultron-Signature": mobile_api.compute_command_signature(pair["shared_secret"], "abc", nc, raw_body),
            },
        )
        self.assertEqual(st_nan, 401)

    def test_comando_fora_da_allowlist_recusado(self):
        pair = self._pair("galaxy-a34")
        for cmd in ("EXEC_SHELL", "RUN_CMD", "DELETE_FILES"):
            st, raw, _ = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command=cmd,
                args={"cmd": "whoami"},
            )
            self.assertEqual(st, 403)
            self.assertEqual(json.loads(raw)["error"], "command_not_allowed")

    def test_pc_open_app_allowlist_e_bloqueio_injecao(self):
        pair = self._pair("galaxy-a34")
        st1, raw1, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PC_OPEN_APP",
            args={"app": "calculadora"},
        )
        self.assertEqual(st1, 200)
        self.assertEqual(json.loads(raw1)["launched"], True)
        self.assertEqual(self.launched, ["calc"])

        st2, _, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PC_OPEN_APP",
            args={"app": "chrome"},
        )
        self.assertEqual(st2, 200)
        self.assertEqual(self.launched[-1], "chrome")

        for proibido in ("powershell", "cmd.exe /c whoami", "notepad && calc", "evil.exe"):
            st_bad, raw_bad, _ = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command="PC_OPEN_APP",
                args={"app": proibido},
            )
            self.assertEqual(st_bad, 403)
            self.assertEqual(json.loads(raw_bad)["error"], "app_not_allowed")
        self.assertEqual(len(self.launched), 2)

    def test_pc_media_acoes_permitidas_e_invalidas(self):
        pair = self._pair("galaxy-a34")
        esperado = {
            "play_pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "stop": "stop",
            "mute": "volumemute",
        }
        for action, mapped in esperado.items():
            st, raw, _ = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command="PC_MEDIA",
                args={"action": action},
            )
            self.assertEqual(st, 200)
            self.assertTrue(json.loads(raw)["executed"])
            self.assertEqual(self.media_keys[-1], mapped)

        st_bad, raw_bad, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PC_MEDIA",
            args={"action": "format_c"},
        )
        self.assertEqual(st_bad, 400)
        self.assertEqual(json.loads(raw_bad)["error"], "invalid_media_action")

    def test_pc_clipboard_push_pull_sem_vazar_conteudo_no_log(self):
        pair = self._pair("galaxy-a34")
        segredo_texto = "segredo-super-confidencial-123"
        logs_registrados = []

        with patch.object(seguranca._log_seg, "info", side_effect=lambda m, *a: logs_registrados.append(str(m))):
            st_push, raw_push, _ = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command="PC_CLIPBOARD_PUSH",
                args={"text": segredo_texto},
            )
            self.assertEqual(st_push, 200)
            self.assertEqual(json.loads(raw_push)["length"], len(segredo_texto))
            self.assertEqual(self.clipboard, segredo_texto)

            st_pull, raw_pull, _ = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command="PC_CLIPBOARD_PULL",
                args={},
            )
            self.assertEqual(st_pull, 200)
            self.assertEqual(json.loads(raw_pull)["text"], segredo_texto)

        tudo_logado = "\n".join(logs_registrados)
        self.assertNotIn(segredo_texto, tudo_logado)
        self.assertIn(f"<{len(segredo_texto)} caracteres>", tudo_logado)

    def test_pc_run_skill_aprovada_pendente_traversal_e_inexistente(self):
        pair = self._pair("galaxy-a34")
        aprovada_dir = self.skills_base / "resumo-diario"
        aprovada_dir.mkdir(parents=True)
        (aprovada_dir / "SKILL.md").write_text(
            "---\nnome: Resumo Diario\ndescricao: Gera resumo\nquando: Quando pedir resumo\n---\n\n1. Ler agenda.\n",
            encoding="utf-8",
        )
        pend_dir = self.skills_pend / "nao-aprovada"
        pend_dir.mkdir(parents=True)
        (pend_dir / "SKILL.md").write_text(
            "---\nnome: Nao Aprovada\ndescricao: Teste\nquando: Nunca\n---\n\n1. Nada.\n",
            encoding="utf-8",
        )
        skills.invalidar()

        st_ok, raw_ok, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PC_RUN_SKILL",
            args={"skill": "resumo-diario"},
        )
        self.assertEqual(st_ok, 200)
        d_ok = json.loads(raw_ok)
        self.assertEqual(d_ok["status"], "queued")
        self.assertEqual(d_ok["operation_id"], "op-1")
        self.assertIn("resumo-diario", self.runtime.submitted[0])

        # Modo standalone (sem runtime rodando): retorna loaded sem erro
        self.runtime._started = False
        st_loaded, raw_loaded, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PC_RUN_SKILL",
            args={"skill": "Resumo Diario"},
        )
        self.assertEqual(st_loaded, 200)
        self.assertEqual(json.loads(raw_loaded)["status"], "loaded")

        st_pend, raw_pend, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PC_RUN_SKILL",
            args={"skill": "nao-aprovada"},
        )
        self.assertEqual(st_pend, 403)
        self.assertEqual(json.loads(raw_pend)["error"], "skill_pending_approval")

        for trav in ("../segredo", "..\\windows\\win.ini", "a/b"):
            st_trav, raw_trav, _ = self._send_command(
                device_id="galaxy-a34",
                secret=pair["shared_secret"],
                command="PC_RUN_SKILL",
                args={"skill": trav},
            )
            self.assertEqual(st_trav, 400)
            self.assertEqual(json.loads(raw_trav)["error"], "invalid_skill_name")

        st_missing, raw_missing, _ = self._send_command(
            device_id="galaxy-a34",
            secret=pair["shared_secret"],
            command="PC_RUN_SKILL",
            args={"skill": "nao-existe"},
        )
        self.assertEqual(st_missing, 404)
        self.assertEqual(json.loads(raw_missing)["error"], "skill_not_found")

    def test_killswitch_valido_invalido_legado_expirado_e_replay(self):
        pair = self._pair("galaxy-a34", killswitch_separado=True)
        logs = []

        # Legado hardcoded ULTRON_LAN_GUARD nunca funciona
        st_legacy, _, _ = self._send_killswitch(secret="ULTRON_LAN_GUARD")
        self.assertEqual(st_legacy, 401)
        self.assertEqual(self.lock_calls, 0)

        # Assinatura inválida não bloqueia
        st_bad, _, _ = self._send_killswitch(secret=pair["killswitch_secret"], override_sig="sha256=" + "f" * 64)
        self.assertEqual(st_bad, 401)
        self.assertEqual(self.lock_calls, 0)

        # Timestamp expirado não bloqueia
        exp_ts = datetime.fromtimestamp(self.now_ts - 120, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        st_exp, _, _ = self._send_killswitch(secret=pair["killswitch_secret"], ts_iso=exp_ts)
        self.assertEqual(st_exp, 401)
        self.assertEqual(self.lock_calls, 0)

        # Assinatura válida com segredo dedicado bloqueia, audita e assina resposta
        sessao.desbloquear("pin")
        self.assertTrue(sessao.estado()["desbloqueada"])
        valid_ts = datetime.fromtimestamp(self.now_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        with patch.object(seguranca._log_seg, "info", side_effect=lambda m, *a: logs.append(str(m))):
            st_ok, raw_ok, headers_ok = self._send_killswitch(
                secret=pair["killswitch_secret"],
                ts_iso=valid_ts,
                reason="emergencia",
            )
        self.assertEqual(st_ok, 200)
        self.assertEqual(self.lock_calls, 1)
        self.assertFalse(sessao.estado()["desbloqueada"])
        self.assertTrue(json.loads(raw_ok)["locked"])
        self.assertTrue(
            verify_mobile_response_signature(
                raw_body=raw_ok,
                signature_header=self._header(headers_ok, "X-Ultron-Signature"),
                shared_secret=pair["killswitch_secret"],
            )
        )
        self.assertTrue(any("action=killswitch" in l and "decision=ALLOW" in l for l in logs))

        # Replay exato do mesmo pacote killswitch deve falhar e não bloquear de novo
        st_replay, raw_replay, _ = self._send_killswitch(
            secret=pair["killswitch_secret"],
            ts_iso=valid_ts,
            reason="emergencia",
        )
        self.assertEqual(st_replay, 401)
        self.assertEqual(json.loads(raw_replay)["error"], "replay_detected")
        self.assertEqual(self.lock_calls, 1)

    def test_is_private_client_ip_rejeita_publico_e_metadata(self):
        for ok_ip in ("192.168.1.20", "10.0.0.5", "172.16.0.9", "127.0.0.1", "::1", "::ffff:192.168.1.5"):
            self.assertTrue(mobile_api.is_private_client_ip(ok_ip), ok_ip)
        for bad_ip in ("169.254.169.254", "fe80::1", "0.0.0.0", "8.8.8.8", "2001:4860:4860::8888", ""):
            self.assertFalse(mobile_api.is_private_client_ip(bad_ip), bad_ip)

    def test_rotas_pareamento_na_api_loopback_desktop(self):
        token = secrets.token_urlsafe(32)
        desk_srv, desk_url = desktop_api.create_server(self.runtime, token, port=0)
        desk_thread = threading.Thread(target=desk_srv.serve_forever, daemon=True)
        desk_thread.start()
        try:
            def call_desk(method: str, path: str, body=None):
                data = json.dumps(body).encode("utf-8") if body is not None else None
                headers = {"X-ULTRON-Token": token}
                if data is not None:
                    headers["Content-Type"] = "application/json"
                req = Request(f"{desk_url}{path}", data=data, headers=headers, method=method)
                with urlopen(req, timeout=3) as r:
                    return r.status, json.loads(r.read().decode("utf-8"))

            st, d_rot = call_desk("POST", "/api/v1/mobile/pairing/rotate", {"device_id": "galaxy-a34"})
            self.assertEqual(st, 200)
            self.assertEqual(d_rot["device_id"], "galaxy-a34")

            st, d_get = call_desk("GET", "/api/v1/mobile/pairing")
            self.assertEqual(st, 200)
            self.assertTrue(d_get["configured"])
            self.assertNotIn(d_rot["shared_secret"], json.dumps(d_get))

            st, d_rev = call_desk("POST", "/api/v1/mobile/pairing/revoke", {})
            self.assertEqual(st, 200)
            self.assertFalse(d_rev["configured"])
        finally:
            desk_srv.shutdown()
            desk_srv.server_close()
            desk_thread.join(timeout=2)

    def test_desktop_runtime_inicia_e_encerra_servidor_mobile_sob_demanda(self):
        from desktop_runtime import DesktopRuntime

        rt = DesktopRuntime(start_voice=False)
        with patch.object(config, "MOBILE_ENABLED", True), patch.object(config, "MOBILE_PORT", 0):
            rot = rt.mobile_pairing_rotate(device_id="galaxy-a34")
            self.assertTrue(rot["mobile_server_running"])
            self.assertTrue(rot["pairing_uri"].startswith("ultron://pair?"))
            self.assertTrue(rot["qr_data_uri"].startswith("data:image/svg+xml;base64,"))
            st = rt.mobile_pairing_status()
            self.assertTrue(st["mobile_server_running"])
            self.assertTrue(st["configured"])

            rev = rt.mobile_pairing_revoke()
            self.assertFalse(rev["configured"])
            self.assertFalse(rev["mobile_server_running"])
            rt.stop_mobile_server()
