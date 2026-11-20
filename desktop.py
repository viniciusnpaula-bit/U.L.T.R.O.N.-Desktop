"""Start the ULTRON core, protected local API, and Electron Desktop UI."""
from __future__ import annotations

import inspect
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path


def _aviso(onde: str, erro: BaseException) -> None:
    """Registra rótulo + tipo do erro; nunca o texto (pode conter chave ou caminho)."""
    try:
        import seguranca
        seguranca.log.warning(f"falha em {onde} ({type(erro).__name__})")
    except Exception:
        print(f"[aviso] falha em {onde} ({type(erro).__name__})")


def _show_error(title: str, message: str, *, info: bool = False) -> None:
    try:
        from tkinter import messagebox
        if info:
            messagebox.showinfo(title, message)
        else:
            messagebox.showerror(title, message)
    except Exception:
        print(f"{title}: {message}")


def _electron_paths(root: Path | None = None) -> tuple[Path, Path]:
    target_root = root or Path(__file__).resolve().parent
    package = target_root / "electron"

    # 1. Produção: Executável compilado em win-unpacked (prioridade)
    for prod_candidate in (
        package / "win-unpacked" / "U.L.T.R.O.N. Desktop.exe",
        package / "dist" / "win-unpacked" / "U.L.T.R.O.N. Desktop.exe",
    ):
        if prod_candidate.is_file():
            return prod_candidate, prod_candidate.parent

    # 2. Desenvolvimento: Fallback para electron em node_modules
    dev_candidate = package / "node_modules" / "electron" / "dist" / "electron.exe"
    return dev_candidate, package


def _launch_electron(executable: Path, app_dir: Path, api_url: str, token: str, root: Path) -> int:
    if not executable.is_file():
        raise FileNotFoundError("Electron não instalado. Execute ULTRON-Setup.exe para instalar o Desktop.")

    asar = executable.parent / "resources" / "app.asar"
    is_compiled = asar.is_file() or executable.name != "electron.exe"

    if not is_compiled and not all((app_dir / name).is_file() for name in ("package.json", "main.js", "site/index.html")):
        raise FileNotFoundError("Os arquivos do aplicativo Electron estão incompletos.")

    required_environment = {
        "PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "PROGRAMDATA", "ALLUSERSPROFILE", "HOMEDRIVE", "HOMEPATH",
        "PROGRAMFILES", "PROGRAMFILES(X86)",
    }
    child_env = {key: value for key, value in os.environ.items()
                 if key.upper() in required_environment}
    data_dir = os.environ.get("ULTRON_DATA_DIR", "").strip()
    if not data_dir:
        try:
            import config as _cfg
            if getattr(_cfg, "MODO_EXECUCAO", "") == "instalado" and getattr(_cfg, "DIR_DADOS", None):
                data_dir = str(Path(_cfg.DIR_DADOS).resolve())
        except Exception:
            data_dir = ""
    child_env.update(ULTRON_API_URL=api_url, ULTRON_API_TOKEN=token,
                     ULTRON_ROOT=str(Path(root).resolve()),
                     **({"ULTRON_DATA_DIR": data_dir} if data_dir else {}))

    if is_compiled:
        cmd = [str(executable)]
        cwd_dir = executable.parent
    else:
        cmd = [str(executable), str(app_dir)]
        cwd_dir = app_dir

    return subprocess.run(cmd, cwd=cwd_dir, env=child_env, check=False).returncode


def main() -> int:
    try:
        import config
    except Exception as erro:
        _aviso("config", erro)
        _show_error("ULTRON Desktop", "Não consegui carregar a configuração. Execute ULTRON-Setup.exe e tente novamente.")
        return 1

    if not any(config.CHAVES.values()):
        _show_error("ULTRON Desktop", "Nenhuma chave de IA configurada. Edite o .env (veja .env.example) e abra o ULTRON novamente.")
        return 1

    try:
        import main as core_main
        import seguranca
        import telegram_bot
        from desktop_api import create_server
        from desktop_runtime import DesktopRuntime
    except Exception as erro:
        _aviso("imports", erro)
        _show_error("ULTRON Desktop", "Faltam dependências do ULTRON. Execute ULTRON-Setup.exe e tente novamente.")
        return 1

    if not core_main.instancia_unica():
        _show_error("ULTRON Desktop", "O ULTRON já está em execução.", info=True)
        return 0

    runtime = None
    server = None
    server_thread = None
    mobile_server = None
    mobile_thread = None
    scheduler_thread = None
    scheduler_stop = threading.Event()
    server_started = False
    mobile_started = False
    closed = False
    close_lock = threading.Lock()

    def cleanup():
        nonlocal closed
        with close_lock:
            if closed:
                return
            closed = True
        scheduler_stop.set()
        if mobile_server is not None:
            if mobile_started:
                try:
                    mobile_server.shutdown()
                except Exception as erro:
                    _aviso("mobile_api.shutdown", erro)
            try:
                mobile_server.server_close()
            except Exception as erro:
                _aviso("mobile_api.server_close", erro)
        if mobile_thread is not None and mobile_thread is not threading.current_thread():
            mobile_thread.join(timeout=3)
        if runtime is not None and hasattr(runtime, "set_mobile_api_state"):
            try:
                runtime.set_mobile_api_state(False, None)
            except Exception:
                pass
        if server is not None:
            if server_started:
                try:
                    server.shutdown()
                except Exception as erro:
                    _aviso("api.shutdown", erro)
            try:
                server.server_close()
            except Exception as erro:
                _aviso("api.server_close", erro)
        if server_thread is not None and server_thread is not threading.current_thread():
            server_thread.join(timeout=3)
        if runtime is not None:
            try:
                runtime.set_api_running(False)
                runtime.shutdown()
            except Exception as erro:
                _aviso("runtime.shutdown", erro)
        if scheduler_thread is not None and scheduler_thread is not threading.current_thread():
            scheduler_thread.join(timeout=3)
        if hasattr(core_main, "remover_atalhos"):
            try:
                core_main.remover_atalhos()
            except Exception as erro:
                _aviso("core.remover_atalhos", erro)

    try:
        core_main.preparar_windows()
        core_main.atalho_parada()
        telegram_bot.iniciar()

        try:
            runtime_params = inspect.signature(DesktopRuntime).parameters
        except (TypeError, ValueError):
            runtime_params = ()
        runtime = DesktopRuntime(stop_event=scheduler_stop) if "stop_event" in runtime_params else DesktopRuntime()
        runtime.start()
        try:
            scheduler_params = inspect.signature(core_main.loop_lembretes).parameters
        except (TypeError, ValueError):
            scheduler_params = ()
        scheduler_kwargs = {"stop_event": scheduler_stop} if "stop_event" in scheduler_params else {}
        scheduler_thread = threading.Thread(
            target=core_main.loop_lembretes,
            kwargs=scheduler_kwargs,
            name="ultron-lembretes",
            daemon=True,
        )
        scheduler_thread.start()
        token = secrets.token_urlsafe(32)
        server, api_url = create_server(runtime, token)
        server_thread = threading.Thread(target=server.serve_forever,
                                         name="ultron-desktop-api", daemon=True)
        server_thread.start()
        server_started = True
        runtime.set_api_running(True)

        if getattr(config, "MOBILE_ENABLED", False):
            try:
                if hasattr(runtime, "ensure_mobile_server_running"):
                    runtime.ensure_mobile_server_running()
                else:
                    import mobile_api
                    import mobile_pairing
                    if mobile_pairing.tem_pareamento_ativo():
                        mobile_server, mobile_url = mobile_api.create_mobile_server(runtime)
                        mobile_thread = threading.Thread(
                            target=mobile_server.serve_forever,
                            name="ultron-mobile-api",
                            daemon=True,
                        )
                        mobile_thread.start()
                        mobile_started = True
                        if hasattr(runtime, "set_mobile_api_state"):
                            runtime.set_mobile_api_state(True, mobile_url)
            except Exception as erro:
                _aviso("mobile_api", erro)

        executable, ui_dir = _electron_paths()
        return _launch_electron(executable, ui_dir, api_url, token, config.BASE)
    except Exception as exc:
        try:
            seguranca.log.error(f"Inicialização do Desktop falhou ({type(exc).__name__}).")
        except Exception:
            pass
        _show_error("ULTRON Desktop", "Não consegui iniciar o painel local. Confira a instalação e logs\\ultron.log.")
        return 1
    finally:
        cleanup()


def _run_cli() -> int:
    args = sys.argv[1:]
    if args == ["--instalar-inicio"]:
        from desktop_autostart import install
        try:
            entry = install(None, Path(sys.executable).with_name("pythonw.exe"), Path(__file__).resolve())
        except Exception:
            print("Não consegui instalar o início automático. Verifique a pasta de inicialização do Windows.")
            return 1
        print(f"Início automático ativado: {entry}")
        return 0
    if args == ["--remover-inicio"]:
        from desktop_autostart import remove
        try:
            removed = remove(None)
        except Exception:
            print("Não consegui remover o início automático. Verifique a pasta de inicialização do Windows.")
            return 1
        print("Início automático removido." if removed else "O início automático não estava ativado.")
        return 0
    if args:
        print("Uso: desktop.py [--instalar-inicio|--remover-inicio]")
        return 2
    return main()


if __name__ == "__main__":
    raise SystemExit(_run_cli())
