import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fala


class CorrecaoDeFalaTests(unittest.TestCase):
    def test_corrige_verbo_e_aplicativo_juntos(self):
        texto, trocas = fala.corrigir("abri o spotifai")
        self.assertEqual(texto, "abra o Spotify")
        self.assertEqual(trocas, [("abri", "abra"), ("spotifai", "Spotify")])

    def test_corrige_nome_parecido(self):
        self.assertEqual(fala.corrigir("fecha o crome")[0], "fecha o Chrome")
        self.assertEqual(fala.corrigir("abre o netflis")[0], "abre o Netflix")

    def test_nao_mexe_em_frase_comum(self):
        for frase in ("qual a previsão do tempo", "desliga o pc", "aumenta o volume"):
            self.assertEqual(fala.corrigir(frase), (frase, []))

    def test_verbo_no_meio_da_frase_e_passado_e_fica(self):
        self.assertEqual(fala.corrigir("eu abri o arquivo"), ("eu abri o arquivo", []))

    def test_sem_verbo_de_comando_nao_corrige_aplicativo(self):
        # "o crome" sozinho não é comando: melhor não adivinhar.
        self.assertEqual(fala.corrigir("o crome travou"), ("o crome travou", []))

    def test_normaliza_acento_para_comparar(self):
        self.assertEqual(fala.normalizar("Configurações"), "configuracoes")


class FuzzyComandoTests(unittest.TestCase):
    """Fuzzy matching generalizado: corrige comandos distorcidos, não só apps."""

    def test_corrige_palavra_distorcida_de_comando(self):
        texto, trocas = fala.resolver_comando("fexar aplicativo")
        self.assertEqual(texto, "fechar aplicativo")
        self.assertEqual(trocas, [("fexar", "fechar")])

    def test_corrige_arquibos_para_arquivos(self):
        self.assertEqual(fala.resolver_comando("organizar arquibos")[0], "organizar arquivos")

    def test_corrige_desfaser(self):
        self.assertEqual(fala.resolver_comando("desfaser")[0], "desfazer")

    def test_nao_mexe_em_palavra_legitima(self):
        for frase in ("abre o chrome", "que horas são", "toca uma música"):
            self.assertEqual(fala.resolver_comando(frase), (frase, []))

    def test_palavra_curta_nao_e_corrigida(self):
        # palavras com menos de 4 letras ficam como estão (evita "sim" -> "site")
        self.assertEqual(fala.resolver_comando("sim")[0], "sim")

    def test_conjugacao_e_plural_legitimos_ficam_como_estao(self):
        # "desliga" é prefixo de "desligar" e "musicas" de "musica": não é erro
        # de reconhecimento, é a forma certa da frase — não pode ser reescrita.
        for frase in ("desliga o pc", "toca uma musica", "abre os arquivos",
                      "aumenta o volume", "fecha a pasta"):
            self.assertEqual(fala.resolver_comando(frase), (frase, []))


if __name__ == "__main__":
    unittest.main()
