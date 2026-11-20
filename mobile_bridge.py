"""Ponte reversa PC -> Celular via fila por dispositivo e Long-Poll HTTP LAN."""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass

import mobile_pairing
import seguranca

POLL_WAIT_MIN_S = 1
POLL_WAIT_MAX_S = 25
POLL_WAIT_DEFAULT_S = 20

DEFAULT_RESULT_TIMEOUT_S = 14.0
SENSITIVE_RESULT_TIMEOUT_S = 25.0

MEDIA_ACTIONS = frozenset({"play_pause", "play", "pause", "next", "previous", "stop"})
SENSITIVE_MOBILE_COMMANDS = frozenset({
    "WHATSAPP",
    "SMS",
    "REPLY_MESSAGE",
    "DIAL",
    "CREATE_EVENT",
})
ALLOWED_MOBILE_COMMANDS = frozenset({
    "PING",
    "DEVICE_STATUS",
    "OPEN_APP",
    "OPEN_CAMERA",
    "TORCH_ON",
    "TORCH_OFF",
    "TORCH_TOGGLE",
    "VOLUME_SET",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "VOLUME_MUTE",
    "MEDIA",
    "VIBRATE",
    "NOTE",
    "READ_CALENDAR",
    "READ_MESSAGES",
    *SENSITIVE_MOBILE_COMMANDS,
})

_DIAL_RE = re.compile(r"^[0-9+\-()\s*#]{2,32}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class MobileBridgeError(RuntimeError):
    """Erro controlado ao despachar ou aguardar comando para o U.L.T.R.O.N. Mobile."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _limpar_texto(valor, campo: str, *, max_len: int, permitir_quebra: bool = False) -> str:
    if not isinstance(valor, str):
        raise ValueError(f"Campo '{campo}' deve ser texto.")
    texto = valor.strip() if not permitir_quebra else valor.strip("\r\n ").replace("\r\n", "\n")
    if not texto:
        raise ValueError(f"Campo '{campo}' é obrigatório.")
    if len(texto) > max_len:
        raise ValueError(f"Campo '{campo}' excede {max_len} caracteres.")
    if _CONTROL_RE.search(texto) or (not permitir_quebra and ("\n" in texto or "\r" in texto)):
        raise ValueError(f"Campo '{campo}' contém caracteres de controle inválidos.")
    return texto


def _exigir_int(valor, campo: str, minimo: int, maximo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        if isinstance(valor, str) and valor.strip().lstrip("+-").isdigit():
            valor = int(valor.strip())
        else:
            raise ValueError(f"Campo '{campo}' deve ser inteiro entre {minimo} e {maximo}.")
    if valor < minimo or valor > maximo:
        raise ValueError(f"Campo '{campo}' deve estar entre {minimo} e {maximo}.")
    return valor


def validate_reverse_command(command: str, args: dict | None = None) -> tuple[str, dict]:
    """Valida comando PC -> Celular em allowlist estrita antes de enfileirar."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Comando Mobile ausente.")
    cmd = command.strip().upper()
    if cmd not in ALLOWED_MOBILE_COMMANDS:
        raise ValueError(f"Comando Mobile não permitido: {cmd}")
    raw = {} if args is None else args
    if not isinstance(raw, dict):
        raise ValueError("Argumentos do comando Mobile devem formar um objeto.")

    if cmd in {
        "PING",
        "DEVICE_STATUS",
        "OPEN_CAMERA",
        "TORCH_ON",
        "TORCH_OFF",
        "TORCH_TOGGLE",
        "VOLUME_UP",
        "VOLUME_DOWN",
        "VOLUME_MUTE",
        "READ_MESSAGES",
    }:
        return cmd, {}

    if cmd == "OPEN_APP":
        return cmd, {"app": _limpar_texto(raw.get("app"), "app", max_len=80)}

    if cmd == "VOLUME_SET":
        percent = _exigir_int(raw.get("percent"), "percent", 0, 100)
        return cmd, {"percent": percent}

    if cmd == "MEDIA":
        action = _limpar_texto(raw.get("action"), "action", max_len=32).lower()
        if action not in MEDIA_ACTIONS:
            raise ValueError(f"Ação de mídia inválida: {action}")
        return cmd, {"action": action}

    if cmd == "VIBRATE":
        dur = 280 if "durationMs" not in raw or raw.get("durationMs") is None else _exigir_int(
            raw.get("durationMs"), "durationMs", 50, 5000
        )
        return cmd, {"durationMs": dur}

    if cmd == "NOTE":
        return cmd, {"text": _limpar_texto(raw.get("text"), "text", max_len=4000, permitir_quebra=True)}

    if cmd == "READ_CALENDAR":
        days = 3 if "days" not in raw or raw.get("days") is None else _exigir_int(
            raw.get("days"), "days", 1, 14
        )
        return cmd, {"days": days}

    if cmd in {"WHATSAPP", "SMS", "REPLY_MESSAGE"}:
        target = _limpar_texto(raw.get("target"), "target", max_len=120)
        text = _limpar_texto(raw.get("text"), "text", max_len=2000, permitir_quebra=True)
        return cmd, {"target": target, "text": text}

    if cmd == "DIAL":
        number = _limpar_texto(raw.get("number"), "number", max_len=32)
        if not _DIAL_RE.fullmatch(number) or not any(ch.isdigit() for ch in number):
            raise ValueError("Número de telefone inválido.")
        return cmd, {"number": number}

    if cmd == "CREATE_EVENT":
        title = _limpar_texto(raw.get("title"), "title", max_len=200)
        start = _limpar_texto(raw.get("start"), "start", max_len=64)
        out = {"title": title, "start": start}
        if raw.get("end"):
            out["end"] = _limpar_texto(raw.get("end"), "end", max_len=64)
        if raw.get("notes"):
            out["notes"] = _limpar_texto(raw.get("notes"), "notes", max_len=1000, permitir_quebra=True)
        return cmd, out

    raise ValueError(f"Comando Mobile não suportado: {cmd}")


@dataclass
class _QueuedCommand:
    command_id: str
    device_id: str
    command: str
    args: dict


@dataclass
class _PendingResult:
    command_id: str
    device_id: str
    command: str
    event: threading.Event
    result: dict | None = None


class MobileReverseBridge:
    """Coordena fila de comandos PC -> Mobile com Long-Poll e espera síncrona de resultado."""

    def __init__(self, pairing_module=None, now_fn=None):
        self._pairing = pairing_module
        self._now = now_fn or time.monotonic
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._queues: dict[str, deque[_QueuedCommand]] = {}
        self._pending: dict[str, _PendingResult] = {}
        self._last_poll_at: dict[str, float] = {}
        self._closed = False

    def record_poll(self, device_id: str) -> bool:
        """Registra atividade de long-poll de device_id; retorna True na 1ª conexão ou reconexão (>60s)."""
        agora = time.monotonic()
        with self._cond:
            anterior = self._last_poll_at.get(device_id)
            self._last_poll_at[device_id] = agora
            return anterior is None or (agora - anterior) > 60.0

    def has_recent_poll(self, device_id: str, max_age_s: float = 60.0) -> bool:
        with self._cond:
            ts = self._last_poll_at.get(device_id)
            if ts is None:
                return False
            return (time.monotonic() - ts) <= max(1.0, float(max_age_s))

    def reopen(self) -> None:
        with self._cond:
            self._closed = False
            self._cond.notify_all()

    def close(self) -> None:
        """Acorda imediatamente todos os long-polls e chamadores em espera no shutdown."""
        with self._cond:
            self._closed = True
            for pending in self._pending.values():
                pending.event.set()
            self._cond.notify_all()

    def resolve_target_device(self, device_id: str | None = None, pairing_module=None) -> str:
        pairing = pairing_module or self._pairing or mobile_pairing
        if device_id is not None and str(device_id).strip():
            dev_id = pairing.validar_device_id(str(device_id))
            if not pairing.obter_segredo_dispositivo(dev_id):
                raise MobileBridgeError(
                    "device_not_paired",
                    f"O dispositivo '{dev_id}' não está pareado no momento.",
                )
            return dev_id
        status = pairing.status_publico()
        devices = status.get("devices") if isinstance(status, dict) else []
        if not devices:
            raise MobileBridgeError(
                "no_paired_device",
                "Nenhum celular está pareado no momento. Gere e leia o QR Code na aba Celular.",
            )
        return str(devices[0]["device_id"])

    def enqueue_and_wait(
        self,
        command: str,
        args: dict | None = None,
        *,
        device_id: str | None = None,
        timeout_s: float | None = None,
        pairing_module=None,
    ) -> dict:
        cmd, clean_args = validate_reverse_command(command, args)
        target_device = self.resolve_target_device(device_id, pairing_module=pairing_module)
        wait_timeout = (
            float(timeout_s)
            if timeout_s is not None
            else (SENSITIVE_RESULT_TIMEOUT_S if cmd in SENSITIVE_MOBILE_COMMANDS else DEFAULT_RESULT_TIMEOUT_S)
        )
        wait_timeout = max(0.05, wait_timeout)

        command_id = str(uuid.uuid4())
        item = _QueuedCommand(
            command_id=command_id,
            device_id=target_device,
            command=cmd,
            args=clean_args,
        )
        pending = _PendingResult(
            command_id=command_id,
            device_id=target_device,
            command=cmd,
            event=threading.Event(),
        )

        with self._cond:
            if self._closed:
                raise MobileBridgeError(
                    "bridge_closed",
                    "O servidor Mobile está encerrado no momento.",
                )
            fila = self._queues.setdefault(target_device, deque())
            fila.append(item)
            self._pending[command_id] = pending
            self._cond.notify_all()

        risco = seguranca.CRITICO if cmd in SENSITIVE_MOBILE_COMMANDS else seguranca.BAIXO
        seguranca.log_seg(
            "desktop",
            f"mobile_send_{cmd.lower()}",
            risco,
            seguranca.ALLOW,
            "queued_for_mobile",
            args=clean_args,
            usuario=target_device,
        )

        signaled = pending.event.wait(timeout=wait_timeout)

        with self._cond:
            self._pending.pop(command_id, None)
            fila = self._queues.get(target_device)
            if fila:
                filtrada = deque(entry for entry in fila if entry.command_id != command_id)
                if filtrada:
                    self._queues[target_device] = filtrada
                else:
                    self._queues.pop(target_device, None)
            closed = self._closed
            resultado = pending.result

        if resultado is not None:
            return resultado
        if closed and signaled:
            raise MobileBridgeError(
                "bridge_closed",
                "A conexão Mobile foi encerrada antes de o celular responder.",
            )
        polled = self.has_recent_poll(target_device)
        reason_code = "mobile_timeout" if polled else "mobile_not_polling"
        seguranca.log_seg(
            "desktop",
            f"mobile_send_{cmd.lower()}",
            risco,
            seguranca.DENY,
            reason_code,
            usuario=target_device,
        )
        if not polled:
            raise MobileBridgeError(
                "mobile_timeout",
                (
                    f"O celular pareado ({target_device}) não respondeu porque ainda não conectou no canal "
                    "de escuta do PC (/api/mobile/poll). Abra o U.L.T.R.O.N. Mobile atualizado na mesma rede "
                    "Wi-Fi e confira se o listener PC -> Celular está ativo no aplicativo."
                ),
            )
        raise MobileBridgeError(
            "mobile_timeout",
            (
                f"O celular pareado ({target_device}) não respondeu a tempo para '{cmd}'. "
                "Ele pode estar offline, com a tela bloqueada ou ocupado."
            ),
        )

    def poll_next(self, device_id: str, wait_s: float = POLL_WAIT_DEFAULT_S) -> dict | None:
        """Aguarda até wait_s por um comando pendente para device_id; retorna None no timeout/close."""
        espera = min(max(float(wait_s), 0.05), float(POLL_WAIT_MAX_S))
        deadline = time.monotonic() + espera
        with self._cond:
            self._last_poll_at[device_id] = time.monotonic()
            while not self._closed:
                fila = self._queues.get(device_id)
                if fila:
                    item = fila.popleft()
                    if not fila:
                        self._queues.pop(device_id, None)
                    return {
                        "command_id": item.command_id,
                        "device_id": item.device_id,
                        "command": item.command,
                        "args": dict(item.args),
                    }
                restante = deadline - time.monotonic()
                if restante <= 0:
                    return None
                self._cond.wait(timeout=restante)
            return None

    def submit_result(self, device_id: str, payload: dict) -> tuple[bool, str]:
        """Recebe resultado enviado pelo Mobile e acorda o chamador aguardando command_id."""
        if not isinstance(payload, dict):
            return False, "json_object_required"
        command_id = payload.get("command_id")
        if not isinstance(command_id, str) or not command_id.strip():
            return False, "invalid_command_id"
        command_id = command_id.strip()

        with self._cond:
            pending = self._pending.get(command_id)
            if pending is None:
                return False, "unknown_or_expired_command"
            if pending.device_id != device_id:
                return False, "device_mismatch"
            if pending.result is not None:
                return False, "duplicate_result"
            raw_cmd = payload.get("command")
            if isinstance(raw_cmd, str) and raw_cmd.strip() and raw_cmd.strip().upper() != pending.command:
                return False, "command_mismatch"
            ok = payload.get("ok")
            if not isinstance(ok, bool):
                return False, "invalid_ok_flag"
            data = payload.get("data", {})
            if not isinstance(data, dict):
                return False, "invalid_data"
            message = payload.get("message", "")
            status = payload.get("status", "executed" if ok else "failed")
            pending.result = {
                "command_id": command_id,
                "device_id": device_id,
                "command": pending.command,
                "ok": ok,
                "status": str(status or ("executed" if ok else "failed")),
                "message": str(message or ""),
                "data": data,
            }
            pending.event.set()
            self._cond.notify_all()
        return True, "accepted"


_BRIDGE_LOCK = threading.Lock()
_DEFAULT_BRIDGE: MobileReverseBridge | None = None


def get_bridge() -> MobileReverseBridge:
    global _DEFAULT_BRIDGE
    with _BRIDGE_LOCK:
        if _DEFAULT_BRIDGE is None:
            _DEFAULT_BRIDGE = MobileReverseBridge()
        return _DEFAULT_BRIDGE


def set_bridge(bridge: MobileReverseBridge | None) -> None:
    global _DEFAULT_BRIDGE
    with _BRIDGE_LOCK:
        _DEFAULT_BRIDGE = bridge
