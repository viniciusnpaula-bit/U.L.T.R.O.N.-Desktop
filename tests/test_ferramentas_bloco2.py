"""Testes unitários para ferramentas do Bloco 2 em ferramentas.py."""
import pytest
from unittest.mock import patch

import ferramentas


def test_ferramentas_bloco2_registradas():
    ferramentas_esperadas = [
        "suspender_abas_navegador",
        "encerrar_apps_travados",
        "controlar_plano_energia",
        "otimizar_cpu_jogos_reunioes",
        "verificar_protecao_termica",
        "gerenciar_inicializacao_sistema",
        "otimizar_prioridade_janela",
        "purgar_memoria_ram",
        "ajustar_brilho_e_cor_tela",
        "desconectar_bluetooth_inativo",
        "configurar_bloco2",
    ]
    for nome in ferramentas_esperadas:
        assert nome in ferramentas.FERRAMENTAS, f"Ferramenta {nome} não registrada em ferramentas.FERRAMENTAS"


def test_executar_purgar_memoria_ram():
    with patch("processos_ops.limpar_ram_ociosa", return_value={
        "sucesso": True, "mb_liberados": 450.5, "processos_limpos": 8, "ram_livre_depois_mb": 2048.0
    }):
        out = ferramentas.executar("purgar_memoria_ram", {}, confirmar=lambda m, t=20: True, origem="desktop")
        assert "450.50 MB liberados" in out or "450.5" in out


def test_executar_suspender_abas_navegador():
    with patch("processos_ops.suspender_abas_pesadas", return_value={
        "sucesso": True, "suspensos": 3, "mb_economizados": 1500.0
    }):
        out = ferramentas.executar("suspender_abas_navegador", {"limite_mb": 500}, confirmar=lambda m, t=20: True, origem="desktop")
        assert "3 abas suspensas" in out or "1500" in out
