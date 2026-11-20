"""Testes para o worker de segundo plano vigilancia_processos.py."""
import time
import pytest
from unittest.mock import patch, MagicMock

import vigilancia_processos


def test_vigilancia_processos_iniciar_e_parar():
    watcher = vigilancia_processos.VigilanciaProcessos()
    assert watcher.ativo is False
    watcher.iniciar()
    assert watcher.ativo is True
    st = watcher.status()
    assert st["ativo"] is True
    watcher.parar()
    assert watcher.ativo is False


def test_vigilancia_processos_respeita_modo_admin():
    watcher = vigilancia_processos.VigilanciaProcessos()
    with patch("seguranca.modo_admin_ativo", return_value=False), \
         patch("processos_ops.encerrar_processos_travados") as mock_travados:
        
        watcher._executar_rotina_travados()
        mock_travados.assert_not_called()


def test_vigilancia_processos_executa_quando_admin():
    watcher = vigilancia_processos.VigilanciaProcessos()
    with patch("seguranca.modo_admin_ativo", return_value=True), \
         patch("processos_ops.carregar_config_bloco2", return_value={"matar_travados_ativo": True}), \
         patch("processos_ops.encerrar_processos_travados", return_value={"encerrados": 2}) as mock_travados:
        
        watcher._executar_rotina_travados()
        mock_travados.assert_called_once()
        assert "encerrados: 2" in watcher.status()["ultimo_relatorio"]


def test_loop_processos_le_config_uma_vez_por_ciclo_e_espera_adaptativo():
    watcher = vigilancia_processos.VigilanciaProcessos()

    def fake_wait(timeout=None):
        watcher._parar_evento.set()
        return True

    with patch("seguranca.modo_admin_ativo", return_value=True), \
         patch("processos_ops.carregar_config_bloco2", return_value={}) as mock_cfg, \
         patch.object(watcher, "_executar_rotina_janela_ativa"), \
         patch.object(watcher, "_executar_rotina_termica"), \
         patch.object(watcher, "_executar_rotina_energia"), \
         patch.object(watcher, "_executar_rotina_travados"), \
         patch.object(watcher, "_executar_rotina_abas"), \
         patch.object(watcher, "_executar_rotina_ram"), \
         patch.object(watcher._parar_evento, "wait", side_effect=fake_wait) as mock_wait:
        watcher._loop()
        mock_cfg.assert_called_once()
        mock_wait.assert_called_once()
        assert 2.0 <= mock_wait.call_args.kwargs["timeout"] <= 15.0


def test_loop_processos_nao_le_config_quando_admin_inativo():
    watcher = vigilancia_processos.VigilanciaProcessos()

    def fake_wait(timeout=None):
        watcher._parar_evento.set()
        return True

    with patch("seguranca.modo_admin_ativo", return_value=False), \
         patch("processos_ops.carregar_config_bloco2") as mock_cfg, \
         patch.object(watcher._parar_evento, "wait", side_effect=fake_wait) as mock_wait:
        watcher._loop()
        mock_cfg.assert_not_called()
        mock_wait.assert_called_once_with(timeout=5.0)
