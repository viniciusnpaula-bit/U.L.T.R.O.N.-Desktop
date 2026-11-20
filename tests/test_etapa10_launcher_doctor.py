"""
Suíte de Testes Automatizados da Cobertura Real do launcher.py --doctor (Etapa 10.3.2).
Valida isoladamente os 8 cenários exigidos pela auditoria, mais a verificação de segurança:
1. Runtime principal íntegro.
2. Runtime principal ausente.
3. Manifesto inválido.
4. Arquivos essenciais ausentes.
5. Electron ausente.
6. Núcleo Python não importável.
7. Diretórios de dados inacessíveis / ausentes.
8. Configurações (.env) ausentes.
9. Segurança estrita (ausência total de vazamento de credenciais, tokens, chaves ou PIN).
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


def _create_mock_structure(base_dir: Path) -> tuple[Path, Path]:
    """Cria estrutura mock mínima para testes seletivos de componentes do doctor."""
    prim_dir = base_dir / "runtime" / "python"
    prim_dir.mkdir(parents=True, exist_ok=True)
    # Binário real ou cópia mínima para passar na verificação de arquivos
    (prim_dir / "python.exe").write_bytes(b"MOCK_BIN")
    (prim_dir / "python3.dll").write_bytes(b"MOCK_DLL")
    (prim_dir / "vcruntime140.dll").write_bytes(b"MOCK_VCRUNTIME")
    (prim_dir / "python314._pth").write_text("Lib\nLib\\site-packages\n.\nimport site\n", encoding="utf-8")
    (prim_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    (prim_dir / "RUNTIME_INFO.json").write_text('{"python_version": "3.14.10"}', encoding="utf-8")

    (base_dir / "desktop.py").write_text("# mock entrypoint\n", encoding="utf-8")
    el_dist = base_dir / "electron" / "node_modules" / "electron" / "dist"
    el_dist.mkdir(parents=True, exist_ok=True)
    (el_dist / "electron.exe").write_bytes(b"MOCK_EL")

    (base_dir / ".env").write_text("GEMINI_API_KEY=test_key\n", encoding="utf-8")
    (base_dir / "dados").mkdir(parents=True, exist_ok=True)
    (base_dir / "dados" / "ultron.db").write_bytes(b"MOCK_SQLITE")

    return prim_dir, el_dist


def test_doctor_01_runtime_principal_integro(capsys):
    """1. Runtime principal íntegro: validação real do ambiente oficial."""
    ret = launcher._doctor(ROOT)
    captured = capsys.readouterr().out
    assert ret == 0
    assert "OK  Python seguro    Python 3.14.10 Embedded (python)" in captured
    assert "OK  núcleo           config, cerebro, seguranca" in captured
    assert "Diagnóstico concluído." in captured


def test_doctor_02_runtime_principal_ausente(tmp_path: Path, capsys):
    """2. Runtime principal ausente: detecta e reporta 'Não encontrado'."""
    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "XX  Python seguro    Não encontrado" in captured
    assert "problema(s) encontrado(s)" in captured


def test_doctor_03_manifesto_invalido(tmp_path: Path, capsys):
    """3. Manifesto inválido: detecta JSON quebrado ou sem versão."""
    prim_dir, _ = _create_mock_structure(tmp_path)
    (prim_dir / "RUNTIME_INFO.json").write_text("{json_corrompido: true", encoding="utf-8")

    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "XX  Python seguro    Corrompido" in captured


def test_doctor_04_arquivos_essenciais_ausentes(tmp_path: Path, capsys):
    """4. Arquivos essenciais ausentes: detecta falta de python3.dll ou python.exe."""
    prim_dir, _ = _create_mock_structure(tmp_path)
    (prim_dir / "python3.dll").unlink()

    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "XX  Python seguro    Corrompido" in captured
    assert "DLL essencial ausente" in captured


def test_doctor_05_electron_ausente(tmp_path: Path, capsys):
    """5. Electron ausente: detecta falta de dist/electron.exe."""
    _prim_dir, el_dist = _create_mock_structure(tmp_path)
    (el_dist / "electron.exe").unlink()

    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "XX  Electron" in captured
    assert "Não encontrado" in captured


def test_doctor_06_nucleo_nao_importavel(tmp_path: Path, capsys):
    """6. Núcleo Python não importável: detecta falha ao tentar importar config/cerebro/seguranca."""
    _prim_dir, _ = _create_mock_structure(tmp_path)
    # Como o mock python.exe não é um executável Win32 real, a tentativa de spawn gera OSError
    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "XX  núcleo" in captured


def test_doctor_07_dados_inacessiveis(tmp_path: Path, monkeypatch, capsys):
    """7. Diretórios de dados inacessíveis / ausentes: detecta falta de ultron.db."""
    _prim_dir, _ = _create_mock_structure(tmp_path)
    (tmp_path / "dados" / "ultron.db").unlink()
    # Isolar de %LOCALAPPDATA%
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "inexistente"))

    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "XX  Dados            memória e histórico" in captured


def test_doctor_08_configuracoes_ausentes(tmp_path: Path, monkeypatch, capsys):
    """8. Configurações ausentes: detecta falta do arquivo .env."""
    _prim_dir, _ = _create_mock_structure(tmp_path)
    (tmp_path / ".env").unlink()
    # Isolar de %APPDATA%
    monkeypatch.setenv("APPDATA", str(tmp_path / "inexistente"))

    ret = launcher._doctor(tmp_path)
    captured = capsys.readouterr().out
    assert ret != 0
    assert "XX  .env             chaves de IA" in captured


def test_doctor_09_seguranca_sem_vazamento_de_segredos(capsys):
    """9. Segurança estrita: varre a saída do doctor e atesta zero vazamento de credenciais."""
    ret = launcher._doctor(ROOT)
    captured = capsys.readouterr().out

    # Padrões conhecidos de chaves e segredos
    proibidos = [
        "AQ.Ab8RN", "gsk_", "sk-proj", "sk-or-v1",
        "SECRET", "TOKEN", "PIN", "SENHA", "PASSWORD"
    ]
    for segredo in proibidos:
        assert segredo not in captured, f"Segredo detectado na saída do doctor: {segredo}"
