import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import disco_ops


def test_backup_incremental_bloqueia_loop_destino_dentro_origem(tmp_path):
    # Review Focus #5: destination inside origin is blocked
    origem = tmp_path / "projetos"
    origem.mkdir()
    destino = origem / "backup"
    destino.mkdir()

    res = disco_ops.executar_backup_incremental(origem=str(origem), destino=str(destino))
    assert res["sucesso"] is False
    assert any(p in res["erro"].lower() for p in ("destino dentro da origem", "loop", "conter"))


def test_backup_incremental_copia_arquivos_e_cria_manifesto(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    destino = tmp_path / "destino"
    destino.mkdir()

    (origem / "doc1.txt").write_bytes(b"conteudo teste 1")
    (origem / "doc2.txt").write_bytes(b"conteudo teste 2")

    res = disco_ops.executar_backup_incremental(origem=str(origem), destino=str(destino))
    assert res["sucesso"] is True
    assert res["copiados"] == 2
    assert (destino / "doc1.txt").exists()
    assert (destino / "doc2.txt").exists()
    manifesto = destino / ".ultron-backup-manifest.json"
    assert manifesto.exists()

    # Segunda rodada sem alteração não copia novamente
    res2 = disco_ops.executar_backup_incremental(origem=str(origem), destino=str(destino))
    assert res2["copiados"] == 0
    assert res2["inalterados"] == 2


def test_arquivar_capturas_desktop_filtra_idade_e_nome(tmp_path):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    velha = desk / "Screenshot 2026-10-01 1000.png"
    nova = desk / "Screenshot 2026-11-13 1000.png"
    outro = desk / "trabalho.docx"

    velha.write_bytes(b"print antiga")
    nova.write_bytes(b"print nova")
    outro.write_bytes(b"texto")

    agora = time.time()
    os.utime(velha, (agora - 10 * 86400, agora - 10 * 86400))
    os.utime(nova, (agora - 1 * 86400, agora - 1 * 86400))

    with patch("disco_ops.desfazer.registrar"):
        res = disco_ops.arquivar_capturas_desktop(dias=7, executar=True, desktop_pasta=str(desk))
        assert res["movidos"] == 1
        assert not velha.exists()
        assert nova.exists()
        assert outro.exists()


def test_corrigir_permissoes_pasta_bloqueia_sem_admin():
    with patch("seguranca.modo_admin_ativo", return_value=False):
        res = disco_ops.corrigir_permissoes_pasta("C:\\teste")
        assert res["sucesso"] is False
        assert "modo admin" in res["erro"].lower()


def test_ejetar_usb_ocioso_recusa_disco_fixo():
    # Review Focus #4: fixed system drive C: is rejected
    with patch("disco_ops._tipo_unidade_windows", return_value=3):  # DRIVE_FIXED = 3
        res = disco_ops.ejetar_usb_ocioso(unidade="C:\\")
        assert res["sucesso"] is False
        assert "não é unidade removível" in res["erro"].lower()
