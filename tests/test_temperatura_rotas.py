"""Testes de roteamento local para temperatura do dia (clima) vs temperatura do PC (hardware)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TemperaturaRotasTests(unittest.TestCase):
    def setUp(self):
        import seguranca
        seguranca.parada.clear()

    def test_temperatura_generica_e_do_dia_vao_para_clima_sem_chamar_llm(self):
        import cerebro
        import config

        antiga_cidade = config.CIDADE
        config.CIDADE = "Campinas"
        try:
            self.assertEqual(cerebro._acao_rapida("qual a temperatura?"), "clima:Campinas")
            self.assertEqual(cerebro._acao_rapida("ver a temperatura do dia"), "clima:Campinas")
            self.assertEqual(cerebro._acao_rapida("temperatura agora"), "clima:Campinas")
            self.assertEqual(cerebro._acao_rapida("temperatura em Curitiba"), "clima:curitiba")

            chamadas = []

            def fake_executar(nome, args, _confirmar, _origem):
                chamadas.append((nome, args))
                return "Campinas: agora 26°C."

            with mock.patch("ferramentas.executar", side_effect=fake_executar), \
                 mock.patch("cerebro._chamar", side_effect=AssertionError("Não deveria chamar LLM")):
                resp = cerebro.processar("ver a temperatura", lambda _m, _p: True, "desktop")

            self.assertIn("26°C", resp)
            self.assertEqual(chamadas, [("clima", {"cidade": "Campinas"})])
        finally:
            config.CIDADE = antiga_cidade

    def test_temperatura_explicita_de_hardware_vai_para_pc_sem_chamar_llm_nem_internet(self):
        import cerebro

        self.assertEqual(cerebro._acao_rapida("ver a temperatura do pc"), "temperatura_pc")
        self.assertEqual(cerebro._acao_rapida("como está a temperatura da cpu?"), "temperatura_pc")
        self.assertEqual(cerebro._acao_rapida("meu notebook está aquecendo?"), "temperatura_pc")

        chamadas = []

        def fake_executar(nome, args, _confirmar, _origem):
            chamadas.append((nome, args))
            return "Temperatura estável: 54.0°C (segura abaixo de 82°C)."

        with mock.patch("ferramentas.executar", side_effect=fake_executar), \
             mock.patch("cerebro._chamar", side_effect=AssertionError("Não deveria chamar LLM")):
            resp = cerebro.processar("qual a temperatura da CPU?", lambda _m, _p: True, "desktop")

        self.assertIn("54.0°C", resp)
        self.assertEqual(chamadas, [("verificar_protecao_termica", {"simular": True})])

    def test_info_sistema_inclui_temperatura_quando_disponivel(self):
        import ferramentas
        import processos_ops

        with mock.patch.object(processos_ops, "_obter_temperatura_cpu", return_value=61.5):
            res = ferramentas.executar("info_sistema", {}, lambda _m, _p: True, "desktop")
        self.assertIn("Temperatura da CPU 61.5°C", res)


if __name__ == "__main__":
    unittest.main()
