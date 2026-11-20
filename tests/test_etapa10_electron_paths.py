"""
Suíte de Testes Automatizados dos Caminhos do Electron e Suporte a win-unpacked (Etapa 10.4.1).
Valida isoladamente os 8 cenários obrigatórios:
1. Produção com win-unpacked presente.
2. Desenvolvimento com node_modules presente.
3. Prioridade da versão de produção quando ambas existem.
4. Ausência de ambas as versões (lança FileNotFoundError e falha no doctor).
5. Caminhos contendo espaços e caracteres especiais.
6. Diretório de trabalho (CWD) correto para cada variante.
7. Preservação estrita das variáveis de ambiente necessárias (ULTRON_API_URL, ULTRON_API_TOKEN, ULTRON_ROOT).
8. Diagnóstico correto no launcher --doctor para cada variante (produção, dev e ausente).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import desktop
import launcher


def _setup_mock_environment(base_dir: Path, *, prod: bool = False, dev: bool = False) -> tuple[Path | None, Path | None]:
    """Cria executáveis mock para produção e/ou desenvolvimento."""
    prod_exe = None
    dev_exe = None
    if prod:
        prod_dir = base_dir / "electron" / "win-unpacked"
        prod_dir.mkdir(parents=True, exist_ok=True)
        prod_exe = prod_dir / "U.L.T.R.O.N. Desktop.exe"
        prod_exe.write_bytes(b"MOCK_PROD_ELECTRON")
        (prod_dir / "resources").mkdir(parents=True, exist_ok=True)
        (prod_dir / "resources" / "app.asar").write_bytes(b"MOCK_ASAR")

    if dev:
        dev_dir = base_dir / "electron" / "node_modules" / "electron" / "dist"
        dev_dir.mkdir(parents=True, exist_ok=True)
        dev_exe = dev_dir / "electron.exe"
        dev_exe.write_bytes(b"MOCK_DEV_ELECTRON")
        el_root = base_dir / "electron"
        (el_root / "package.json").write_text('{"name": "test"}', encoding="utf-8")
        (el_root / "main.js").write_text("// mock main", encoding="utf-8")
        (el_root / "site").mkdir(parents=True, exist_ok=True)
        (el_root / "site" / "index.html").write_text("<!-- mock -->", encoding="utf-8")

    return prod_exe, dev_exe


def test_01_producao_com_win_unpacked_presente(tmp_path: Path):
    """1. Produção com win-unpacked presente: seleciona o executável de produção."""
    prod_exe, _ = _setup_mock_environment(tmp_path, prod=True, dev=False)
    exe, app_dir = desktop._electron_paths(tmp_path)
    assert exe == prod_exe
    assert exe.is_file()
    assert app_dir == prod_exe.parent


def test_02_desenvolvimento_com_node_modules_presente(tmp_path: Path):
    """2. Desenvolvimento com node_modules presente: seleciona o executável de desenvolvimento."""
    _, dev_exe = _setup_mock_environment(tmp_path, prod=False, dev=True)
    exe, app_dir = desktop._electron_paths(tmp_path)
    assert exe == dev_exe
    assert exe.is_file()
    assert app_dir == tmp_path / "electron"


def test_03_prioridade_da_versao_de_producao(tmp_path: Path):
    """3. Prioridade da versão de produção quando ambas existem simultaneamente."""
    prod_exe, dev_exe = _setup_mock_environment(tmp_path, prod=True, dev=True)
    exe, app_dir = desktop._electron_paths(tmp_path)
    assert exe == prod_exe, "A versão de produção win-unpacked deve ter prioridade absoluta sobre node_modules"
    assert exe != dev_exe
    assert app_dir == prod_exe.parent


def test_04_ausencia_de_ambas_as_versoes(tmp_path: Path):
    """4. Ausência de ambas as versões: _electron_paths devolve candidato dev ausente e _launch_electron lança FileNotFoundError."""
    exe, app_dir = desktop._electron_paths(tmp_path)
    assert not exe.exists()
    with pytest.raises(FileNotFoundError, match="Electron não instalado"):
        desktop._launch_electron(exe, app_dir, "http://127.0.0.1:3900", "token", tmp_path)


def test_05_caminhos_com_espacos(tmp_path: Path):
    """5. Caminhos com espaços e acentos: valida suporte correto."""
    space_root = tmp_path / "Pasta com Espaços & Acentos (Teste)"
    space_root.mkdir()
    prod_exe, _ = _setup_mock_environment(space_root, prod=True)
    exe, app_dir = desktop._electron_paths(space_root)
    assert exe == prod_exe
    assert " " in str(exe)
    assert exe.is_file()


def test_06_diretorio_de_trabalho_correto(tmp_path: Path):
    """6. Diretório de trabalho (cwd) correto para cada variante."""
    prod_exe, dev_exe = _setup_mock_environment(tmp_path, prod=True, dev=True)

    # Produção usa cwd = prod_exe.parent
    calls = []
    def fake_run(cmd, cwd=None, env=None, check=False):
        calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        return subprocess.CompletedProcess(cmd, 0)

    with patch("subprocess.run", side_effect=fake_run):
        desktop._launch_electron(prod_exe, prod_exe.parent, "http://127.0.0.1:3900", "token_prod", tmp_path)
        assert len(calls) == 1
        assert calls[0]["cwd"] == prod_exe.parent
        assert calls[0]["cmd"] == [str(prod_exe)]

    # Desenvolvimento usa cwd = app_dir e inclui app_dir nos argumentos
    calls.clear()
    with patch("subprocess.run", side_effect=fake_run):
        dev_app_dir = tmp_path / "electron"
        desktop._launch_electron(dev_exe, dev_app_dir, "http://127.0.0.1:3900", "token_dev", tmp_path)
        assert len(calls) == 1
        assert calls[0]["cwd"] == dev_app_dir
        assert calls[0]["cmd"] == [str(dev_exe), str(dev_app_dir)]


def test_07_preservacao_variaveis_ambiente(tmp_path: Path):
    """7. Preservação das variáveis de ambiente necessárias (ULTRON_API_URL, ULTRON_API_TOKEN, ULTRON_ROOT)."""
    prod_exe, _ = _setup_mock_environment(tmp_path, prod=True)
    captured_env = {}
    def fake_run(cmd, cwd=None, env=None, check=False):
        captured_env.update(env or {})
        return subprocess.CompletedProcess(cmd, 0)

    with patch("subprocess.run", side_effect=fake_run):
        desktop._launch_electron(prod_exe, prod_exe.parent, "http://127.0.0.1:3900", "meu_token_secreto", tmp_path)

    assert captured_env.get("ULTRON_API_URL") == "http://127.0.0.1:3900"
    assert captured_env.get("ULTRON_API_TOKEN") == "meu_token_secreto"
    assert captured_env.get("ULTRON_ROOT") == str(tmp_path.resolve())
    assert "PATH" in captured_env
    assert "SYSTEMROOT" in captured_env


def test_08_diagnostico_doctor_variantes(tmp_path: Path, capsys):
    """8. Diagnóstico correto no launcher --doctor para cada variante (produção, dev e ausente)."""
    # Cenário A: Produção
    prod_root = tmp_path / "prod"
    _setup_mock_environment(prod_root, prod=True)
    (prod_root / "runtime" / "python").mkdir(parents=True, exist_ok=True)
    launcher._doctor(prod_root)
    out_prod = capsys.readouterr().out
    assert "OK  Electron         produção (win-unpacked)" in out_prod

    # Cenário B: Desenvolvimento
    dev_root = tmp_path / "dev"
    _setup_mock_environment(dev_root, dev=True)
    (dev_root / "runtime" / "python").mkdir(parents=True, exist_ok=True)
    launcher._doctor(dev_root)
    out_dev = capsys.readouterr().out
    assert "OK  Electron         desenvolvimento (node_modules)" in out_dev

    # Cenário C: Ausente
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    launcher._doctor(empty_root)
    out_empty = capsys.readouterr().out
    assert "XX  Electron         Não encontrado" in out_empty
