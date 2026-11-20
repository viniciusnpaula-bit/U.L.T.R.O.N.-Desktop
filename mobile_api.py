"""Servidor HTTP LAN autenticado por HMAC-SHA256 para integração com U.L.T.R.O.N. Mobile."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import config
import desktop_api
import mobile_bridge
import mobile_pairing
import seguranca
from mobile_bridge import MobileReverseBridge
from mobile_commands import CommandError, MobileCommandDispatcher

_MAX_BODY = 64 * 1024
NONCE_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_KS_SIG_RE = re.compile(r"^sha256=([0-9a-fA-F]{64})$", re.IGNORECASE)


def compute_command_signature(shared_secret: str, timestamp: str, nonce: str, raw_body: str) -> str:
    """HMAC-SHA256 hex lowercase sobre f'{timestamp}.{nonce}.{raw_body}'."""
    mensagem = f"{timestamp}.{nonce}.{raw_body}".encode("utf-8")
    return hmac.new(shared_secret.encode("utf-8"), mensagem, hashlib.sha256).hexdigest().lower()


def compute_raw_signature(secret: str, raw_body: str) -> str:
    """HMAC-SHA256 hex lowercase sobre o raw_body UTF-8."""
    return hmac.new(secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest().lower()


def sign_response(
    shared_secret: str,
    raw_body: str,
    now_fn=None,
    *,
    resp_ts: str | None = None,
    resp_nonce: str | None = None,
) -> dict[str, str]:
    """Gera cabeçalhos HMAC de resposta compatíveis com DesktopPairingService.verifyResponseSignature."""
    if resp_ts is None:
        agora = now_fn() if now_fn is not None else time.time()
        resp_ts = str(int(agora * 1000))
    if resp_nonce is None:
        resp_nonce = secrets.token_hex(16)
    sig = compute_command_signature(shared_secret, resp_ts, resp_nonce, raw_body)
    return {
        "X-Ultron-Signature": f"sha256={sig}",
        "X-Ultron-Timestamp": resp_ts,
        "X-Ultron-Nonce": resp_nonce,
    }


def is_private_client_ip(addr: str) -> bool:
    """Aceita apenas IPs privados RFC1918/ULA ou loopback; rejeita públicos, 0.0.0.0 e link-local."""
    limpo = str(addr or "").strip()
    if limpo.startswith("[") and limpo.endswith("]"):
        limpo = limpo[1:-1]
    if "%" in limpo:
        limpo = limpo.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(limpo)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return False
    return bool(ip.is_private or ip.is_loopback)


def _parse_iso8601_utc(texto: str) -> float | None:
    if not isinstance(texto, str):
        return None
    limpo = texto.strip()
    if not limpo or len(limpo) > 64:
        return None
    if limpo.endswith("Z") or limpo.endswith("z"):
        limpo = limpo[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(limpo)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


class NonceStore:
    """Cache em memória com TTL e teto de capacidade para bloqueio anti-replay."""

    def __init__(self, ttl_s: float = 120.0, max_entries: int = 10000):
        self._ttl_s = max(1.0, float(ttl_s))
        self._max_entries = max(100, int(max_entries))
        self._entries: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_mark(self, key: str, now: float | None = None) -> bool:
        """Retorna True se o nonce for inédito e válido; False em caso de replay."""
        agora = float(time.time() if now is None else now)
        with self._lock:
            expiradas = [k for k, exp in self._entries.items() if exp <= agora]
            for k in expiradas:
                self._entries.pop(k, None)
            if key in self._entries:
                return False
            if len(self._entries) >= self._max_entries:
                excesso = len(self._entries) - self._max_entries + 1
                mais_antigos = sorted(self._entries.items(), key=lambda item: item[1])[:excesso]
                for k, _ in mais_antigos:
                    self._entries.pop(k, None)
            self._entries[key] = agora + self._ttl_s
            return True


class _MobileServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    mobile_bridge: MobileReverseBridge | None = None

    def shutdown(self):
        bridge = getattr(self, "mobile_bridge", None)
        if bridge is not None:
            bridge.close()
        super().shutdown()


def create_mobile_server(
    runtime=None,
    host: str | None = None,
    port: int | None = None,
    *,
    clock_skew_s: int | None = None,
    allow_non_private: bool | None = None,
    now_fn=None,
    dispatcher: MobileCommandDispatcher | None = None,
    pairing_module=None,
    bridge: MobileReverseBridge | None = None,
):
    """Cria o servidor HTTP LAN autenticado para o U.L.T.R.O.N. Mobile."""
    bind_host = str(config.MOBILE_HOST if host is None else host).strip() or "0.0.0.0"
    bind_port = int(config.MOBILE_PORT if port is None else port)
    skew_s = int(config.MOBILE_CLOCK_SKEW_S if clock_skew_s is None else clock_skew_s)
    permitir_externo = bool(
        config.MOBILE_ALLOW_NON_PRIVATE if allow_non_private is None else allow_non_private
    )
    relogio = now_fn or time.time
    pairing = pairing_module or mobile_pairing
    active_dispatcher = dispatcher or MobileCommandDispatcher(runtime=runtime)
    active_bridge = bridge if bridge is not None else mobile_bridge.get_bridge()
    active_bridge.reopen()
    nonce_store = NonceStore(ttl_s=max(120, skew_s * 2))

    class Handler(BaseHTTPRequestHandler):
        server_version = f"ULTRONMobileBridge/{desktop_api._obter_versao()}"
        sys_version = ""

        def log_message(self, _format, *_args):
            return

        def _drenar_corpo(self, limite: int = 64 * 1024, espera: float = 0.2):
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

        def _send(
            self,
            status: int,
            data: dict,
            *,
            sign_secret: str | None = None,
            killswitch_mode: bool = False,
            resp_ts: str | None = None,
            resp_nonce: str | None = None,
        ):
            self._drenar_corpo()
            raw_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            payload = raw_str.encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                if sign_secret:
                    if killswitch_mode:
                        sig = compute_raw_signature(sign_secret, raw_str)
                        self.send_header("X-Ultron-Signature", f"sha256={sig}")
                        self.send_header(
                            "X-Ultron-Timestamp",
                            datetime.fromtimestamp(relogio(), tz=timezone.utc).isoformat(),
                        )
                    else:
                        headers_sig = sign_response(
                            sign_secret,
                            raw_str,
                            now_fn=relogio,
                            resp_ts=resp_ts,
                            resp_nonce=resp_nonce,
                        )
                        for header_k, header_v in headers_sig.items():
                            self.send_header(header_k, header_v)
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        def _send_no_content(self):
            self._drenar_corpo()
            try:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        def _check_client_ip(self) -> bool:
            if permitir_externo:
                return True
            client_ip = self.client_address[0] if self.client_address else ""
            if not is_private_client_ip(client_ip):
                seguranca.log_seg(
                    "mobile", "network", seguranca.ALTO, seguranca.DENY,
                    "non_private_client_ip", usuario=client_ip,
                )
                self._send(403, {"ok": False, "error": "lan_client_required"})
                return False
            return True

        def _read_raw_body(self) -> str | None:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send(415, {"ok": False, "error": "application_json_required"})
                return None
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError):
                self._send(400, {"ok": False, "error": "invalid_content_length"})
                return None
            if length <= 0:
                self._send(400, {"ok": False, "error": "empty_body" if length == 0 else "invalid_content_length"})
                return None
            if length > _MAX_BODY:
                self._send(413, {"ok": False, "error": "request_too_large"})
                return None
            raw_bytes = self.rfile.read(length)
            self._corpo_lido = True
            if len(raw_bytes) != length:
                self._send(400, {"ok": False, "error": "incomplete_body"})
                return None
            try:
                return raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                self._send(400, {"ok": False, "error": "invalid_utf8"})
                return None

        def _authenticate_headers(self, raw_body: str) -> tuple[str, str, str, str] | None:
            if not pairing.tem_pareamento_ativo():
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "pairing_not_configured",
                )
                self._send(503, {"ok": False, "error": "pairing_not_configured"})
                return None

            h_device = (self.headers.get("X-Ultron-Device") or "").strip()
            h_ts = (self.headers.get("X-Ultron-Timestamp") or "").strip()
            h_nonce = (self.headers.get("X-Ultron-Nonce") or "").strip()
            h_sig = (self.headers.get("X-Ultron-Signature") or "").strip()
            if not all((h_device, h_ts, h_nonce, h_sig)):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "missing_auth_headers", usuario=h_device or "unknown",
                )
                self._send(401, {"ok": False, "error": "missing_auth_headers"})
                return None

            if not NONCE_RE.fullmatch(h_nonce):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "invalid_nonce", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "invalid_nonce"})
                return None

            if not (h_ts.isascii() and h_ts.isdigit()):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "invalid_timestamp", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "timestamp_expired"})
                return None
            ts_ms = int(h_ts)
            now_ms = int(relogio() * 1000)
            if abs(now_ms - ts_ms) > skew_s * 1000:
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "timestamp_expired", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "timestamp_expired"})
                return None

            shared_secret = pairing.obter_segredo_dispositivo(h_device)
            if not shared_secret:
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "device_not_paired", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "unauthorized_device"})
                return None

            provided_sig = re.sub(r"^sha256=", "", h_sig, flags=re.IGNORECASE).lower()
            if not _HEX64_RE.fullmatch(provided_sig):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "invalid_signature", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "invalid_signature"})
                return None
            expected_sig = compute_command_signature(shared_secret, h_ts, h_nonce, raw_body)
            if not hmac.compare_digest(provided_sig, expected_sig):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "invalid_signature", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "invalid_signature"})
                return None

            return h_device, h_ts, h_nonce, shared_secret

        def _parse_signed_json(self, raw_body: str, h_device: str, h_ts: str, h_nonce: str, shared_secret: str) -> dict | None:
            try:
                body = json.loads(raw_body)
            except ValueError:
                self._send(400, {"ok": False, "error": "invalid_json"}, sign_secret=shared_secret)
                return None
            if not isinstance(body, dict):
                self._send(400, {"ok": False, "error": "json_object_required"}, sign_secret=shared_secret)
                return None

            if body.get("device_id") != h_device:
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "device_mismatch", usuario=h_device,
                )
                self._send(403, {"ok": False, "error": "device_mismatch"}, sign_secret=shared_secret)
                return None

            body_ts = body.get("timestamp")
            if body_ts is None or str(body_ts) != h_ts:
                self._send(400, {"ok": False, "error": "timestamp_mismatch"}, sign_secret=shared_secret)
                return None

            if body.get("nonce") != h_nonce:
                self._send(400, {"ok": False, "error": "nonce_mismatch"}, sign_secret=shared_secret)
                return None
            return body

        def _handle_command(self):
            raw_body = self._read_raw_body()
            if raw_body is None:
                return
            auth = self._authenticate_headers(raw_body)
            if auth is None:
                return
            h_device, h_ts, h_nonce, shared_secret = auth
            body = self._parse_signed_json(raw_body, h_device, h_ts, h_nonce, shared_secret)
            if body is None:
                return

            command = body.get("command")
            if not isinstance(command, str) or not command.strip():
                self._send(400, {"ok": False, "error": "invalid_command"}, sign_secret=shared_secret)
                return

            args = body.get("args", {})
            if not isinstance(args, dict):
                self._send(400, {"ok": False, "error": "invalid_args"}, sign_secret=shared_secret)
                return

            if not nonce_store.check_and_mark(f"dev:{h_device}:{h_nonce}", now=relogio()):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "nonce_replay", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "nonce_replay"}, sign_secret=shared_secret)
                return

            try:
                resultado = active_dispatcher.dispatch(h_device, command, args)
                self._send(200, resultado, sign_secret=shared_secret)
            except CommandError as err:
                self._send(
                    err.status_code,
                    {"ok": False, "error": err.error_code, "message": err.message},
                    sign_secret=shared_secret,
                )
            except Exception as exc:
                seguranca.log.warning("Falha interna ao executar comando mobile (%s).", type(exc).__name__)
                self._send(500, {"ok": False, "error": "internal_error"}, sign_secret=shared_secret)

        def _handle_poll(self, query: str):
            qs = parse_qs(query, keep_blank_values=True)
            wait_s = mobile_bridge.POLL_WAIT_DEFAULT_S
            if "wait_s" in qs:
                raw_wait = (qs["wait_s"][0] or "").strip()
                try:
                    num_wait = float(raw_wait)
                    if not math.isfinite(num_wait):
                        raise ValueError("non_finite")
                    parsed_wait = int(num_wait)
                except ValueError:
                    seguranca.log_seg(
                        "mobile", "poll", seguranca.MEDIO, seguranca.DENY,
                        "invalid_wait_s",
                    )
                    self._send(400, {"ok": False, "error": "invalid_wait_s"})
                    return
                wait_s = min(max(parsed_wait, mobile_bridge.POLL_WAIT_MIN_S), mobile_bridge.POLL_WAIT_MAX_S)

            auth = self._authenticate_headers("")
            if auth is None:
                return
            h_device, _h_ts, h_nonce, shared_secret = auth

            if not nonce_store.check_and_mark(f"dev:{h_device}:{h_nonce}", now=relogio()):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "nonce_replay", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "nonce_replay"}, sign_secret=shared_secret)
                return

            if active_bridge.record_poll(h_device):
                seguranca.log_seg(
                    "mobile", "poll", seguranca.BAIXO, seguranca.ALLOW,
                    "connected", usuario=h_device,
                )

            cmd = active_bridge.poll_next(h_device, wait_s=wait_s)
            if cmd is None:
                self._send_no_content()
                return

            seguranca.log_seg(
                "mobile", "poll_dispatch", seguranca.BAIXO, seguranca.ALLOW,
                cmd["command"], args=cmd["args"], usuario=h_device,
            )
            resp_ts = str(int(relogio() * 1000))
            resp_nonce = secrets.token_hex(16)
            payload = {
                "command_id": cmd["command_id"],
                "device_id": cmd["device_id"],
                "command": cmd["command"],
                "args": cmd["args"],
                "timestamp": resp_ts,
                "nonce": resp_nonce,
            }
            self._send(
                200,
                payload,
                sign_secret=shared_secret,
                resp_ts=resp_ts,
                resp_nonce=resp_nonce,
            )

        def _handle_result(self):
            raw_body = self._read_raw_body()
            if raw_body is None:
                return
            auth = self._authenticate_headers(raw_body)
            if auth is None:
                return
            h_device, h_ts, h_nonce, shared_secret = auth
            body = self._parse_signed_json(raw_body, h_device, h_ts, h_nonce, shared_secret)
            if body is None:
                return

            command_id = body.get("command_id")
            if not isinstance(command_id, str) or not command_id.strip():
                self._send(400, {"ok": False, "error": "invalid_command_id"}, sign_secret=shared_secret)
                return
            if not isinstance(body.get("ok"), bool):
                self._send(400, {"ok": False, "error": "invalid_ok_flag"}, sign_secret=shared_secret)
                return

            if not nonce_store.check_and_mark(f"dev:{h_device}:{h_nonce}", now=relogio()):
                seguranca.log_seg(
                    "mobile", "auth", seguranca.ALTO, seguranca.DENY,
                    "nonce_replay", usuario=h_device,
                )
                self._send(401, {"ok": False, "error": "nonce_replay"}, sign_secret=shared_secret)
                return

            accepted, reason = active_bridge.submit_result(h_device, body)
            if not accepted:
                status = 403 if reason == "device_mismatch" else (409 if reason == "duplicate_result" else 404)
                seguranca.log_seg(
                    "mobile", "result", seguranca.MEDIO, seguranca.DENY,
                    reason, usuario=h_device,
                )
                self._send(status, {"ok": False, "error": reason}, sign_secret=shared_secret)
                return

            seguranca.log_seg(
                "mobile",
                "result",
                seguranca.BAIXO,
                seguranca.ALLOW,
                reason,
                args={"command": str(body.get("command") or ""), "ok": body.get("ok")},
                usuario=h_device,
            )
            self._send(
                200,
                {"ok": True, "accepted": True, "command_id": command_id.strip()},
                sign_secret=shared_secret,
            )

        def _handle_killswitch(self):
            raw_body = self._read_raw_body()
            if raw_body is None:
                return
            candidates = pairing.obter_segredos_killswitch()
            if not candidates:
                seguranca.log_seg(
                    "mobile", "killswitch", seguranca.CRITICO, seguranca.DENY,
                    "killswitch_not_configured",
                )
                self._send(503, {"ok": False, "error": "killswitch_not_configured"})
                return

            h_sig = (self.headers.get("X-Ultron-Signature") or "").strip()
            h_ts = (self.headers.get("X-Ultron-Timestamp") or "").strip()
            sig_match = _KS_SIG_RE.fullmatch(h_sig)
            if not sig_match or not h_ts:
                seguranca.log_seg(
                    "mobile", "killswitch", seguranca.CRITICO, seguranca.DENY,
                    "invalid_signature_header",
                )
                self._send(401, {"ok": False, "error": "invalid_signature_header"})
                return
            provided_hex = sig_match.group(1).lower()

            ts_epoch = _parse_iso8601_utc(h_ts)
            if ts_epoch is None or abs(relogio() - ts_epoch) > skew_s:
                seguranca.log_seg(
                    "mobile", "killswitch", seguranca.CRITICO, seguranca.DENY,
                    "timestamp_expired",
                )
                self._send(401, {"ok": False, "error": "timestamp_expired"})
                return

            matched_label = None
            matched_secret = None
            for label, secret in candidates:
                expected = compute_raw_signature(secret, raw_body)
                if hmac.compare_digest(provided_hex, expected) and matched_secret is None:
                    matched_label = label
                    matched_secret = secret

            if not matched_secret or matched_label is None:
                seguranca.log_seg(
                    "mobile", "killswitch", seguranca.CRITICO, seguranca.DENY,
                    "invalid_signature",
                )
                self._send(401, {"ok": False, "error": "invalid_signature"})
                return

            try:
                body = json.loads(raw_body)
            except ValueError:
                self._send(400, {"ok": False, "error": "invalid_json"}, sign_secret=matched_secret, killswitch_mode=True)
                return
            if not isinstance(body, dict):
                self._send(400, {"ok": False, "error": "json_object_required"}, sign_secret=matched_secret, killswitch_mode=True)
                return

            if body.get("command") != "LOCK_WORKSTATION":
                self._send(400, {"ok": False, "error": "invalid_killswitch_command"}, sign_secret=matched_secret, killswitch_mode=True)
                return

            if body.get("source") != "ULTRON_MOBILE":
                self._send(403, {"ok": False, "error": "invalid_killswitch_source"}, sign_secret=matched_secret, killswitch_mode=True)
                return

            if body.get("timestamp") != h_ts:
                self._send(400, {"ok": False, "error": "timestamp_mismatch"}, sign_secret=matched_secret, killswitch_mode=True)
                return

            replay_key = "ks:" + hashlib.sha256(f"{h_ts}.{provided_hex}".encode("utf-8")).hexdigest()
            if not nonce_store.check_and_mark(replay_key, now=relogio()):
                seguranca.log_seg(
                    "mobile", "killswitch", seguranca.CRITICO, seguranca.DENY,
                    "replay_detected", usuario=matched_label,
                )
                self._send(401, {"ok": False, "error": "replay_detected"}, sign_secret=matched_secret, killswitch_mode=True)
                return

            try:
                res = active_dispatcher.execute_killswitch(
                    body.get("reason", "manual"),
                    body["source"],
                    matched_label,
                )
                self._send(200, res, sign_secret=matched_secret, killswitch_mode=True)
            except Exception as exc:
                seguranca.log.warning("Falha ao executar killswitch (%s).", type(exc).__name__)
                self._send(
                    500,
                    {"ok": False, "error": "killswitch_failed"},
                    sign_secret=matched_secret,
                    killswitch_mode=True,
                )

        def do_POST(self):
            if not self._check_client_ip():
                return
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment:
                self._send(400, {"ok": False, "error": "query_not_supported"})
                return
            if parsed.path == "/api/mobile/command":
                self._handle_command()
            elif parsed.path == "/api/mobile/result":
                self._handle_result()
            elif parsed.path == "/killswitch":
                self._handle_killswitch()
            elif parsed.path == "/api/mobile/poll":
                self._method_not_allowed()
            else:
                self._send(404, {"ok": False, "error": "not_found"})

        def do_GET(self):
            if not self._check_client_ip():
                return
            parsed = urlsplit(self.path)
            if parsed.fragment:
                self._send(400, {"ok": False, "error": "fragment_not_supported"})
                return
            if parsed.path == "/api/mobile/poll":
                self._handle_poll(parsed.query)
            elif parsed.path in {"/api/mobile/command", "/api/mobile/result", "/killswitch"}:
                self._method_not_allowed()
            else:
                self._send(404, {"ok": False, "error": "not_found"})

        def _method_not_allowed(self):
            if not self._check_client_ip():
                return
            self._send(405, {"ok": False, "error": "method_not_allowed"})

        do_PUT = _method_not_allowed
        do_DELETE = _method_not_allowed
        do_OPTIONS = _method_not_allowed

    server = _MobileServer((bind_host, bind_port), Handler)
    server.mobile_bridge = active_bridge
    actual_host, actual_port = server.server_address[:2]
    display_host = mobile_pairing.descobrir_ip_lan() if actual_host in ("0.0.0.0", "::") else actual_host
    return server, f"http://{display_host}:{actual_port}"
