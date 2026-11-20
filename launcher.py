"""ULTRON launcher — the single thing a shortcut or the installer points at.

Why this exists: the old package shipped *both* a compiled launcher (launcher.cs →
"ULTRON Desktop.exe") and a batch file that called pythonw.exe, and they disagreed
about which one was the real entry point. That is confusing for a user and noisy for
an antivirus (an unsigned PE that fires another hidden process). This script is the
only entry point now:

    ULTRON.exe              open the desktop panel (no console window)
    ULTRON.exe --texto      console chat through main.py
    ULTRON.exe --bandeja    tray icon only
    ULTRON.exe --doctor     local diagnostics, prints a report, changes nothing

It is compiled by tools/build_setup.py into ULTRON.exe with the official icon and
version information. Running it from source works too (python launcher.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "U.L.T.R.O.N. Desktop"


def _install_root() -> Path:
    """Pasta do programa. Quando compilado, é onde o ULTRON.exe está (não a pasta
    temporária onde o PyInstaller se extrai)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _install_root()


def _validate_embedded_runtime(runtime_dir: Path) -> tuple[bool, str]:
    """Valida a integridade física e arquivos fundamentais do runtime Embedded."""
    py = runtime_dir / "python.exe"
    if not py.is_file():
        return False, f"Interpretador python.exe ausente em {runtime_dir}"

    pth_files = list(runtime_dir.glob("python*._pth"))
    if not pth_files:
        return False, f"Arquivo de caminhos (._pth) ausente em {runtime_dir}"

    site_pkgs = runtime_dir / "Lib" / "site-packages"
    if not site_pkgs.is_dir():
        return False, f"Diretório Lib/site-packages ausente em {runtime_dir}"

    manifest_file = runtime_dir / "RUNTIME_INFO.json"
    if not manifest_file.is_file():
        return False, f"Manifesto RUNTIME_INFO.json ausente em {runtime_dir}"

    for dll in ("python3.dll", "vcruntime140.dll"):
        if not (runtime_dir / dll).is_file():
            return False, f"DLL essencial ausente ({dll}) em {runtime_dir}"

    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not data.get("python_version"):
            return False, "Manifesto corrompido: campo python_version ausente"
    except Exception as e:
        return False, f"Falha ao validar manifesto: {e}"

    return True, "OK"


def _load_manifest(runtime_dir: Path) -> dict:
    manifest_file = runtime_dir / "RUNTIME_INFO.json"
    if manifest_file.is_file():
        try:
            return json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _resolve_python(root: Path | None = None) -> tuple[Path | None, Path | None, str, Path | None, dict]:
    """Localiza o interpretador Python apropriado priorizando o runtime embarcado.
    
    Retorna: (python_exe, pythonw_exe, tipo, runtime_dir, metadados)
    Tipos: 'embedded', 'venv', 'corrupt', 'missing'
    """
    target_root = root or ROOT

    primary = target_root / "runtime" / "python"
    secondary = target_root / "build" / "runtime" / "python"

    is_installed = os.environ.get("ULTRON_INSTALLED") == "1" or getattr(sys, "frozen", False)
    is_dev = ((target_root / ".git").is_dir() or os.environ.get("ULTRON_DEV") == "1") and not is_installed

    # 1. Runtime Oficial de Produção (Python 3.14.10 Embedded)
    if primary.is_dir():
        # Tentar recuperação segura de estado incompleto se houver backup
        try:
            tools_dir = target_root / "tools"
            if tools_dir.is_dir() and str(tools_dir) not in sys.path:
                sys.path.insert(0, str(tools_dir))
            from build_python_runtime import recover_incomplete_state
            recover_incomplete_state(primary)
        except Exception:
            pass

        valid, reason = _validate_embedded_runtime(primary)
        if valid:
            py = primary / "python.exe"
            pyw = primary / "pythonw.exe"
            manifest = _load_manifest(primary)
            manifest["source"] = "primary"
            return py, (pyw if pyw.is_file() else py), "embedded", primary, manifest
        else:
            return None, None, "corrupt", primary, {"error": reason}

    # 2. Runtime Secundário (build/runtime/python): Contingência técnica manual.
    # NUNCA selecionado automaticamente em produção para contornar falha do runtime oficial.
    allow_secondary = os.environ.get("ULTRON_ALLOW_SECONDARY_RUNTIME") == "1" or (is_dev and not primary.exists())
    if allow_secondary and secondary.is_dir():
        valid_sec, reason_sec = _validate_embedded_runtime(secondary)
        if valid_sec:
            py = secondary / "python.exe"
            pyw = secondary / "pythonw.exe"
            manifest = _load_manifest(secondary)
            manifest["source"] = "secondary"
            manifest["contingency"] = True
            return py, (pyw if pyw.is_file() else py), "embedded", secondary, manifest

    # 3. Fallback de desenvolvimento (somente quando for ambiente de dev e NÃO for produção instalada)
    if is_dev:
        for pasta in ("venv", ".venv"):
            candidate = target_root / pasta / "Scripts"
            py = candidate / "python.exe"
            pyw = candidate / "pythonw.exe"
            if py.is_file():
                return py, (pyw if pyw.is_file() else py), "venv", target_root / pasta, {"version": "venv"}

    return None, None, "missing", None, {"error": "Runtime oficial Python 3.14.10 ausente"}


PYTHON_EXE, PYTHONW_EXE, RUNTIME_TYPE, RUNTIME_DIR, RUNTIME_META = _resolve_python()


def _build_isolated_env(runtime_dir: Path | None = None) -> dict[str, str]:
    """Gera ambiente estritamente isolado contra contaminações de Python global ou AppData."""
    required_environment = {
        "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "PROGRAMDATA", "COMSPEC", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    }
    isolated = {k: v for k, v in os.environ.items() if k.upper() in required_environment}
    isolated["PYTHONNOUSERSITE"] = "1"
    isolated["OPENBLAS_NUM_THREADS"] = "1"

    isolated.pop("PYTHONPATH", None)
    isolated.pop("PYTHONHOME", None)

    sys32 = os.environ.get("SYSTEMROOT", r"C:\Windows") + r"\System32"
    windir = os.environ.get("SYSTEMROOT", r"C:\Windows")
    path_entries = []
    if runtime_dir:
        path_entries.append(str(runtime_dir))
        scripts = runtime_dir / "Scripts"
        if scripts.is_dir():
            path_entries.append(str(scripts))
    path_entries.extend([sys32, windir])
    isolated["PATH"] = os.pathsep.join(path_entries)

    return isolated


def _show_error(message: str) -> None:
    if sys.stderr is not None and sys.stderr.isatty():
        print(f"{APP_NAME}: {message}", file=sys.stderr)
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, message, APP_NAME,
            0x00000010 | 0x00040000,  # MB_ICONERROR | MB_TOPMOST
        )
    except Exception:
        pass


def _show_info(message: str) -> None:
    if sys.stderr is not None and sys.stderr.isatty():
        print(f"{APP_NAME}: {message}")
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x00000040 | 0x00040000)
    except Exception:
        pass


def _installed() -> bool:
    return PYTHON_EXE is not None and PYTHON_EXE.is_file() and (ROOT / "desktop.py").is_file()


def _runtime_corrupt_message(reason: str) -> None:
    target_str = str(RUNTIME_DIR) if RUNTIME_DIR else "runtime/python"
    msg = (
        f"{APP_NAME} — Erro de Integridade no Interpretador\n\n"
        f"O runtime Python embarcado em {target_str} está corrompido ou incompleto:\n"
        f"• {reason}\n\n"
        "Execute o instalador oficial do ULTRON para restaurar a integridade dos arquivos."
    )
    _show_error(msg)


def _needs_setup_message() -> None:
    setup = ROOT / "ULTRON-Setup.exe"
    hint = (
        "O ULTRON ainda não está instalado nesta pasta.\n\n"
        f"Execute o instalador: {setup.name if setup.is_file() else 'o instalador oficial'}\n"
        "Ele instala o Python embarcado e as dependências — não requer ferramentas globais."
    )
    _show_error(hint)


def _spawn(arguments: list[str], *, hidden: bool) -> int:
    python = PYTHONW_EXE if hidden and PYTHONW_EXE and PYTHONW_EXE.is_file() else PYTHON_EXE
    if not python:
        raise RuntimeError("Interpretador Python não disponível para spawn.")
    flags = 0x00000008 if hidden else 0  # DETACHED_PROCESS: the panel outlives the launcher
    if hidden:
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(python), *arguments],
        cwd=str(ROOT),
        close_fds=True,
        creationflags=flags,
        env=_build_isolated_env(RUNTIME_DIR),
    )
    return process.pid


def _wait_for_api(timeout_seconds: float = 8.0) -> bool:
    """Panel is ready when the loopback API answers; keeps the launch feeling instant."""
    import socket
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.4)
            try:
                probe.connect(("127.0.0.1", 3900))
                return True
            except OSError:
                time.sleep(0.25)
    return False


def _doctor(root: Path | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"{APP_NAME} — diagnóstico local\n{'-' * 46}")

    target_root = root or ROOT
    py_exe, _pyw_exe, rt_type, rt_dir, rt_meta = _resolve_python(target_root)

    rt_desc = "Não encontrado"
    if rt_type == "embedded" and rt_dir:
        ver = rt_meta.get("python_version", "desconhecida")
        if rt_meta.get("contingency") or rt_meta.get("fallback"):
            rt_desc = f"Python {ver} Embedded ({rt_dir.name} - CONTINGÊNCIA SECUNDÁRIA)"
        else:
            rt_desc = f"Python {ver} Embedded ({rt_dir.name})"
    elif rt_type == "venv":
        rt_desc = "vEnv de desenvolvimento"
    elif rt_type == "corrupt":
        rt_desc = f"Corrompido ({rt_meta.get('error')})"

    el_prod1 = target_root / "electron" / "win-unpacked" / "U.L.T.R.O.N. Desktop.exe"
    el_prod2 = target_root / "electron" / "dist" / "win-unpacked" / "U.L.T.R.O.N. Desktop.exe"
    el_dev = target_root / "electron" / "node_modules" / "electron" / "dist" / "electron.exe"

    if el_prod1.is_file() or el_prod2.is_file():
        el_ok = True
        el_desc = "produção (win-unpacked)"
    elif el_dev.is_file():
        el_ok = True
        el_desc = "desenvolvimento (node_modules)"
    else:
        el_ok = False
        el_desc = "Não encontrado"

    checks = [
        ("Python seguro", py_exe is not None and py_exe.is_file(), rt_desc),
        ("desktop.py", (target_root / "desktop.py").is_file(), "ponto de entrada"),
        ("Electron", el_ok, el_desc),
        (".env", (target_root / ".env").is_file() or (target_root / "config" / ".env").is_file() or (Path(os.environ.get("APPDATA", "")) / "ULTRON" / ".env").is_file(), "chaves de IA"),
        ("Dados", (target_root / "dados" / "ultron.db").is_file() or (Path(os.environ.get("LOCALAPPDATA", "")) / "ULTRON" / "ultron.db").is_file(), "memória e histórico"),
    ]
    failures = 0
    for title, passed, detail in checks:
        print(f"  {'OK ' if passed else 'XX '} {title:<16} {detail}")
        failures += 0 if passed else 1
    if py_exe and py_exe.is_file():
        try:
            probe = subprocess.run([str(py_exe), "-c", "import config, cerebro, seguranca"],
                                   cwd=str(target_root), env=_build_isolated_env(rt_dir),
                                   capture_output=True, text=True)
            print(f"  {'OK ' if probe.returncode == 0 else 'XX '} {'núcleo':<16} config, cerebro, seguranca")
            if probe.returncode != 0:
                failures += 1
                print(probe.stderr.strip()[-800:])
        except OSError as e:
            failures += 1
            print(f"  XX  {'núcleo':<16} falha ao executar ({type(e).__name__})")
    print("-" * 46)
    print("Diagnóstico concluído." if failures == 0 else f"{failures} problema(s) encontrado(s).")
    return 0 if failures == 0 else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] in {"--doctor", "--diagnostico", "-d"}:
        return _doctor()
    if not _installed():
        if RUNTIME_TYPE == "corrupt":
            _runtime_corrupt_message(RUNTIME_META.get("error", "Arquivos inválidos"))
        elif os.name == "nt":
            _needs_setup_message()
        return 1
    env = _build_isolated_env(RUNTIME_DIR)
    if argv and argv[0] in {"--texto"}:
        return subprocess.call([str(PYTHON_EXE), str(ROOT / "main.py"), "--texto"], cwd=str(ROOT), env=env)
    if argv and argv[0] in {"--bandeja"}:
        return subprocess.call([str(PYTHON_EXE), str(ROOT / "main.py"), "--bandeja"], cwd=str(ROOT), env=env)
    if argv and argv[0] in {"--instalar-inicio", "--remover-inicio"}:
        return subprocess.call([str(PYTHON_EXE), str(ROOT / "desktop.py"), argv[0]], cwd=str(ROOT), env=env)
    _spawn([str(ROOT / "desktop.py")], hidden=True)
    if not _wait_for_api() and sys.stderr is not None and sys.stderr.isatty():
        print("O painel está demorando para responder; veja logs\\ultron.log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
