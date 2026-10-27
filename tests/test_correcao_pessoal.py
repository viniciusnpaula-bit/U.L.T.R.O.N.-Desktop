"""Testes da detecção de correção pessoal por voz ("não, eu disse X")."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class DetectarCorrecaoTests(unittest.TestCase):
    def test_nao_eu_disse(self):
        self.assertEqual(main._detectar_correcao_pessoal("não, eu disse Rocket League"),
                         (None, "Rocket League"))

    def test_sem_virgula(self):
        self.assertEqual(main._detectar_correcao_pessoal("nao eu disse Rocket League"),
                         (None, "Rocket League"))

    def test_eu_disse_sozinho(self):
        self.assertEqual(main._detectar_correcao_pessoal("eu disse Spotify"),
                         (None, "Spotify"))

    def test_corrigir_para(self):
        self.assertEqual(main._detectar_correcao_pessoal("corrigir para Spotify"),
                         (None, "Spotify"))

    def test_nao_foi_x_foi_y(self):
        self.assertEqual(main._detectar_correcao_pessoal("não foi spotifai foi Spotify"),
                         ("spotifai", "Spotify"))

    def test_comando_normal_nao_e_correcao(self):
        for frase in ("abre o chrome", "fecha o spotify", "que horas são"):
            self.assertIsNone(main._detectar_correcao_pessoal(frase))

    def test_texto_vazio(self):
        self.assertIsNone(main._detectar_correcao_pessoal(""))


if __name__ == "__main__":
    unittest.main()
