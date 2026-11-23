"""
Suíte de Testes da Política Definitiva de Fallback dos Runtimes (Etapa 10.3.2).
Valida os 10 cenários obrigatórios estabelecidos pela decisão arquitetural:
1. Runtime principal válido (Python 3.14.10) selecionado normalmente.
2. Runtime principal ausente em produção interrompe e exige reinstalação.
3. Runtime principal corrompido interrompe sem mascaramento.
4. Runtime secundário presente, mas NÃO selecionado automaticamente em produção.
5. Ambos os runtimes inválidos interrompem a inicialização.
6. .venv presente em instalação de produção é recusado peremptoriamente.
7. .venv presente em desenvolvimento (.git) é aceito como fallback técnico.
8. Python global presente no sistema NUNCA é utilizado como fallback.
9. Diagnóstico (_doctor) exibe causa da interrupção em caso de falha.
10. Diagnóstico (_doctor) exibe fielmente a versão selecionada em sucesso.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import launcher


def _create_mock_embedded_runtime(dest_dir: Path, version: str = "3.14.10") -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "python.exe").write_bytes(b"MOCK_EXE")
    (dest_dir / "pythonw.exe").write_bytes(b"MOCK_PYW")
    (dest_dir / "python3.dll").write_bytes(b"MOCK_DLL")
    (dest_dir / "vcruntime140.dll").write_bytes(b"MOCK_VCRUNTIME")
    (dest_dir / "python314._pth").write_text("Lib\nLib\\site-packages\n.\nimport site\n", encoding="utf-8")
    (dest_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    manifest = {
        "python_version": version,
        "arch": "AMD64",
        "created_at": "2026-11-09T00:00:00Z"
    }
    (dest_dir / "RUNTIME_INFO.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_01_runtime_principal_valido():
    """1. Runtime principal válido (Python 3.14.10) selecionado normalmente."""
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
        pytest.skip("Runtime de produção em runtime/python não está disponível no ambiente de CI.")
    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(ROOT)
    assert rt_type == "embedded"
    assert rt_dir == ROOT / "runtime" / "python"
    assert rt_meta.get("source") == "primary"
    assert "contingency" not in rt_meta
    assert py_exe is not None and py_exe.is_file()
    assert pyw_exe is not None and pyw_exe.is_file()


def test_02_runtime_principal_ausente_em_producao_rejeita(tmp_path: Path, monkeypatch):
    """2. Runtime principal ausente em produção interrompe e exige reinstalação."""
    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    monkeypatch.delenv("ULTRON_DEV", raising=False)
    monkeypatch.delenv("ULTRON_ALLOW_SECONDARY_RUNTIME", raising=False)

    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "missing"
    assert py_exe is None
    assert rt_dir is None
    assert "ausente" in rt_meta.get("error", "").lower()


def test_03_runtime_principal_corrompido_interrompe(tmp_path: Path, monkeypatch):
    """3. Runtime principal corrompido interrompe sem mascaramento e não executa."""
    prim_dir = tmp_path / "runtime" / "python"
    prim_dir.mkdir(parents=True, exist_ok=True)
    (prim_dir / "arquivo_incompleto.txt").write_text("dados_corrompidos")

    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "corrupt"
    assert py_exe is None
    assert rt_dir == prim_dir
    assert "error" in rt_meta


def test_04_runtime_secundario_presente_mas_nao_selecionado_em_producao(tmp_path: Path, monkeypatch):
    """4. Runtime secundário presente, mas NÃO selecionado automaticamente em produção."""
    # Simular secundário válido em build/runtime/python
    sec_dir = tmp_path / "build" / "runtime" / "python"
    _create_mock_embedded_runtime(sec_dir, version="3.12.9")

    # Modo de produção instalado
    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    monkeypatch.delenv("ULTRON_DEV", raising=False)
    monkeypatch.delenv("ULTRON_ALLOW_SECONDARY_RUNTIME", raising=False)

    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    # Deve rejeitar e retornar missing (não mascarar a falta do 3.14.10)
    assert rt_type == "missing", f"Esperado 'missing' em producao, mas obteve {rt_type}"
    assert py_exe is None


def test_05_ambos_os_runtimes_invalidos(tmp_path: Path, monkeypatch):
    """5. Ambos os runtimes inválidos interrompem a inicialização."""
    prim_dir = tmp_path / "runtime" / "python"
    prim_dir.mkdir(parents=True, exist_ok=True)
    sec_dir = tmp_path / "build" / "runtime" / "python"
    sec_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "corrupt"
    assert py_exe is None


def test_06_venv_presente_em_instalacao_de_producao_e_recusado(tmp_path: Path, monkeypatch):
    """6. .venv presente em instalação de produção é recusado peremptoriamente."""
    venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True, exist_ok=True)
    venv_py.write_bytes(b"MOCK_VENV")

    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    monkeypatch.delenv("ULTRON_DEV", raising=False)

    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "missing"
    assert py_exe is None


def test_07_venv_presente_em_desenvolvimento_e_aceito(tmp_path: Path, monkeypatch):
    """7. .venv presente em desenvolvimento (.git) é aceito como fallback técnico."""
    venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True, exist_ok=True)
    venv_py.write_bytes(b"MOCK_VENV")

    (tmp_path / ".git").mkdir()
    monkeypatch.delenv("ULTRON_INSTALLED", raising=False)
    monkeypatch.delenv("ULTRON_DEV", raising=False)

    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "venv"
    assert py_exe == venv_py


def test_08_python_global_nunca_usado_como_fallback(tmp_path: Path, monkeypatch):
    """8. Python global presente no sistema NUNCA é utilizado como fallback."""
    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    # Garantir que em nenhuma hipotese o executavel do sistema (sys.executable) seja devolvido
    assert py_exe != Path(sys.executable)
    assert py_exe is None
    assert rt_type == "missing"


def test_09_diagnostico_mostrando_causa_da_interrupcao(tmp_path: Path, capsys):
    """9. Diagnóstico (_doctor) exibe causa da interrupção em caso de falha."""
    prim_dir = tmp_path / "runtime" / "python"
    prim_dir.mkdir(parents=True, exist_ok=True)
    (prim_dir / "invalido.txt").write_text("corrompido")

    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "Corrompido" in captured
    assert "problema(s) encontrado(s)" in captured


def test_10_diagnostico_mostrando_versao_selecionada(capsys):
    """10. Diagnóstico (_doctor) exibe fielmente a versão selecionada em sucesso."""
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
        pytest.skip("Runtime de produção em runtime/python não está disponível no ambiente de CI.")
    ret = launcher._doctor(ROOT)
    captured = capsys.readouterr().out
    assert ret == 0
    assert "Python 3.14.10 Embedded (python)" in captured
    assert "Diagnóstico concluído." in captured


def test_11_cenario_b_primario_valido_com_variavel_mantem_precedencia(tmp_path: Path, monkeypatch):
    """Cenário B: Produção com Python 3.14.10 válido e variável igual a 1 mantém Python 3.14.10."""
    prim_dir = tmp_path / "runtime" / "python"
    sec_dir = tmp_path / "build" / "runtime" / "python"
    _create_mock_embedded_runtime(prim_dir, version="3.14.10")
    _create_mock_embedded_runtime(sec_dir, version="3.12.9")

    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    monkeypatch.delenv("ULTRON_DEV", raising=False)
    monkeypatch.setenv("ULTRON_ALLOW_SECONDARY_RUNTIME", "1")

    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "embedded"
    assert rt_dir == prim_dir
    assert rt_meta.get("source") == "primary"
    assert "contingency" not in rt_meta
    assert rt_meta.get("python_version") == "3.14.10"


def test_12_cenario_d_primario_ausente_com_variavel_seleciona_contingencia(tmp_path: Path, monkeypatch):
    """Cenário D: Produção com Python 3.14.10 ausente e variável igual a 1 seleciona 3.12.9 com contingência."""
    sec_dir = tmp_path / "build" / "runtime" / "python"
    _create_mock_embedded_runtime(sec_dir, version="3.12.9")

    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    monkeypatch.delenv("ULTRON_DEV", raising=False)
    monkeypatch.setenv("ULTRON_ALLOW_SECONDARY_RUNTIME", "1")

    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "embedded"
    assert rt_dir == sec_dir
    assert rt_meta.get("source") == "secondary"
    assert rt_meta.get("contingency") is True
    assert rt_meta.get("python_version") == "3.12.9"


def test_13_cenario_e_primario_corrompido_com_variavel_bloqueia_sem_mascarar(tmp_path: Path, monkeypatch):
    """Cenário E: Produção com Python 3.14.10 corrompido e variável igual a 1 bloqueia sem mascaramento."""
    prim_dir = tmp_path / "runtime" / "python"
    prim_dir.mkdir(parents=True, exist_ok=True)
    (prim_dir / "arquivo_incompleto.txt").write_text("dados_corrompidos")

    sec_dir = tmp_path / "build" / "runtime" / "python"
    _create_mock_embedded_runtime(sec_dir, version="3.12.9")

    monkeypatch.setenv("ULTRON_INSTALLED", "1")
    monkeypatch.delenv("ULTRON_DEV", raising=False)
    monkeypatch.setenv("ULTRON_ALLOW_SECONDARY_RUNTIME", "1")

    py_exe, pyw_exe, rt_type, rt_dir, rt_meta = launcher._resolve_python(tmp_path)
    assert rt_type == "corrupt"
    assert py_exe is None
    assert rt_dir == prim_dir
    assert "error" in rt_meta

