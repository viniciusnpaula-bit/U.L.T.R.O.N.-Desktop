"""Testes de isolamento e validação do Python 3.12 Embedded.

Etapa 10.2: Construção Automatizada do Python 3.12 Embedded (64 bits).
Valida:
1. Inicialização do python.exe embedded e versão 3.12.9 (64 bits).
2. Configuração estrita de python312._pth com carregamento de site e site-packages.
3. Importação das extensões nativas C/C++/Rust: NumPy, OpenCV, Pygame-CE, Cryptography, sounddevice, psutil.
4. Importação e funcionalidade de WinRT (Security & Credentials UI).
5. Importação e funcionalidade dos módulos centrais do U.L.T.R.O.N. Desktop.
6. Acesso aos diretórios de dados desacoplados (config.DIR_DADOS e DIR_CONFIG).
7. Execução a partir de diretório de trabalho arbitrário.
8. Isolamento de PATH: execução sem nenhum Python global, .venv, venv, Node ou Git no PATH.
9. Integridade e validade do manifesto RUNTIME_INFO.json.
10. Verificação do comando --check do script gerador.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT_DIR / "build" / "runtime" / "python"
PYTHON_EXE = RUNTIME_DIR / "python.exe"
MANIFEST_FILE = RUNTIME_DIR / "RUNTIME_INFO.json"


@pytest.fixture(scope="session", autouse=True)
def garantir_runtime_construido() -> None:
    """Garante que o runtime Python Embedded exista antes de rodar os testes."""
    if not PYTHON_EXE.exists() or not MANIFEST_FILE.exists():
        if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
            pytest.skip(f"Runtime Python Embedded local ausente no CI: {RUNTIME_DIR}")
        pytest.fail(
            f"Runtime Python Embedded não encontrado em {RUNTIME_DIR}. "
            "Execute 'python tools/build_python_runtime.py' primeiro."
        )


def _exec_embedded(
    code_or_args: str | list[str],
    *,
    cwd: Path | str | None = None,
    extra_env: dict[str, str] | None = None,
    clean_path: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Utilitário para executar o interpretador embedded de forma controlada."""
    env = os.environ.copy()
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    if clean_path:
        # Remove do PATH qualquer referência a Python, venv, node, npm, git
        raw_path = env.get("PATH", "")
        clean_dirs = [
            part for part in raw_path.split(os.pathsep)
            if not any(
                forbidden in part.lower()
                for forbidden in ("python", "venv", ".venv", "node", "npm", "git")
            )
        ]
        # Garante pastas básicas essenciais do Windows
        system_root = env.get("SystemRoot", r"C:\Windows")
        clean_dirs.extend([
            str(Path(system_root) / "System32"),
            str(Path(system_root)),
            str(Path(system_root) / "System32" / "Wbem"),
        ])
        env["PATH"] = os.pathsep.join(clean_dirs)
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        env.pop("VIRTUAL_ENV", None)

    if extra_env:
        env.update(extra_env)

    if isinstance(code_or_args, str):
        cmd = [str(PYTHON_EXE), "-c", code_or_args]
    else:
        cmd = [str(PYTHON_EXE)] + code_or_args

    res = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Decodifica de forma segura no Windows (env já força PYTHONUTF8=1 / PYTHONIOENCODING=utf-8)
    res.stdout = res.stdout.decode("utf-8", errors="replace")  # type: ignore[assignment]
    res.stderr = res.stderr.decode("utf-8", errors="replace")  # type: ignore[assignment]
    return res


def test_01_binario_python_embedded_existe_e_versao() -> None:
    assert PYTHON_EXE.is_file(), f"python.exe não existe em {PYTHON_EXE}"
    res = _exec_embedded(["--version"])
    assert res.returncode == 0, f"Falha ao executar python.exe --version: {res.stderr}"
    assert "3.12.9" in res.stdout, f"Versão esperada 3.12.9, obtida: {res.stdout}"


def test_02_arquitetura_e_bitness_64bit() -> None:
    code = (
        "import sys, platform; "
        "arch = platform.architecture()[0]; "
        "is64 = sys.maxsize > 2**32; "
        "print(f'{arch},{is64}')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro: {res.stderr}"
    arch, is64 = res.stdout.strip().split(",")
    assert arch == "64bit", f"Esperado 64bit, obtido: {arch}"
    assert is64 == "True", f"Esperado True para 64-bit, obtido: {is64}"


def test_03_configuracao_pth_e_site() -> None:
    pth_file = RUNTIME_DIR / "python312._pth"
    assert pth_file.is_file(), "python312._pth não encontrado"
    content = pth_file.read_text(encoding="utf-8")

    assert "Lib" in content, "Lib ausente em python312._pth"
    assert "Lib/site-packages" in content, "Lib/site-packages ausente em python312._pth"
    assert "import site" in content, "import site ausente em python312._pth"

    # Testa que o módulo site é importável e tem caminhos válidos
    code = (
        "import site, sys; "
        "paths = sys.path; "
        "has_site_pkgs = any('site-packages' in p for p in paths); "
        "print(f'{has_site_pkgs}')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro: {res.stderr}"
    assert "True" in res.stdout, f"site-packages não encontrado em sys.path: {res.stdout}"


def test_04_importacao_biblioteca_padrao_nativa() -> None:
    code = (
        "import sqlite3, ssl, ctypes, asyncio, hashlib, _overlapped, _wmi; "
        "print('STDLIB_NATIVE_OK')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro ao importar stdlib nativa: {res.stderr}"
    assert "STDLIB_NATIVE_OK" in res.stdout


def test_05_importacao_audio_e_midia() -> None:
    code = (
        "import sounddevice as sd; "
        "import pygame; "
        "import pyttsx3; "
        "import edge_tts; "
        "import speech_recognition as sr; "
        "print('AUDIO_MEDIA_OK')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro ao importar áudio e mídia: {res.stderr}"
    assert "AUDIO_MEDIA_OK" in res.stdout


def test_06_importacao_visao_computacional_e_numpy() -> None:
    code = (
        "import numpy as np; "
        "import cv2; "
        "mat = np.zeros((10, 10, 3), dtype=np.uint8); "
        "gray = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY); "
        "print(f'CV2_NUMPY_OK:{gray.shape}')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro ao testar OpenCV/NumPy: {res.stderr}"
    assert "CV2_NUMPY_OK:(10, 10)" in res.stdout


def test_07_importacao_winrt_e_credenciais() -> None:
    code = (
        "import winrt.windows.security.credentials.ui as cui; "
        "has_verifier = hasattr(cui, 'UserConsentVerifier'); "
        "print(f'WINRT_OK:{has_verifier}')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro ao importar WinRT: {res.stderr}"
    assert "WINRT_OK:True" in res.stdout


def test_08_importacao_criptografia_e_seguranca() -> None:
    code = (
        "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; "
        "key = AESGCM.generate_key(bit_length=256); "
        "aesgcm = AESGCM(key); "
        "nonce = b'123456789012'; "
        "ct = aesgcm.encrypt(nonce, b'teste_secreto', None); "
        "pt = aesgcm.decrypt(nonce, ct, None); "
        "import psutil, pystray, send2trash; "
        "print(f'CRYPTO_SECURITY_OK:{pt.decode()}')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro ao testar criptografia/segurança: {res.stderr}"
    assert "CRYPTO_SECURITY_OK:teste_secreto" in res.stdout


def test_09_importacao_nucleo_ultron() -> None:
    code = (
        f"import sys; sys.path.insert(0, r'{ROOT_DIR}'); "
        "import config, seguranca, memoria, cofre, cerebro, desktop_api, desktop_runtime; "
        "print('CORE_ULTRON_OK')"
    )
    res = _exec_embedded(code)
    assert res.returncode == 0, f"Erro ao importar núcleo U.L.T.R.O.N.: {res.stderr}"
    assert "CORE_ULTRON_OK" in res.stdout


def test_10_acesso_dados_usuario_e_modo_config(tmp_path: Path) -> None:
    fake_local = tmp_path / "localappdata"
    fake_roaming = tmp_path / "appdata"
    fake_local.mkdir()
    fake_roaming.mkdir()

    code = (
        f"import sys; sys.path.insert(0, r'{ROOT_DIR}'); "
        "import os, config, sqlite3; "
        "config.reconfigurar_diretorios(); "
        "db_path = config.ARQUIVO_BANCO; "
        "db_path.parent.mkdir(parents=True, exist_ok=True); "
        "conn = sqlite3.connect(str(db_path)); "
        "conn.execute('CREATE TABLE IF NOT EXISTS t (id INT);'); "
        "conn.commit(); "
        "conn.close(); "
        "print(f'DATA_ACCESS_OK:{db_path.exists()}')"
    )
    extra_env = {
        "ULTRON_INSTALLED": "1",
        "ULTRON_DEV": "",
        "ULTRON_PORTABLE": "",
        "LOCALAPPDATA": str(fake_local),
        "APPDATA": str(fake_roaming),
    }
    res = _exec_embedded(code, extra_env=extra_env)
    assert res.returncode == 0, f"Erro no teste de acesso a dados: {res.stderr}"
    assert "DATA_ACCESS_OK:True" in res.stdout
    assert (fake_local / "ULTRON" / "ultron.db").exists()


def test_11_execucao_com_working_dir_arbitrario(tmp_path: Path) -> None:
    arbitrary_cwd = tmp_path / "somewhere_else"
    arbitrary_cwd.mkdir()

    code = (
        f"import sys; sys.path.insert(0, r'{ROOT_DIR}'); "
        "import os, config; "
        "cwd = os.getcwd(); "
        "print(f'CWD_OK:{cwd}')"
    )
    res = _exec_embedded(code, cwd=arbitrary_cwd)
    assert res.returncode == 0, f"Erro ao rodar em diretório arbitrário: {res.stderr}"
    assert "CWD_OK:" in res.stdout
    assert str(arbitrary_cwd.resolve()).lower() in res.stdout.lower()


def test_12_isolamento_sem_python_global_no_path() -> None:
    """Valida execução estritamente autônoma, com PATH sanitizado (sem Python global, sem venv, sem Node, sem Git)."""
    code = (
        "import os, sys, cv2, numpy, sounddevice, pygame, winrt, cryptography; "
        "path = os.environ.get('PATH', ''); "
        "print(f'STANDALONE_SUCCESS:{len(path)}') "
    )
    res = _exec_embedded(code, clean_path=True)
    assert res.returncode == 0, (
        f"Falha de execução com PATH sanitizado (sem Python global):\n"
        f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    )
    assert "STANDALONE_SUCCESS" in res.stdout


def test_13_manifesto_runtime_info_valido() -> None:
    assert MANIFEST_FILE.is_file(), f"Manifesto {MANIFEST_FILE} não encontrado"
    data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

    assert data.get("python_version") == "3.12.9"
    assert data.get("architecture") == "AMD64"
    assert data.get("bitness") == 64
    assert data.get("size_mb", 0) > 100
    assert data.get("installed_packages_count", 0) >= 30

    # Valida presença de pacotes críticos no manifesto
    pkgs = data.get("installed_packages", {})
    for expected in ["numpy", "pygame-ce", "opencv-python-headless", "cryptography", "sounddevice", "psutil"]:
        # Busca sem case
        found = any(k.lower() == expected.lower() for k in pkgs.keys())
        assert found, f"Pacote crítico '{expected}' ausente no manifesto"


def test_14_repetibilidade_e_verificacao_check() -> None:
    builder_script = ROOT_DIR / "tools" / "build_python_runtime.py"
    assert builder_script.is_file()

    # Executa com flag --check
    cmd = [sys.executable, str(builder_script), "--check", "--output-dir", str(RUNTIME_DIR)]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_txt = res.stdout.decode("utf-8", errors="replace")
    stderr_txt = res.stderr.decode("utf-8", errors="replace")

    assert res.returncode == 0, f"Falha na verificação --check do runtime:\n{stdout_txt}\n{stderr_txt}"
    assert "3.12.9" in stdout_txt
    assert "407" in stdout_txt or "MB" in stdout_txt


def test_15_interrupcao_e_rollback_na_substituicao_atomica(tmp_path: Path) -> None:
    """Valida que em caso de interrupção ou erro durante o swap do runtime, o runtime anterior é restaurado."""
    import shutil
    from unittest.mock import patch
    sys.path.insert(0, str(ROOT_DIR / "tools"))
    from build_python_runtime import safe_atomic_replace

    target = tmp_path / "target_runtime"
    target.mkdir()
    (target / "python.exe").write_text("orig_py", encoding="utf-8")
    (target / "marker.txt").write_text("versao_anterior", encoding="utf-8")

    staging = tmp_path / "staging_runtime"
    staging.mkdir()
    (staging / "python.exe").write_text("new_py", encoding="utf-8")
    (staging / "marker.txt").write_text("versao_nova", encoding="utf-8")

    # Simula falha ao promover o staging para target
    original_move = shutil.move
    def fake_move(src, dst):
        if str(src) == str(staging) and str(dst) == str(target):
            raise OSError("Simulacao de falha de I/O / interrupcao durante substituicao")
        return original_move(src, dst)

    with patch("shutil.move", side_effect=fake_move):
        with pytest.raises(OSError, match="Simulacao de falha"):
            safe_atomic_replace(staging, target)

    # Verifica que o rollback recuperou a versao anterior
    assert target.exists(), "Target runtime deveria ter sido restaurado pelo rollback"
    assert (target / "marker.txt").read_text(encoding="utf-8") == "versao_anterior"

    # Agora valida substituição normal sem falhas
    safe_atomic_replace(staging, target)
    assert target.exists()
    assert (target / "marker.txt").read_text(encoding="utf-8") == "versao_nova"


def test_16_lockfile_versionado_oficial_existe_e_integro() -> None:
    """Valida que tools/requirements-lock-win-py312.txt existe e contém hashes de pacotes essenciais."""
    lockfile = ROOT_DIR / "tools" / "requirements-lock-win-py312.txt"
    assert lockfile.is_file(), f"Lockfile oficial {lockfile} não encontrado"
    content = lockfile.read_text(encoding="utf-8")

    assert "--require-hashes" in content or "--hash=sha256:" in content
    assert "numpy==" in content
    assert "opencv-python-headless==" in content
    assert "pygame-ce==" in content
    assert "cryptography==" in content
    assert "sounddevice==" in content
    assert "winrt-runtime==" in content


def test_17_resiliencia_interrupcao_cinco_momentos(tmp_path: Path) -> None:
    """Valida recuperação e resiliência em 5 momentos críticos de interrupção abrupta do swap."""
    sys.path.insert(0, str(ROOT_DIR / "tools"))
    from build_python_runtime import recover_incomplete_state, safe_atomic_replace

    worker_code = """
import sys, os, shutil
from pathlib import Path

moment = int(sys.argv[1])
base_dir = Path(sys.argv[2])
target = base_dir / "target_runtime"
staging = base_dir / "staging_runtime"
backup = base_dir / "target_runtime.backup_99999"

if moment == 1:
    # 1. Antes de renomear o runtime antigo: encerramento abrupto imediato
    os._exit(101)

elif moment == 2:
    # 2. Depois de renomear o runtime antigo para backup: encerramento abrupto
    shutil.move(str(target), str(backup))
    os._exit(102)

elif moment == 3:
    # 3. Depois de iniciar promoção: backup existe e target fica incompleto/corrompido
    shutil.move(str(target), str(backup))
    target.mkdir()
    (target / "corrupt_partial_file.tmp").write_text("incompleto", encoding="utf-8")
    os._exit(103)

elif moment == 4:
    # 4. Depois da promoção: novo target promovido, mas interrompido antes de limpar backup
    shutil.move(str(target), str(backup))
    shutil.move(str(staging), str(target))
    os._exit(104)

elif moment == 5:
    # 5. Durante limpeza do backup: target promovido, backup residual permanece
    shutil.move(str(target), str(backup))
    shutil.move(str(staging), str(target))
    backup.mkdir(exist_ok=True)
    (backup / "leftover.tmp").write_text("orfao", encoding="utf-8")
    os._exit(105)
"""
    worker_script = tmp_path / "worker.py"
    worker_script.write_text(worker_code, encoding="utf-8")

    for moment in [1, 2, 3, 4, 5]:
        env_dir = tmp_path / f"scenario_moment_{moment}"
        env_dir.mkdir(parents=True, exist_ok=True)
        target = env_dir / "target_runtime"
        staging = env_dir / "staging_runtime"

        target.mkdir()
        (target / "python.exe").write_text("orig_py", encoding="utf-8")
        (target / "version.txt").write_text("v1_original", encoding="utf-8")

        staging.mkdir()
        (staging / "python.exe").write_text("new_py", encoding="utf-8")
        (staging / "version.txt").write_text("v2_novo", encoding="utf-8")

        # Dispara subprocesso que sofrerá interrupção abrupta (exit code != 0)
        proc = subprocess.run([sys.executable, str(worker_script), str(moment), str(env_dir)])
        assert proc.returncode == 100 + moment, f"Subprocesso do momento {moment} não abortou com código esperado"

        # Executa recuperação pelo builder
        recovered = recover_incomplete_state(target)

        if moment in [1, 2, 3]:
            # Deve ter recuperado o runtime original v1
            assert target.exists(), f"Momento {moment}: target deveria existir após recuperação"
            assert (target / "version.txt").read_text(encoding="utf-8") == "v1_original"
        elif moment in [4, 5]:
            # Deve ter mantido o runtime promovido v2 e eliminado backups
            assert target.exists(), f"Momento {moment}: target promovido deveria existir"
            assert (target / "version.txt").read_text(encoding="utf-8") == "v2_novo"
            # Nenhum backup deve sobrar
            backups = list(env_dir.glob("target_runtime.backup_*"))
            assert len(backups) == 0, f"Momento {moment}: backups orfãos deveriam ter sido limpos: {backups}"


