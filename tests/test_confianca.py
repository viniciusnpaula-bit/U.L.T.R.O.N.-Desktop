"""Testes do porteiro de confiança: confirmar só quando a transcrição inspira dúvida."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cerebro
import config


class ConfiancaTests(unittest.TestCase):
    def test_baixa_confirma_mesmo_sem_alternativas(self):
        r = cerebro.interpretacao_incerta(
            "qual a previsão do tempo", ["qual a previsão do tempo"],
            {"nivel": "baixa", "motivo": "áudio com pouca clareza"})
        self.assertTrue(r["confirmar"])
        self.assertIn("clareza", r["motivo"])
        self.assertEqual(r["opcoes"], ["qual a previsão do tempo"])

    def test_baixa_sem_texto_usa_a_fala_como_opcao(self):
        r = cerebro.interpretacao_incerta(
            "abrir o chrome", [], {"nivel": "baixa", "motivo": "ruído"})
        self.assertTrue(r["confirmar"])
        self.assertEqual(r["opcoes"], ["abrir o chrome"])

    def test_media_com_verbo_de_acao_confirma(self):
        r = cerebro.interpretacao_incerta(
            "abrir o crono", ["abrir o crono"], {"nivel": "media"})
        self.assertTrue(r["confirmar"])

    def test_media_com_verbo_no_meio_confirma(self):
        r = cerebro.interpretacao_incerta(
            "quero fechar o chrome", ["quero fechar o chrome"], {"nivel": "media"})
        self.assertTrue(r["confirmar"])

    def test_media_sem_verbo_de_acao_nao_confirma(self):
        r = cerebro.interpretacao_incerta(
            "qual a previsão do tempo", ["qual a previsão do tempo"],
            {"nivel": "media"})
        self.assertFalse(r["confirmar"])

    def test_alta_nao_confirma(self):
        r = cerebro.interpretacao_incerta(
            "abrir o chrome", ["abrir o chrome"], {"nivel": "alta"})
        self.assertFalse(r["confirmar"])

    def test_sem_confianca_mantem_comportamento_antigo(self):
        r = cerebro.interpretacao_incerta("abre o navegador", ["abre o navegador"])
        self.assertFalse(r["confirmar"])

    def test_conferir_nunca_desliga_confirmacao(self):
        with patch.object(config, "VOZ_CONFERIR", "nunca", create=True):
            r = cerebro.interpretacao_incerta(
                "abrir o chrome", ["abrir o chrome"],
                {"nivel": "baixa", "motivo": "ruído"})
        self.assertFalse(r["confirmar"])

    def test_conferir_sempre_confirma_ate_pergunta(self):
        with patch.object(config, "VOZ_CONFERIR", "sempre", create=True):
            r = cerebro.interpretacao_incerta(
                "que horas são", ["que horas são"], {"nivel": "alta"})
        self.assertTrue(r["confirmar"])

    def test_alternativas_continuam_valendo_sem_confianca(self):
        r = cerebro.interpretacao_incerta(
            "apaga o arquivo", ["apaga o arquivo", "apagar o arquivo"])
        self.assertTrue(r["confirmar"])


if __name__ == "__main__":
    unittest.main()
