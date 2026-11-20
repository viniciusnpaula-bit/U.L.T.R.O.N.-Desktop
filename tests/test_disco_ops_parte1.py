import os
import time
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import disco_ops


def test_config_bloco1_defaults(tmp_path):
    with patch("disco_ops.ARQUIVO_CONFIG_BLOCO1", tmp_path / "bloco1.json"):
        cfg = disco_ops.carregar_config_bloco1()
        assert cfg["downloads_pdf_ativo"] is True
        assert cfg["disco_limite_pct"] == 80
        assert cfg["usb_ocioso_seg"] == 300
        assert "projetos_pastas" in cfg
        assert "backup_origens" in cfg


def test_limpar_duplicados_mantem_mais_recente(tmp_path):
    p1 = tmp_path / "doc_velho.txt"
    p2 = tmp_path / "doc_novo.txt"
    p3 = tmp_path / "outro.txt"
    content = b"Conteudo exatamente identico para teste de deduplicacao."
    p1.write_bytes(content)
    p2.write_bytes(content)
    p3.write_bytes(b"Conteudo diferente")

    # Garante que p2 tem mtime mais recente
    agora = time.time()
    os.utime(p1, (agora - 100, agora - 100))
    os.utime(p2, (agora, agora))

    with patch("disco_ops.send2trash") as mock_trash, patch("disco_ops.desfazer.registrar"):
        resultado = disco_ops.limpar_duplicados(str(tmp_path), executar=True)
        assert resultado["removidos"] == 1
        assert resultado["bytes_economizados"] == len(content)
        mock_trash.assert_called_once_with(str(p1.resolve()))


def test_extrair_bloqueia_path_traversal(tmp_path):
    # Review Focus #2: archive containing traversal is blocked
    malicious_archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(malicious_archive, "w") as zf:
        zf.writestr("../../evil.exe", b"malware")

    res = disco_ops.extrair_e_limpar_instalador(str(malicious_archive), destino=str(tmp_path / "out"))
    assert res["sucesso"] is False
    assert any(palavra in res["erro"].lower() for palavra in ("bloqueado", "traversal", "invalido", "inseguro"))


def test_organizar_pdf_downloads_renomeia_arquivo(tmp_path):
    pdf_path = tmp_path / "download_teste.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 teste content")

    fake_meta = {"data": "2026-11-13", "assunto": "Fatura Internet"}
    with patch("disco_ops._extrair_texto_pdf", return_value="Fatura de servicos"), \
         patch("cerebro.extrair_titulo_pdf", return_value=fake_meta), \
         patch("disco_ops.desfazer.registrar"):
        res = disco_ops.organizar_pdf_downloads(pasta=str(tmp_path), aplicar=True)
        assert res["renomeados"] == 1
        esperado = tmp_path / "2026-11-13 - Fatura Internet.pdf"
        assert esperado.exists()
        assert not pdf_path.exists()
