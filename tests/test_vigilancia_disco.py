import time
import pytest
from unittest.mock import patch, MagicMock
from vigilancia_disco import VigilanciaDisco


def test_vigilancia_disco_lifecycle():
    worker = VigilanciaDisco()
    assert worker.ativo is False
    worker.iniciar()
    assert worker.ativo is True
    st = worker.status()
    assert "ativo" in st
    assert st["ativo"] is True
    worker.parar()
    assert worker.ativo is False


def test_vigilancia_pausa_quando_sessao_bloqueada():
    worker = VigilanciaDisco()
    with patch("seguranca.modo_admin_ativo", return_value=False), \
         patch("disco_ops.organizar_pdf_downloads") as mock_pdf:
        worker._executar_rotina_downloads()
        mock_pdf.assert_not_called()


def test_vigilancia_executa_quando_admin_ativo():
    worker = VigilanciaDisco()
    with patch("seguranca.modo_admin_ativo", return_value=True), \
         patch("disco_ops.organizar_pdf_downloads") as mock_pdf:
        worker._executar_rotina_downloads()
        mock_pdf.assert_called_once()


def test_loop_disco_le_config_uma_vez_por_ciclo_e_espera_adaptativo():
    worker = VigilanciaDisco()

    def fake_wait(timeout=None):
        worker._parar_evento.set()
        return True

    with patch("seguranca.modo_admin_ativo", return_value=True), \
         patch("disco_ops.carregar_config_bloco1", return_value={}) as mock_cfg, \
         patch.object(worker, "_executar_rotina_downloads"), \
         patch.object(worker, "_executar_rotina_prints"), \
         patch.object(worker, "_executar_rotina_usb"), \
         patch.object(worker, "_executar_rotina_disco"), \
         patch.object(worker._parar_evento, "wait", side_effect=fake_wait) as mock_wait:
        worker._loop()
        mock_cfg.assert_called_once()
        mock_wait.assert_called_once()
        assert 2.0 <= mock_wait.call_args.kwargs["timeout"] <= 10.0


def test_loop_disco_nao_le_config_quando_admin_inativo():
    worker = VigilanciaDisco()

    def fake_wait(timeout=None):
        worker._parar_evento.set()
        return True

    with patch("seguranca.modo_admin_ativo", return_value=False), \
         patch("disco_ops.carregar_config_bloco1") as mock_cfg, \
         patch.object(worker._parar_evento, "wait", side_effect=fake_wait) as mock_wait:
        worker._loop()
        mock_cfg.assert_not_called()
        mock_wait.assert_called_once_with(timeout=5.0)
