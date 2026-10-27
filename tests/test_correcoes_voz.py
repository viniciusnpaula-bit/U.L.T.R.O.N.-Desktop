"""Testes do dicionário de correções pessoais de voz."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import correcoes_voz


class CorrecoesPessoaisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "tmp_correcoes_voz.json"
        self._orig = correcoes_voz.ARQUIVO
        correcoes_voz.ARQUIVO = self.tmp
        if self.tmp.exists():
            self.tmp.unlink()

    def tearDown(self):
        correcoes_voz.ARQUIVO = self._orig
        if self.tmp.exists():
            self.tmp.unlink()

    def test_registrar_e_aplicar_correcao(self):
        correcoes_voz.registrar("rocket leage", "Rocket League")
        texto, trocas = correcoes_voz.aplicar("abre o rocket leage")
        self.assertEqual(texto, "abre o Rocket League")
        self.assertEqual(trocas, [("rocket leage", "Rocket League")])

    def test_aplicar_ignora_acento_e_maiusculas(self):
        correcoes_voz.registrar("spotifai", "Spotify")
        texto, _ = correcoes_voz.aplicar("toca o SPOTIFAI")
        self.assertEqual(texto, "toca o Spotify")

    def test_nao_corrige_o_que_nao_foi_ensinado(self):
        texto, trocas = correcoes_voz.aplicar("abre o spotify")
        self.assertEqual(texto, "abre o spotify")
        self.assertEqual(trocas, [])

    def test_texto_vazio(self):
        self.assertEqual(correcoes_voz.aplicar(""), ("", []))
        self.assertEqual(correcoes_voz.aplicar(None), ("", []))

    def test_registrar_vazio_nao_salva(self):
        correcoes_voz.registrar("", "x")
        correcoes_voz.registrar("x", "")
        self.assertEqual(correcoes_voz.carregar(), {})

    def test_correcao_de_uma_palavra_vale_em_outras_frases(self):
        # "abri o chrome" -> "abra o chrome": só "abri" mudou, então a correção
        # aprende a palavra e serve para qualquer comando.
        correcoes_voz.registrar_correcao("abri o chrome", "abra o chrome")
        self.assertEqual(correcoes_voz.aplicar("abri o firefox")[0], "abra o firefox")

    def test_correcao_de_trecho_nao_engole_o_verbo(self):
        # "abre o roquet league" -> "Rocket League": guarda só o trecho errado,
        # então o verbo continua no comando.
        correcoes_voz.registrar_correcao("abre o roquet league", "Rocket League")
        self.assertEqual(correcoes_voz.aplicar("abre o roquet league")[0],
                         "abre o Rocket League")

    def test_frases_sem_alinamento_guardam_o_par_inteiro(self):
        correcoes_voz.registrar_correcao("xyz abc", "algo totalmente diferente")
        self.assertIn("xyz abc", correcoes_voz.carregar())

    def test_correcao_igual_nao_grava_nada(self):
        correcoes_voz.registrar_correcao("abre o chrome", "Abre o Chrome")
        self.assertEqual(correcoes_voz.carregar(), {})

    def test_palavra_curta_nao_vira_regra_global(self):
        # Trocar só o artigo ("o" -> "a") não pode virar uma regra que muda
        # toda frase; nesse caso guarda o par inteiro.
        correcoes_voz.registrar_correcao("abre o chrome", "abre a chrome")
        tabela = correcoes_voz.carregar()
        self.assertNotIn("o", tabela)
        self.assertIn("abre o chrome", tabela)


if __name__ == "__main__":
    unittest.main()
