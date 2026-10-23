import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cerebro


class InterpretacaoIncertaTests(unittest.TestCase):
    def test_fala_unica_nunca_pede_confirmacao(self):
        r = cerebro.interpretacao_incerta("abre o navegador", ["abre o navegador"])
        self.assertFalse(r["confirmar"])

    def test_verbos_diferentes_pedem_confirmacao(self):
        r = cerebro.interpretacao_incerta("apaga o arquivo", ["apaga o arquivo", "apagar o arquivo"])
        self.assertTrue(r["confirmar"])
        self.assertIn("apaga", r["motivo"])

    def test_verbo_de_consequencia_pede_confirmacao(self):
        r = cerebro.interpretacao_incerta("desliga o pc", ["desliga o pc", "desligar o pc"])
        self.assertTrue(r["confirmar"])

    def test_assunto_neutro_nao_pede_confirmacao(self):
        r = cerebro.interpretacao_incerta("qual a previsão do tempo", ["qual a previsão do tempo", "qual a provisão do tempo"])
        self.assertFalse(r["confirmar"])

    def test_comando_simples_nao_pede_confirmacao(self):
        r = cerebro.interpretacao_incerta("fecha o chrome", ["fecha o chrome"])
        self.assertFalse(r["confirmar"])


if __name__ == "__main__":
    unittest.main()
