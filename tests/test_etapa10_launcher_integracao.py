"""Testes de integração do launcher e do Python 3.14.10 Embedded ao runtime de produção.

Etapa 10.3: Integração do Python 3.14.10 Embedded ao Runtime de Produção.
Valida:
1. Localização e validação de integridade do runtime de produção (runtime/python).
2. Isolamento estrito de ambiente (PYTHONNOUSERSITE=1, sem PYTHONPATH/PYTHONHOME).
3. Resiliência e detecção de erros em caso de runtime ausente, incompleto ou DLL faltando.
4. Recuperação automática de estado incompleto ou backup pendente.
5. Execução do comando de diagnóstico `launcher.py --doctor`.
6. Comunicação autenticada da API local loopback com token seguro (X-ULTRON-Token).
7. Preservação dos diretórios de dados desacoplados (%LOCALAPPDATA% / %APPDATA%).
8. Encerramento gracioso do servidor de API e DesktopRuntime.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT_DIR / "runtime" / "python"
PYTHON_EXE = RUNTIME_DIR / "python.exe"
LAUNCHER_PY = ROOT_DIR / "launcher.py"


@pytest.fixture(scope="session", autouse=True)
def garantir_runtime_producao_314() -> None:
    """Garante que o runtime de produção em runtime/python exista antes dos testes."""
    if not PYTHON_EXE.exists():
        if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
            pytest.skip("Runtime de produção em runtime/python não está disponível no ambiente de CI.")
        pytest.fail(f"Runtime de produção Python 3.14 não encontrado em {RUNTIME_DIR}.")


def test_01_launcher_localiza_e_valida_runtime_producao() -> None:
    """Valida que o launcher resolve runtime/python como 'embedded' de forma íntegra."""
    sys.path.insert(0, str(ROOT_DIR))
    import launcher

    py, pyw, r_type, r_dir, r_meta = launcher._resolve_python()
    assert r_type == "embedded", f"Tipo de runtime inesperado: {r_type}"
    assert py is not None and py.is_file(), "python.exe do launcher não é válido"
    assert pyw is not None and pyw.is_file(), "pythonw.exe do launcher não é válido"
    assert r_dir == RUNTIME_DIR, f"Diretório inesperado: {r_dir}"
    assert r_meta.get("python_version") == "3.14.10", f"Versão incorreta no manifesto: {r_meta}"
    assert r_meta.get("architecture") == "AMD64"


def test_02_launcher_isolamento_ambiente() -> None:
    """Valida as variáveis de ambiente estritamente isoladas contra contaminação externa."""
    import launcher

    env = launcher._build_isolated_env(RUNTIME_DIR)

    assert env.get("PYTHONNOUSERSITE") == "1", "PYTHONNOUSERSITE deve ser 1"
    assert env.get("OPENBLAS_NUM_THREADS") == "1"
    assert "PYTHONPATH" not in env, "PYTHONPATH externo não pode ser herdado"
    assert "PYTHONHOME" not in env, "PYTHONHOME externo não pode ser herdado"

    path_str = env.get("PATH", "")
    assert str(RUNTIME_DIR) in path_str, "runtime/python deve estar no PATH isolado"
    assert "system32" in path_str.lower(), "System32 deve estar presente no PATH"


def test_03_launcher_falha_quando_runtime_incompleto(tmp_path: Path) -> None:
    """Valida que falhas estruturais no runtime são detectadas sem fallback silencioso."""
    import launcher

    fake_rt = tmp_path / "fake_incomplete_runtime"
    fake_rt.mkdir()

    # Cenário 1: Sem python.exe
    valid, reason = launcher._validate_embedded_runtime(fake_rt)
    assert not valid
    assert "python.exe ausente" in reason

    # Cenário 2: Com python.exe mas sem ._pth
    (fake_rt / "python.exe").write_text("dummy", encoding="utf-8")
    valid, reason = launcher._validate_embedded_runtime(fake_rt)
    assert not valid
    assert "._pth" in reason

    # Cenário 3: Com ._pth mas sem site-packages
    (fake_rt / "python314._pth").write_text("Lib\n", encoding="utf-8")
    valid, reason = launcher._validate_embedded_runtime(fake_rt)
    assert not valid
    assert "site-packages" in reason

    # Cenário 4: Com site-packages mas sem manifesto
    (fake_rt / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    valid, reason = launcher._validate_embedded_runtime(fake_rt)
    assert not valid
    assert "RUNTIME_INFO.json" in reason

    # Cenário 5: Sem DLLs essenciais
    (fake_rt / "RUNTIME_INFO.json").write_text(json.dumps({"python_version": "3.14.10"}), encoding="utf-8")
    valid, reason = launcher._validate_embedded_runtime(fake_rt)
    assert not valid
    assert "DLL essencial ausente" in reason


def test_04_launcher_recupera_backup_se_alvo_interrompido(tmp_path: Path) -> None:
    """Valida que o launcher aciona a recuperação automática caso o runtime esteja em backup."""
    from unittest.mock import patch
    import launcher

    fake_target = tmp_path / "python"
    fake_backup = tmp_path / "python.backup_12345"
    fake_backup.mkdir()
    (fake_backup / "python.exe").write_text("dummy_py", encoding="utf-8")
    (fake_backup / "marker.txt").write_text("backup_ok", encoding="utf-8")

    with patch.object(launcher, "ROOT", tmp_path):
        sys.path.insert(0, str(ROOT_DIR / "tools"))
        from build_python_runtime import recover_incomplete_state
        recovered = recover_incomplete_state(fake_target)
        assert recovered is True
        assert fake_target.exists()
        assert (fake_target / "marker.txt").read_text(encoding="utf-8") == "backup_ok"
        assert not fake_backup.exists(), "Backup orfão deveria ter sido removido após restauração"


def test_05_launcher_doctor_executa_e_valida_nucleo() -> None:
    """Executa o comando launcher.py --doctor e verifica que todos os checks retornam OK."""
    res = subprocess.run([str(PYTHON_EXE), str(LAUNCHER_PY), "--doctor"],
                         cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_txt = res.stdout.decode("utf-8", errors="replace")
    assert res.returncode == 0, f"Doctor falhou com exit {res.returncode}:\n{stdout_txt}"
    assert "Python 3.14.10 Embedded" in stdout_txt
    assert "Diagnóstico concluído." in stdout_txt
    assert "0 problema(s) encontrado(s)." in stdout_txt or "OK  núcleo" in stdout_txt


def test_06_integracao_api_local_loopback_e_token() -> None:
    """Valida que o servidor HTTP local responde no loopback e exige o token X-ULTRON-Token."""
    import urllib.request
    import urllib.error
    import secrets
    from desktop_api import create_server

    class MockRuntime:
        def health(self):
            return {"status": "ok", "versao": "2.1.0"}
        def status(self):
            return {"status": "ok"}

    runtime = MockRuntime()
    token = secrets.token_urlsafe(32)
    server, api_url = create_server(runtime, token)

    import threading
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        # 1. Requisição sem token -> deve retornar 401 Unauthorized
        req_sem_token = urllib.request.Request(f"{api_url}/api/v1/health")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_sem_token, timeout=3.0)
        assert exc_info.value.code == 401

        # 2. Requisição com token X-ULTRON-Token válido -> deve retornar 200 OK
        req_com_token = urllib.request.Request(f"{api_url}/api/v1/health")
        req_com_token.add_header("X-ULTRON-Token", token)
        with urllib.request.urlopen(req_com_token, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("ok") is True
            assert "version" in data
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2.0)


def test_07_integracao_preservacao_diretorios_dados() -> None:
    """Valida que os diretórios desacoplados em config.py apontam para o perfil do usuário em produção."""
    import config

    old_env = os.environ.copy()
    try:
        os.environ["ULTRON_INSTALLED"] = "1"
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        os.environ.pop("ULTRON_DEV", None)
        caminhos = config.reconfigurar_diretorios()

        assert "ULTRON" in str(caminhos["dados"])
        assert "ULTRON" in str(caminhos["config"])
        assert config.ARQUIVO_BANCO.parent == caminhos["dados"]
        assert config.ARQUIVO_COFRE.parent == caminhos["dados"]
        assert config.ARQUIVO_ENV.parent == caminhos["config"]
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        config.reconfigurar_diretorios()


def test_08_integracao_desktop_runtime_sob_python_embedded() -> None:
    """Executa DesktopRuntime e ciclo de vida completo diretamente sob o runtime Python 3.14 Embedded."""
    test_code = """
import sys, threading, time
from pathlib import Path
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

import config
from desktop_runtime import DesktopRuntime

stop_evt = threading.Event()
runtime = DesktopRuntime(start_voice=False, stop_event=stop_evt)
runtime.start()
assert runtime._started is True, "DesktopRuntime nao iniciou"

runtime.set_api_running(True)
assert runtime._api_running is True

# Testar chamada de rotinas do runtime
snapshot = runtime.get_snapshot()
assert isinstance(snapshot, dict)
assert snapshot["core_running"] is True
assert snapshot["api_running"] is True

# Desligamento gracioso
runtime.shutdown()
assert runtime._started is False, "DesktopRuntime nao encerrou graciosamente"
print("SUCESSO: DesktopRuntime ciclo de vida concluido sob Python 3.14")
"""
    res = subprocess.run([str(PYTHON_EXE), "-c", test_code],
                         cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_txt = res.stdout.decode("utf-8", errors="replace")
    stderr_txt = res.stderr.decode("utf-8", errors="replace")
    assert res.returncode == 0, f"Falha no DesktopRuntime sob Python 3.14:\nSTDOUT: {stdout_txt}\nSTDERR: {stderr_txt}"
    assert "SUCESSO: DesktopRuntime ciclo de vida concluido" in stdout_txt
