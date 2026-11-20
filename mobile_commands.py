"""Roteamento seguro (allowlist + fail-closed) para comandos autenticados do U.L.T.R.O.N. Mobile."""
from __future__ import annotations

import ctypes
import os
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

import config
import desktop_api
import ferramentas_apps
import hardware
import seguranca
import sessao
import skills

ALLOWED_COMMANDS = frozenset({
    "PING",
    "STATUS",
    "PC_STATUS",
    "PC_OPEN_APP",
    "PC_MEDIA",
    "PC_CLIPBOARD_PUSH",
    "PC_CLIPBOARD_PULL",
    "PC_RUN_SKILL",
})

MAX_CLIPBOARD_CHARS = 32768
_MAX_APP_LEN = 80
_SHELL_META_CHARS = frozenset(";&|><$`\r\n\x00")
_BLOCKED_REMOTE_APPS = frozenset({
    "cmd", "cmd.exe", "command prompt", "prompt de comando",
    "powershell", "powershell.exe", "windows powershell", "pwsh", "pwsh.exe",
    "wt", "windows terminal", "terminal",
    "bash", "wsl", "wsl.exe",
    "regedit", "regedit.exe", "editor do registro",
    "mshta", "mshta.exe", "wscript", "wscript.exe", "cscript", "cscript.exe",
    "rundll32", "rundll32.exe", "mmc", "mmc.exe", "diskpart", "diskpart.exe",
})
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")

ALLOWED_MEDIA_ACTIONS = {
    "play_pause": "playpause",
    "play": "playpause",
    "pause": "playpause",
    "next": "nexttrack",
    "previous": "prevtrack",
    "prev": "prevtrack",
    "stop": "stop",
    "mute": "volumemute",
    "unmute": "volumemute",
    "volume_up": "volumeup",
    "volume_down": "volumedown",
}

_WIN_VK_MEDIA = {
    "playpause": 0xB3,
    "nexttrack": 0xB0,
    "prevtrack": 0xB1,
    "stop": 0xB2,
    "volumemute": 0xAD,
    "volumeup": 0xAF,
    "volumedown": 0xAE,
}


class CommandError(Exception):
    """Erro estruturado mapeado diretamente para resposta HTTP."""

    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def _default_launch_app(target: str) -> None:
    if os.name == "nt":
        os.startfile(target)  # noqa: S606 - target vem estritamente da allowlist explícita
        return
    raise RuntimeError("Lançamento de aplicativo remoto disponível apenas no Windows.")


def _default_send_media(mapped_key: str) -> None:
    if os.name == "nt" and mapped_key in _WIN_VK_MEDIA:
        vk = _WIN_VK_MEDIA[mapped_key]
        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 0x0002, 0)
        return
    import pyautogui
    pyautogui.press(mapped_key)


def _default_clipboard_copy(text: str) -> None:
    import pyperclip
    pyperclip.copy(text)


def _default_clipboard_paste() -> str:
    import pyperclip
    return str(pyperclip.paste() or "")


def _default_lock_workstation() -> None:
    if os.name != "nt":
        raise RuntimeError("LockWorkStation disponível apenas no Windows.")
    ok = ctypes.windll.user32.LockWorkStation()
    if not ok:
        raise RuntimeError("Falha ao bloquear a estação de trabalho no Windows.")


class MobileCommandDispatcher:
    """Executa comandos remotos do Mobile com allowlist estrita e política fail-closed."""

    def __init__(
        self,
        runtime=None,
        *,
        launch_app=None,
        resolve_installed_app=None,
        launch_installed_item=None,
        send_media=None,
        clipboard_copy=None,
        clipboard_paste=None,
        lock_workstation=None,
        get_version=None,
    ):
        self.runtime = runtime
        self._custom_launch_app = launch_app is not None
        self._launch_app = launch_app or _default_launch_app
        self._resolve_installed_app = resolve_installed_app or ferramentas_apps._resolver_app
        self._launch_installed_item = launch_installed_item
        self._send_media = send_media or _default_send_media
        self._clipboard_copy = clipboard_copy or _default_clipboard_copy
        self._clipboard_paste = clipboard_paste or _default_clipboard_paste
        self._lock_workstation = lock_workstation or _default_lock_workstation
        self._get_version = get_version or desktop_api._obter_versao

    def dispatch(self, device_id: str, command: str, args: dict) -> dict:
        cmd = str(command or "").strip().upper()
        if cmd not in ALLOWED_COMMANDS:
            seguranca.log_seg(
                "mobile",
                f"cmd:{cmd or 'empty'}",
                seguranca.ALTO,
                seguranca.DENY,
                "command_not_allowed",
                args,
                usuario=device_id,
            )
            raise CommandError(403, "command_not_allowed", f"Comando não permitido: {cmd or '(vazio)'}")

        if cmd not in {"PING", "STATUS", "PC_STATUS"} and seguranca.parada.is_set():
            seguranca.log_seg(
                "mobile",
                cmd,
                seguranca.MEDIO,
                seguranca.DENY,
                "emergency_stop_active",
                usuario=device_id,
            )
            raise CommandError(409, "emergency_stop_active", "Parada de emergência ativa no Desktop.")

        if cmd in {"PING", "STATUS", "PC_STATUS"}:
            return self._handle_status(device_id, cmd)
        if cmd == "PC_OPEN_APP":
            return self._handle_open_app(device_id, args)
        if cmd == "PC_MEDIA":
            return self._handle_media(device_id, args)
        if cmd == "PC_CLIPBOARD_PUSH":
            return self._handle_clipboard_push(device_id, args)
        if cmd == "PC_CLIPBOARD_PULL":
            return self._handle_clipboard_pull(device_id)
        if cmd == "PC_RUN_SKILL":
            return self._handle_run_skill(device_id, args)
        raise CommandError(403, "command_not_allowed", f"Comando não permitido: {cmd}")

    def _handle_status(self, device_id: str, cmd: str) -> dict:
        cpu = psutil.cpu_percent(interval=0.05)
        mem = psutil.virtual_memory()
        uptime_seconds = max(0, int(time.time() - psutil.boot_time()))
        st = sessao.estado()
        runtime_running = bool(self.runtime is not None and getattr(self.runtime, "_started", False))
        seguranca.log_seg("mobile", cmd, seguranca.BAIXO, seguranca.ALLOW, "ok", usuario=device_id)
        return {
            "ok": True,
            "command": cmd,
            "status": "online",
            "version": str(self._get_version()),
            "hostname": socket.gethostname(),
            "cpu_percent": round(float(cpu), 1),
            "ram_percent": round(float(mem.percent), 1),
            "ram_used_mb": int(mem.used // (1024 * 1024)),
            "ram_total_mb": int(mem.total // (1024 * 1024)),
            "uptime_seconds": uptime_seconds,
            "uptime_human": hardware._uptime(),
            "session": {
                "unlocked": bool(st.get("desbloqueada")),
                "method": st.get("metodo"),
            },
            "runtime_running": runtime_running,
            "timestamp": int(time.time() * 1000),
        }

    @staticmethod
    def _build_app_allowlist() -> dict[str, tuple[str, str]]:
        """Mapeia nomes normalizados -> (nome_canonico, alvo) exclusivamente da allowlist."""
        programas = seguranca.allowlist("programas", {}) or {}
        mobile_extra = seguranca.allowlist("mobile_programas", {}) or {}
        combined: dict[str, str] = {}
        if isinstance(programas, dict):
            combined.update(programas)
        if isinstance(mobile_extra, dict):
            combined.update(mobile_extra)

        indice: dict[str, tuple[str, str]] = {}
        for chave, alvo in combined.items():
            if not isinstance(chave, str) or not isinstance(alvo, str):
                continue
            nome_limpo = chave.strip()
            alvo_limpo = alvo.strip()
            if not nome_limpo or not alvo_limpo:
                continue
            par = (nome_limpo, alvo_limpo)
            indice[nome_limpo.lower()] = par
            indice[seguranca.normalizar(nome_limpo).strip()] = par
            alvo_stem = alvo_limpo.rstrip(":").lower()
            if alvo_stem and not any(sep in alvo_stem for sep in ("/", "\\", " ")):
                indice.setdefault(alvo_stem, par)
            elif "\\" in alvo_limpo or "/" in alvo_limpo:
                stem = Path(alvo_limpo).stem.lower()
                if stem:
                    indice.setdefault(stem, par)
        return indice

    def _handle_open_app(self, device_id: str, args: dict) -> dict:
        app = args.get("app")
        if not isinstance(app, str) or not 1 <= len(app.strip()) <= _MAX_APP_LEN:
            seguranca.log_seg(
                "mobile", "PC_OPEN_APP", seguranca.MEDIO, seguranca.DENY,
                "invalid_app_payload", args, usuario=device_id,
            )
            raise CommandError(400, "invalid_app_payload", "Parâmetro 'app' inválido.")
        app_limpo = app.strip()
        if any(ch in _SHELL_META_CHARS for ch in app_limpo):
            seguranca.log_seg(
                "mobile", "PC_OPEN_APP", seguranca.ALTO, seguranca.DENY,
                "shell_metachar_rejected", {"app": app_limpo}, usuario=device_id,
            )
            raise CommandError(403, "app_not_allowed", "Caracteres inválidos no nome do aplicativo.")

        app_lower = app_limpo.lower()
        app_norm = seguranca.normalizar(app_limpo).strip()
        if (
            app_lower in _BLOCKED_REMOTE_APPS
            or app_norm in _BLOCKED_REMOTE_APPS
            or "powershell" in app_norm
            or seguranca.comando_bloqueado(app_limpo)
        ):
            seguranca.log_seg(
                "mobile", "PC_OPEN_APP", seguranca.CRITICO, seguranca.DENY,
                "blocked_target", {"app": app_limpo}, usuario=device_id,
            )
            raise CommandError(403, "app_not_allowed", "Aplicativo bloqueado pela política de segurança.")

        indice = self._build_app_allowlist()
        achado = indice.get(app_lower) or indice.get(app_norm)
        if achado:
            nome_canonico, alvo = achado
            if seguranca.comando_bloqueado(alvo):
                seguranca.log_seg(
                    "mobile", "PC_OPEN_APP", seguranca.CRITICO, seguranca.DENY,
                    "blocked_target", {"app": nome_canonico}, usuario=device_id,
                )
                raise CommandError(403, "app_not_allowed", "Alvo bloqueado pela política de segurança.")

            self._launch_app(alvo)
            seguranca.log_seg(
                "mobile", "PC_OPEN_APP", seguranca.BAIXO, "EXECUTED", "ok",
                {"app": nome_canonico}, usuario=device_id,
            )
            return {
                "ok": True,
                "command": "PC_OPEN_APP",
                "app": nome_canonico,
                "launched": True,
            }

        if bool(seguranca.allowlist("aceitar_apps_instalados", False)):
            item, score = self._resolve_installed_app(app_limpo)
            if item and score >= 0.9:
                nome_canonico, tipo, valor = item
                if isinstance(valor, str) and valor.strip():
                    valor_limpo = valor.strip()
                    stem = Path(valor_limpo).stem.lower()
                    nome_norm = seguranca.normalizar(str(nome_canonico)).strip()
                    bloqueado = (
                        tipo not in ("appid", "uri", "arquivo")
                        or any(ch in _SHELL_META_CHARS for ch in valor_limpo)
                        or nome_norm in _BLOCKED_REMOTE_APPS
                        or "powershell" in nome_norm
                        or stem in _BLOCKED_REMOTE_APPS
                        or seguranca.comando_bloqueado(valor_limpo)
                        or seguranca.comando_bloqueado(str(nome_canonico))
                    )
                    if bloqueado:
                        seguranca.log_seg(
                            "mobile", "PC_OPEN_APP", seguranca.CRITICO, seguranca.DENY,
                            "blocked_target", {"app": str(nome_canonico)}, usuario=device_id,
                        )
                        raise CommandError(403, "app_not_allowed", "Alvo bloqueado pela política de segurança.")

                    if self._launch_installed_item is not None:
                        self._launch_installed_item(item)
                    elif self._custom_launch_app:
                        self._launch_app(
                            f"shell:AppsFolder\\{valor_limpo}" if tipo == "appid" else valor_limpo
                        )
                    else:
                        ferramentas_apps._lancar((nome_canonico, tipo, valor_limpo))

                    seguranca.log_seg(
                        "mobile", "PC_OPEN_APP", seguranca.BAIXO, "EXECUTED", "installed_app",
                        {"app": str(nome_canonico)}, usuario=device_id,
                    )
                    return {
                        "ok": True,
                        "command": "PC_OPEN_APP",
                        "app": str(nome_canonico),
                        "launched": True,
                    }

        seguranca.log_seg(
            "mobile", "PC_OPEN_APP", seguranca.MEDIO, seguranca.DENY,
            "app_not_allowed", {"app": app_limpo}, usuario=device_id,
        )
        raise CommandError(403, "app_not_allowed", f"Aplicativo fora da allowlist: {app_limpo}")

    def _handle_media(self, device_id: str, args: dict) -> dict:
        action = args.get("action")
        if not isinstance(action, str) or not action.strip():
            seguranca.log_seg(
                "mobile", "PC_MEDIA", seguranca.BAIXO, seguranca.DENY,
                "invalid_media_action", args, usuario=device_id,
            )
            raise CommandError(400, "invalid_media_action", "Parâmetro 'action' inválido.")
        key = action.strip().lower().replace("-", "_").replace(" ", "_")
        mapped = ALLOWED_MEDIA_ACTIONS.get(key)
        if not mapped:
            seguranca.log_seg(
                "mobile", "PC_MEDIA", seguranca.BAIXO, seguranca.DENY,
                "invalid_media_action", {"action": key}, usuario=device_id,
            )
            raise CommandError(400, "invalid_media_action", f"Ação de mídia não suportada: {action}")

        self._send_media(mapped)
        seguranca.log_seg(
            "mobile", "PC_MEDIA", seguranca.BAIXO, "EXECUTED", "ok",
            {"action": key}, usuario=device_id,
        )
        return {
            "ok": True,
            "command": "PC_MEDIA",
            "action": key,
            "executed": True,
        }

    def _handle_clipboard_push(self, device_id: str, args: dict) -> dict:
        if "text" not in args or not isinstance(args.get("text"), str):
            seguranca.log_seg(
                "mobile", "PC_CLIPBOARD_PUSH", seguranca.MEDIO, seguranca.DENY,
                "invalid_clipboard_payload", usuario=device_id,
            )
            raise CommandError(400, "invalid_clipboard_payload", "Campo 'text' deve ser string.")
        text = args["text"]
        if len(text) > MAX_CLIPBOARD_CHARS:
            seguranca.log_seg(
                "mobile", "PC_CLIPBOARD_PUSH", seguranca.MEDIO, seguranca.DENY,
                "clipboard_too_large", {"length": len(text)}, usuario=device_id,
            )
            raise CommandError(413, "clipboard_too_large", f"Texto excede o limite de {MAX_CLIPBOARD_CHARS} caracteres.")

        self._clipboard_copy(text)
        seguranca.log_seg(
            "mobile", "PC_CLIPBOARD_PUSH", seguranca.MEDIO, "EXECUTED", "ok",
            {"text": text}, usuario=device_id,
        )
        return {
            "ok": True,
            "command": "PC_CLIPBOARD_PUSH",
            "length": len(text),
        }

    def _handle_clipboard_pull(self, device_id: str) -> dict:
        raw_text = str(self._clipboard_paste() or "")
        truncated = len(raw_text) > MAX_CLIPBOARD_CHARS
        text = raw_text[:MAX_CLIPBOARD_CHARS]
        seguranca.log_seg(
            "mobile", "PC_CLIPBOARD_PULL", seguranca.MEDIO, "EXECUTED", "ok",
            {"length": len(text), "truncated": truncated}, usuario=device_id,
        )
        return {
            "ok": True,
            "command": "PC_CLIPBOARD_PULL",
            "text": text,
            "length": len(text),
            "truncated": truncated,
        }

    def _handle_run_skill(self, device_id: str, args: dict) -> dict:
        skill_name = args.get("skill")
        if not isinstance(skill_name, str):
            seguranca.log_seg(
                "mobile", "PC_RUN_SKILL", seguranca.ALTO, seguranca.DENY,
                "invalid_skill_name", usuario=device_id,
            )
            raise CommandError(400, "invalid_skill_name", "Nome de skill inválido.")
        raw = skill_name.strip()
        if (
            not raw
            or "/" in raw
            or "\\" in raw
            or ".." in raw
            or "\x00" in raw
            or not _SKILL_NAME_RE.fullmatch(raw)
        ):
            seguranca.log_seg(
                "mobile", "PC_RUN_SKILL", seguranca.ALTO, seguranca.DENY,
                "invalid_skill_name", {"skill": raw}, usuario=device_id,
            )
            raise CommandError(400, "invalid_skill_name", "Nome de skill inválido.")

        if not getattr(config, "SKILLS_ATIVO", True):
            seguranca.log_seg(
                "mobile", "PC_RUN_SKILL", seguranca.MEDIO, seguranca.DENY,
                "skills_disabled", {"skill": raw}, usuario=device_id,
            )
            raise CommandError(409, "skills_disabled", "Skills estão desativadas.")

        raw_lower = raw.lower()
        matched = next(
            (s for s in skills.listar() if s.slug == raw or s.nome.strip().lower() == raw_lower),
            None,
        )
        if matched is None:
            pendente = next(
                (s for s in skills.pendentes() if s.slug == raw or s.nome.strip().lower() == raw_lower),
                None,
            )
            if pendente is not None:
                seguranca.log_seg(
                    "mobile", "PC_RUN_SKILL", seguranca.ALTO, seguranca.DENY,
                    "skill_pending_approval", {"skill": pendente.slug}, usuario=device_id,
                )
                raise CommandError(403, "skill_pending_approval", f"Skill '{pendente.slug}' aguarda aprovação no Desktop.")
            seguranca.log_seg(
                "mobile", "PC_RUN_SKILL", seguranca.MEDIO, seguranca.DENY,
                "skill_not_found", {"skill": raw}, usuario=device_id,
            )
            raise CommandError(404, "skill_not_found", f"Skill autorizada não encontrada: {raw}")

        if not skills.corpo(matched.slug):
            raise CommandError(404, "skill_not_found", f"Skill sem conteúdo válido: {matched.slug}")

        skills.marcar_uso(matched.slug)
        if self.runtime is not None and getattr(self.runtime, "_started", False) and hasattr(self.runtime, "submit_command"):
            operation_id = self.runtime.submit_command(
                f"Use a skill aprovada '{matched.slug}' ({matched.nome}) e siga o procedimento dela."
            )
            seguranca.log_seg(
                "mobile", "PC_RUN_SKILL", seguranca.MEDIO, "EXECUTED", "queued",
                {"skill": matched.slug, "operation_id": operation_id}, usuario=device_id,
            )
            return {
                "ok": True,
                "command": "PC_RUN_SKILL",
                "status": "queued",
                "skill": matched.slug,
                "nome": matched.nome,
                "operation_id": operation_id,
            }

        seguranca.log_seg(
            "mobile", "PC_RUN_SKILL", seguranca.MEDIO, "EXECUTED", "loaded",
            {"skill": matched.slug}, usuario=device_id,
        )
        return {
            "ok": True,
            "command": "PC_RUN_SKILL",
            "status": "loaded",
            "skill": matched.slug,
            "nome": matched.nome,
            "descricao": matched.descricao,
        }

    def execute_killswitch(self, reason: str, source: str, actor_label: str) -> dict:
        clean_reason = re.sub(r"[\r\n\x00-\x1f\x7f]+", " ", str(reason or "manual")).strip()[:120] or "manual"
        self._lock_workstation()
        sessao.bloquear()
        seguranca.log_seg(
            "mobile",
            "killswitch",
            seguranca.CRITICO,
            seguranca.ALLOW,
            "lock_workstation",
            {"reason": clean_reason, "source": str(source)[:40]},
            resultado="locked",
            usuario=actor_label,
        )
        return {
            "ok": True,
            "command": "LOCK_WORKSTATION",
            "locked": True,
            "reason": clean_reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
