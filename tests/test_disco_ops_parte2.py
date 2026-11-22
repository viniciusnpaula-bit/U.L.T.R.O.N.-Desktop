import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
import disco_ops


def test_limpar_disco_ignora_se_abaixo_do_limiar():
    mock_part = MagicMock(device="C:\\", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed")
    mock_usage = MagicMock(percent=75.0, total=100 * 1024**3, free=25 * 1024**3)
    with patch("psutil.disk_partitions", return_value=[mock_part]), \
         patch("psutil.disk_usage", return_value=mock_usage):
        res = disco_ops.limpar_disco(executar=True, limite_pct=80)
        assert res["executado"] is False
        assert "abaixo do limite" in res["motivo"].lower()


def test_limpar_disco_nunca_apaga_cookies_ou_login_data(tmp_path):
    # Review Focus #3: browser profile files are protected
    chrome_dir = tmp_path / "User Data" / "Default"
    cache_dir = chrome_dir / "Cache" / "Cache_Data"
    cache_dir.mkdir(parents=True)
    (cache_dir / "f_0001").write_bytes(b"disposable cache content")

    cookie_file = chrome_dir / "Cookies"
    cookie_file.write_bytes(b"sensitive login cookie")

    with patch("disco_ops._diretorios_cache_navegadores", return_value=[cache_dir]):
        res = disco_ops._limpar_caches_navegadores(simular=False)
        assert not (cache_dir / "f_0001").exists()
        assert cookie_file.exists()


def test_converter_imagens_webp_para_png(tmp_path):
    webp_path = tmp_path / "imagem.webp"
    img = Image.new("RGBA", (10, 10), color=(255, 0, 0, 128))
    img.save(webp_path, "WEBP")

    with patch("disco_ops.desfazer.registrar"):
        res = disco_ops.converter_imagens(str(webp_path), formato="png", apagar_original=False)
        assert res["convertidos"] == 1
        png_path = tmp_path / "imagem.png"
        assert png_path.exists()
        assert webp_path.exists()


def test_arquivar_projetos_antigos_compacta_em_tar_zst(tmp_path):
    proj_dir = tmp_path / "projeto_antigo"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_bytes(b"print('hello antigo')")

    agora = time.time()
    seis_meses_atras = agora - (190 * 86400)
    os.utime(proj_dir / "main.py", (seis_meses_atras, seis_meses_atras))
    os.utime(proj_dir, (seis_meses_atras, seis_meses_atras))

    with patch("disco_ops.send2trash") as mock_trash, patch("disco_ops.desfazer.registrar"):
        res = disco_ops.arquivar_projetos_antigos(pasta=str(tmp_path), meses=6, executar=True)
        assert res["compactados"] == 1
        mock_trash.assert_called_once()
        ext = ".tar.zst" if sys.version_info >= (3, 14) else ".tar.gz"
        archive_path = tmp_path / f"projeto_antigo{ext}"
        assert archive_path.exists()
