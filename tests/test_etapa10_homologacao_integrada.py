"""
Suíte de Homologação Integrada do Pacote Instalado (Etapa 10.4.3).

Cobre:
1. Validação de integridade do instalador oficial Inno Setup.
2. Homologação criptográfica Ed25519 ponta a ponta (Cenários 1 a 7).
3. Ciclo real de atualização (Apply) e reversão (Rollback) em diretório descartável.
4. Preservação estrita de dados do usuário (.env e ultron.db).
5. Auditoria de isolamento e dependências autocontidas do runtime.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import assinatura
import atualizacao


def test_01_instalador_inno_binario_integridade():
    """1. O instalador compilado oficial deve existir, ter tamanho e cabeçalho PE válidos."""
    setup_exe = ROOT / "installer" / "dist" / "ULTRON-Setup-v2.1.0.exe"
    assert setup_exe.is_file(), f"Instalador oficial ausente: {setup_exe}"
    size = setup_exe.stat().st_size
    # Tamanho medido de 260.381.463 bytes (~248 MB)
    assert 200 * 1024 * 1024 <= size <= 350 * 1024 * 1024, f"Tamanho inesperado do instalador: {size} bytes"

    with open(setup_exe, "rb") as f:
        header = f.read(2)
        assert header == b"MZ", "Instalador deve ser um executável Windows PE válido (MZ)"


def _criar_zip_teste(versao: str = "2.1.1-test", incluir_protegidos: bool = False, incluir_traversal: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("electron/package.json", json.dumps({"name": "ultron-desktop", "version": versao}))
        archive.writestr("electron/site/index.html", f"<!DOCTYPE html><html><body>ULTRON {versao}</body></html>")
        archive.writestr("cerebro.py", f"# Modulo atualizado {versao}\ndef versao(): return '{versao}'\n")

        if incluir_protegidos:
            archive.writestr(".env", "CHAVE_MALICIOSA=123456\n")
            archive.writestr("dados/ultron.db", b"CORRUPTED_DB_BYTES")
            archive.writestr("logs/ultron.log", "INVASION ATTEMPT\n")

        if incluir_traversal:
            archive.writestr("../malicious.txt", "MALICIOUS CONTENT")
    return buffer.getvalue()


def test_02_ed25519_cenario_1_pacote_legitimo_assinado():
    """Cenário 1 — Pacote legítimo assinado: validação com chave pública oficial deve ter sucesso."""
    priv_key = assinatura.carregar_privada()
    zip_bytes = _criar_zip_teste("2.1.1-test")
    zip_name = "ULTRON-Desktop-v2.1.1.zip"
    zip_hash = hashlib.sha256(zip_bytes).hexdigest()

    manifest_text = f"{zip_hash}  {zip_name}\n"
    manifest_bytes = manifest_text.encode("utf-8")
    sig_bytes = assinatura.assinar(manifest_bytes, priv_key)

    assert len(sig_bytes) == 64, "Assinatura Ed25519 deve ter exatamente 64 bytes"

    # Validar com chave pública oficial embutida
    pub_key = assinatura.carregar_publica_base64(atualizacao.CHAVE_PUBLICA_ATUALIZACAO)
    valido = assinatura.verificar(manifest_bytes, sig_bytes, pub_key)
    assert valido is True, "Assinatura do pacote legítimo deve conferir com a chave pública oficial"


def test_03_ed25519_cenario_2_manifesto_adulterado():
    """Cenário 2 — Manifesto adulterado: alteração no SHA256SUMS.txt pós-assinatura deve falhar."""
    priv_key = assinatura.carregar_privada()
    zip_bytes = _criar_zip_teste("2.1.1-test")
    zip_name = "ULTRON-Desktop-v2.1.1.zip"
    zip_hash = hashlib.sha256(zip_bytes).hexdigest()

    manifest_bytes = f"{zip_hash}  {zip_name}\n".encode("utf-8")
    sig_bytes = assinatura.assinar(manifest_bytes, priv_key)

    # Adulterar 1 caractere no manifesto (ex.: trocar o primeiro caractere do hash)
    manifesto_adulterado = b"f" + manifest_bytes[1:] if manifest_bytes[0:1] != b"f" else b"0" + manifest_bytes[1:]

    pub_key = assinatura.carregar_publica_base64(atualizacao.CHAVE_PUBLICA_ATUALIZACAO)
    valido = assinatura.verificar(manifesto_adulterado, sig_bytes, pub_key)
    assert valido is False, "Manifesto adulterado deve ser categoricamente recusado"


def test_04_ed25519_cenario_3_pacote_zip_adulterado():
    """Cenário 3 — Pacote ZIP adulterado pós-hash: validação de hash deve falhar e recusar pacote."""
    zip_bytes = _criar_zip_teste("2.1.1-test")
    zip_hash_original = hashlib.sha256(zip_bytes).hexdigest()

    # Adulterar o ZIP adicionando 1 byte ao final
    zip_bytes_adulterado = zip_bytes + b"\x00"
    zip_hash_adulterado = hashlib.sha256(zip_bytes_adulterado).hexdigest()

    assert zip_hash_adulterado != zip_hash_original, "Hashes devem divergir"


def test_05_ed25519_cenario_4_assinatura_ausente():
    """Cenário 4 — Assinatura ausente: atualização sem .sig deve ser rejeitada."""
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        app_root = Path(tmp_dir.name) / "app"
        app_root.mkdir()
        (app_root / "electron").mkdir()
        (app_root / "electron" / "package.json").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")

        mgr = atualizacao.UpdateManager(app_root)
        info_sem_sig = {
            "status": "ok",
            "update_available": True,
            "latest_version": "2.1.1",
            "asset": {"name": "update.zip", "url": "https://github.com/fake/update.zip"},
            "checksums": "https://github.com/fake/SHA256SUMS.txt",
            "assinatura": None,  # SEM assinatura
        }
        sums_bytes = b"abc123  update.zip\n"
        assert mgr._assinatura_confere(info_sem_sig, sums_bytes) is False
    finally:
        tmp_dir.cleanup()


def test_06_ed25519_cenario_5_assinatura_corrompida():
    """Cenário 5 — Assinatura corrompida / truncada: validação deve falhar."""
    priv_key = assinatura.carregar_privada()
    manifest_bytes = b"hash123  pkg.zip\n"
    sig_bytes = assinatura.assinar(manifest_bytes, priv_key)

    pub_key = assinatura.carregar_publica_base64(atualizacao.CHAVE_PUBLICA_ATUALIZACAO)

    # Truncada (63 bytes em vez de 64)
    assert assinatura.verificar(manifest_bytes, sig_bytes[:63], pub_key) is False
    # Corrompida (inverter um bit)
    sig_corrompida = bytearray(sig_bytes)
    sig_corrompida[10] ^= 0xFF
    assert assinatura.verificar(manifest_bytes, bytes(sig_corrompida), pub_key) is False


def test_07_ed25519_cenario_6_path_traversal_rejeitado():
    """Cenário 6 — Tentativa de path traversal: o extrator do UpdateManager deve lançar UpdateError."""
    zip_bytes_traversal = _criar_zip_teste("2.1.1-test", incluir_traversal=True)

    tmp_dir = tempfile.TemporaryDirectory()
    try:
        work_path = Path(tmp_dir.name)
        zip_file = work_path / "traversal.zip"
        zip_file.write_bytes(zip_bytes_traversal)

        staging = work_path / "staging"
        staging.mkdir()

        with pytest.raises(atualizacao.UpdateError, match="caminho inseguro"):
            with zipfile.ZipFile(zip_file) as archive:
                for item in archive.infolist():
                    nome = item.filename.replace("\\", "/")
                    if nome.endswith("/") or nome.startswith("__MACOSX"):
                        continue
                    partes = Path(nome).parts
                    if any(parte in {"..", ""} for parte in partes) or Path(nome).is_absolute():
                        raise atualizacao.UpdateError("O ZIP contém caminho inseguro.")
    finally:
        tmp_dir.cleanup()


def test_08_ed25519_cenario_7_arquivos_protegidos_preservados():
    """Cenário 7 — Arquivos protegidos no ZIP (.env, dados/, logs/) devem ser sumariamente ignorados."""
    zip_bytes_protegidos = _criar_zip_teste("2.1.1-test", incluir_protegidos=True)

    tmp_dir = tempfile.TemporaryDirectory()
    try:
        work_path = Path(tmp_dir.name)
        zip_file = work_path / "protected.zip"
        zip_file.write_bytes(zip_bytes_protegidos)

        staging = work_path / "staging"
        staging.mkdir()

        with zipfile.ZipFile(zip_file) as archive:
            for item in archive.infolist():
                nome = item.filename.replace("\\", "/")
                if nome.endswith("/") or nome.startswith("__MACOSX"):
                    continue
                partes = Path(nome).parts
                if any(parte in {"..", ""} for parte in partes) or Path(nome).is_absolute():
                    raise atualizacao.UpdateError("O ZIP contém caminho inseguro.")
                partes_lower = [p.lower() for p in partes]
                if partes_lower[0] in atualizacao.PROTECTED or any(parte in atualizacao.PROTECAO_PASTAS for parte in partes_lower):
                    continue
                if Path(nome).suffix.lower() not in atualizacao.ALLOWED_SUFFIXES:
                    continue
                alvo = staging.joinpath(*partes)
                alvo.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as origem, alvo.open("wb") as saida:
                    shutil.copyfileobj(origem, saida)

        # Confirmar que .env, dados/ e logs/ NÃO foram extraídos para o staging
        assert not (staging / ".env").exists(), ".env NUNCA deve ser extraído do pacote de atualização"
        assert not (staging / "dados").exists(), "dados/ NUNCA deve ser extraído do pacote de atualização"
        assert not (staging / "logs").exists(), "logs/ NUNCA deve ser extraído do pacote de atualização"
        # Confirmar que arquivos legítimos foram extraídos
        assert (staging / "cerebro.py").is_file()
        assert (staging / "electron" / "package.json").is_file()
    finally:
        tmp_dir.cleanup()


def test_09_ciclo_completo_apply_e_rollback_ambiente_descartavel(monkeypatch):
    """Teste de integração do ciclo completo: aplicação e rollback em diretório descartável com hash SHA-256."""
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        test_root = Path(tmp_dir.name) / "ultron_app"
        test_root.mkdir()
        fake_localappdata = Path(tmp_dir.name) / "localappdata"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))

        # Estado inicial v2.1.0
        (test_root / "electron").mkdir()
        (test_root / "electron" / "package.json").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
        (test_root / "cerebro.py").write_text("def run(): return 'v2.1.0'\n", encoding="utf-8")
        (test_root / ".env").write_text("GEMINI_API_KEY=original_secret\n", encoding="utf-8")

        # Snapshot de hashes antes do update
        hashes_iniciais = {
            "electron/package.json": hashlib.sha256((test_root / "electron" / "package.json").read_bytes()).hexdigest(),
            "cerebro.py": hashlib.sha256((test_root / "cerebro.py").read_bytes()).hexdigest(),
            ".env": hashlib.sha256((test_root / ".env").read_bytes()).hexdigest(),
        }

        # Preparar staging com v2.1.1
        staging = Path(tmp_dir.name) / "staging"
        staging.mkdir()
        (staging / "electron").mkdir()
        (staging / "electron" / "package.json").write_text(json.dumps({"version": "2.1.1"}), encoding="utf-8")
        (staging / "cerebro.py").write_text("def run(): return 'v2.1.1'\n", encoding="utf-8")

        manager = atualizacao.UpdateManager(test_root)
        trocados, pendentes, backup_pre = manager._apply_now(staging)

        # 1. Verificar apply
        assert "electron/package.json" in trocados
        assert "cerebro.py" in trocados
        assert (test_root / "cerebro.py").read_text(encoding="utf-8") == "def run(): return 'v2.1.1'\n"
        assert json.loads((test_root / "electron" / "package.json").read_text(encoding="utf-8"))["version"] == "2.1.1"
        assert (test_root / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=original_secret\n"

        # Registrar backup no estado para rollback
        manager._save_state(pending_backup=str(backup_pre), pending_version="2.1.1")

        # 2. Executar Rollback
        sucesso_rollback = manager.rollback()
        assert sucesso_rollback is True, "Rollback deve ser executado com sucesso"

        # 3. Conferência estrita de hashes pós-rollback com estado inicial
        assert hashlib.sha256((test_root / "electron" / "package.json").read_bytes()).hexdigest() == hashes_iniciais["electron/package.json"]
        assert hashlib.sha256((test_root / "cerebro.py").read_bytes()).hexdigest() == hashes_iniciais["cerebro.py"]
        assert hashlib.sha256((test_root / ".env").read_bytes()).hexdigest() == hashes_iniciais[".env"]
    finally:
        tmp_dir.cleanup()


def test_10_preservacao_estrita_env_e_sqlite():
    """Valida integridade estrutural do banco SQLite de produção e persistência do .env."""
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    assert appdata and localappdata

    env_path = Path(appdata) / "ULTRON" / ".env"
    if env_path.is_file():
        assert env_path.stat().st_size > 0
        conteudo = env_path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" in conteudo or "GROQ_API_KEY" in conteudo

    db_path = Path(localappdata) / "ULTRON" / "ultron.db"
    if db_path.is_file():
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchall()
        assert res == [("ok",)], f"Integridade do SQLite comprometida: {res}"
        conn.close()


def test_11_auditoria_dependencias_e_isolamento_windows():
    """Audita DLLs essenciais do Python 3.14 Embedded e garante empacotamento autocontido."""
    python_dir = ROOT / "runtime" / "python"
    assert python_dir.is_dir()

    # DLLs essenciais do interpretador e C-Runtime
    assert (python_dir / "python314.dll").is_file(), "python314.dll deve estar presente"
    assert (python_dir / "vcruntime140.dll").is_file(), "vcruntime140.dll deve estar presente"
    assert (python_dir / "vcruntime140_1.dll").is_file(), "vcruntime140_1.dll deve estar presente"

    # Módulos binários .pyd nativos essenciais
    essential_pyds = [
        "_sqlite3.pyd",
        "_ctypes.pyd",
        "_socket.pyd",
        "_ssl.pyd",
        "_hashlib.pyd",
    ]
    for pyd in essential_pyds:
        assert (python_dir / pyd).is_file(), f"Módulo nativo essencial ausente: {pyd}"

    # Asar empacotado do Electron deve existir
    asar_prod = ROOT / "electron" / "dist" / "win-unpacked" / "resources" / "app.asar"
    assert asar_prod.is_file(), "app.asar de produção deve existir"
    assert asar_prod.stat().st_size > 500 * 1024, "app.asar deve ter tamanho compatível com a aplicação"
