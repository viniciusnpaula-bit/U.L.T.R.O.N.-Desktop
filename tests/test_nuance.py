import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nuance


class LeituraEmocionalTests(unittest.TestCase):
    """A leitura precisa ser objetiva: sinal no texto, não adivinhação."""

    def test_texto_sem_sinal_e_neutro(self):
        leitura = nuance.analisar("que dia lindo para organizar a pasta")
        self.assertEqual(leitura["emocao"], "neutro")
        self.assertEqual(leitura["intensidade"], 0)
        self.assertEqual(leitura["confianca"], 0.0)
        self.assertEqual(leitura["sinais"], [])

    def test_frustracao_composta_nao_e_anulada_pela_negacao(self):
        leitura = nuance.analisar("não funciona de novo")
        self.assertEqual(leitura["emocao"], "frustrado")
        self.assertEqual(leitura["intensidade"], 3)
        self.assertIn("não funciona", leitura["sinais"])

    def test_negacao_imediata_derruba_o_termo(self):
        leitura = nuance.analisar("não estou triste")
        self.assertEqual(leitura["emocao"], "neutro")

    def test_intensificador_e_exclamacao_aumentam_o_peso(self):
        leve = nuance.analisar("estou irritado")
        forte = nuance.analisar("estou MUITO irritado com isso!!")
        self.assertEqual(leitura_emocao(leve), "irritado")
        self.assertGreater(forte["confianca"], leve["confianca"])
        self.assertGreaterEqual(forte["intensidade"], leve["intensidade"])

    def test_pergunta_repetida_pesa_para_confusao(self):
        leitura = nuance.analisar("como assim??? não entendi nada")
        self.assertEqual(leitura["emocao"], "confuso")
        self.assertEqual(leitura["intensidade"], 3)

    def test_urgencia_sem_emocao_continua_sendo_urgente(self):
        leitura = nuance.analisar("preciso disso agora!")
        self.assertTrue(leitura["urgente"])
        self.assertEqual(leitura["emocao"], "neutro")

    def test_termo_composto_nao_conta_duas_vezes(self):
        leitura = nuance.analisar("muito obrigado")
        self.assertEqual(leitura["emocao"], "grato")
        self.assertEqual(leitura["intensidade"], 2)

        raiva = nuance.analisar("que raiva")
        self.assertEqual(raiva["emocao"], "irritado")
        self.assertEqual(raiva["intensidade"], 2)

    def test_rotulo_curto(self):
        self.assertEqual(nuance.rotulo({"emocao": "neutro", "intensidade": 0}), "neutro")
        self.assertEqual(
            nuance.rotulo({"emocao": "frustrado", "intensidade": 3}), "frustrado (forte)")
        self.assertEqual(
            nuance.rotulo({"emocao": "grato", "intensidade": 1}), "grato (leve)")

    def test_instrucao_so_aparece_quando_ha_sinal(self):
        self.assertEqual(nuance.instrucao("abra a pasta de downloads"), "")
        texto = nuance.instrucao("não funciona de novo")
        self.assertIn("frustrado", texto)
        self.assertIn("Ajuste o tom", texto)

    def test_instrucao_marca_urgencia(self):
        texto = nuance.instrucao("estou ansioso e preciso disso agora")
        self.assertIn("ansioso", texto)
        self.assertIn("urgência", texto)


def leitura_emocao(leitura):
    return leitura["emocao"]


if __name__ == "__main__":
    unittest.main()
