"""
Suíte de Testes Automatizados da Geração e Validação do Instalador Inno Setup (Etapa 10.4.2).
Valida:
1. Existência e integridade do script Inno Setup (installer/ultron_setup.iss).
2. Diretivas de instalação por usuário (PrivilegesRequired=lowest e DefaultDirName em LocalAppData).
3. Preservação de configurações do usuário (onlyifdoesntexist e uninsneveruninstall para .env).
4. Ausência de arquivos e diretórios de desenvolvimento (.git, .venv, etc.) nas diretivas de empacotamento.
5. Validação de todos os arquivos de origem referenciados no script .iss.
6. Existência e integridade do instalador compilado (installer/dist/ULTRON-Setup-v2.1.0.exe).
7. Launcher ULTRON.exe gerado e íntegro.
8. Compatibilidade criptográfica da chave pública Ed25519 com o mecanismo de atualização.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import atualizacao
import assinatura


def _versao_atual() -> str:
    return json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))["version"]


def test_01_script_inno_setup_existe():
    """1. O script oficial de instalação deve existir e ter conteúdo válido."""
    iss_file = ROOT / "installer" / "ultron_setup.iss"
    assert iss_file.is_file(), "installer/ultron_setup.iss deve existir"
    content = iss_file.read_text(encoding="utf-8")
    assert "[Setup]" in content
    assert "[Files]" in content
    assert "[Icons]" in content


def test_02_diretivas_de_instalacao_por_usuario():
    """2. O instalador deve ser configurado para instalação por usuário sem privilégios administrativos."""
    iss_file = ROOT / "installer" / "ultron_setup.iss"
    content = iss_file.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in content
    assert "{localappdata}\\Programs\\ULTRON" in content
    assert "OutputBaseFilename=ULTRON-Setup-v{#MyAppVersion}" in content or "OutputBaseFilename=ULTRON-Setup-v2.1.0" in content


def test_03_preservacao_estrita_configuracao_usuario():
    """3. O arquivo .env deve usar onlyifdoesntexist e uninsneveruninstall."""
    iss_file = ROOT / "installer" / "ultron_setup.iss"
    content = iss_file.read_text(encoding="utf-8")
    env_lines = [line for line in content.splitlines() if ".env.example" in line and "{userappdata}\\ULTRON" in line]
    assert len(env_lines) == 1, "Deve existir exatamente uma linha mapeando .env.example para {userappdata}\\ULTRON"
    line = env_lines[0]
    assert "onlyifdoesntexist" in line
    assert "uninsneveruninstall" in line


def test_04_bloqueio_de_pastas_de_desenvolvimento_no_iss():
    """4. O script não deve incluir pastas de desenvolvimento como .git ou .venv."""
    iss_file = ROOT / "installer" / "ultron_setup.iss"
    content = iss_file.read_text(encoding="utf-8")
    forbidden = [".git\\", ".venv\\", "\\venv\\", "__pycache__", ".pytest_cache"]
    for word in forbidden:
        assert word not in content, f"Script .iss não pode referenciar {word}"


def test_05_arquivos_de_origem_existem():
    """5. Todos os caminhos de origem referenciados no script .iss devem existir no repositório."""
    installer_dir = ROOT / "installer"
    expected_sources = [
        ROOT / "ULTRON.exe",
        ROOT / "iniciar_desktop.bat",
        ROOT / "launcher.py",
        ROOT / "desktop.py",
        ROOT / "config.py",
        ROOT / ".env.example",
        ROOT / "permissoes.json",
        ROOT / "registros_emocionais.json",
        ROOT / "requirements.txt",
        ROOT / "LEIA-ME.txt",
        ROOT / "LICENSE",
        ROOT / "SECURITY.md",
        ROOT / "U.L.T.R.O.N.-Logo.png",
        ROOT / "runtime" / "python" / "python.exe",
        ROOT / "runtime" / "python" / "RUNTIME_INFO.json",
        ROOT / "electron" / "package.json",
        ROOT / "electron" / "assets" / "ULTRON.ico",
        ROOT / "electron" / "dist" / "win-unpacked" / "U.L.T.R.O.N. Desktop.exe",
        ROOT / "electron" / "dist" / "win-unpacked" / "resources" / "app.asar",
    ]
    for src in expected_sources:
        assert src.is_file(), f"Arquivo de origem obrigatório ausente: {src}"


def test_06_instalador_compilado_existe_e_valido():
    """6. O instalador compilado ULTRON-Setup-v<versao>.exe deve existir e ter tamanho compatível."""
    versao = _versao_atual()
    setup_exe = ROOT / "installer" / "dist" / f"ULTRON-Setup-v{versao}.exe"
    assert setup_exe.is_file(), f"O instalador compilado deve existir em {setup_exe}"
    size = setup_exe.stat().st_size
    # Esperado entre 200 MB e 450 MB com compressão sólida LZMA2
    assert 200 * 1024 * 1024 <= size <= 450 * 1024 * 1024, f"Tamanho inesperado do instalador: {size} bytes"


def test_07_launcher_ultron_exe_valido():
    """7. O launcher ULTRON.exe deve ser um binário Win32 PE limpo (sem bootloader PyInstaller --onefile)."""
    ultron_exe = ROOT / "ULTRON.exe"
    assert ultron_exe.is_file()
    dados = ultron_exe.read_bytes()
    assert len(dados) >= 8 * 1024
    assert dados[:2] == b"MZ", "ULTRON.exe deve ser um executável Windows PE válido"
    assert b"MEI\x0c\x0b\x0a\x0b\x0e" not in dados, "ULTRON.exe não deve usar bootloader PyInstaller --onefile"


def test_08_verificacao_ed25519_atualizador():
    """8. A chave pública Ed25519 em atualizacao.py deve ser válida e decodificável."""
    pub_b64 = atualizacao.CHAVE_PUBLICA_ATUALIZACAO
    assert pub_b64, "CHAVE_PUBLICA_ATUALIZACAO não pode estar vazia"
    pub_bytes = base64.b64decode(pub_b64)
    assert len(pub_bytes) == 32, "Chave pública Ed25519 deve ter exatamente 32 bytes crus"
    pub_key = assinatura.carregar_publica_base64(pub_b64)
    assert pub_key is not None
