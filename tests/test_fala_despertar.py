"""Testes da normalização do despertar: o Whisper gruda ou come o 'Ei, ULTRON'."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fala


class NormalizarDespertarTests(unittest.TestCase):
    def test_grudado_sem_l(self):
        self.assertEqual(
            fala.normalizar_despertar("EIUTRON, aumentar o volume em 20%."),
            "Ei, ULTRON, aumentar o volume em 20%.")

    def test_grudado_com_l(self):
        self.assertEqual(
            fala.normalizar_despertar("EIULTRON. Aumentar o volume em 20%."),
            "Ei, ULTRON. Aumentar o volume em 20%.")

    def test_e_ultron_sem_ei(self):
        self.assertEqual(
            fala.normalizar_despertar("E ULTRON, fechar o Spotify."),
            "Ei, ULTRON, fechar o Spotify.")

    def test_despertar_correto_fica_igual(self):
        for frase in ("Ei, ULTRON, abrir o Chrome!",
                      "Ei Ultron, abrir o Chrome.",
                      "EI, ULTRON, que horas são?"):
            self.assertEqual(fala.normalizar_despertar(frase), frase)

    def test_sem_despertar_nao_mexe(self):
        for frase in ("aumentar o volume em 20%.", "qual é a previsão do tempo?",
                      "o ultron é um assistente"):
            self.assertEqual(fala.normalizar_despertar(frase), frase)

    def test_despertar_sozinho_no_inicio(self):
        self.assertEqual(
            fala.normalizar_despertar("ULTRON, que horas são?"),
            "Ei, ULTRON, que horas são?")

    def test_variantes_conhecidas(self):
        for entrada in ("ULTROM, abrir o Chrome", "ALTRON, abrir o Chrome",
                        "ultra on, abrir o Chrome"):
            self.assertTrue(
                fala.normalizar_despertar(entrada).startswith("Ei, ULTRON"),
                entrada)

    def test_idempotente(self):
        uma = fala.normalizar_despertar("EIULTRON, abrir o Chrome")
        self.assertEqual(fala.normalizar_despertar(uma), uma)

    def test_despertar_dinamico_por_identidade(self):
        from unittest.mock import patch

        casos = [
            ("jarvis", "jarvis, que horas são?", "Ei, JARVIS, que horas são?", "ei jarvis", "ei ultron"),
            ("edith", "edit, abrir o chrome", "Ei, EDITH, abrir o chrome", "ei edit", "ei jarvis"),
            ("visao", "visão, qual a previsão?", "Ei, VISÃO, qual a previsão?", "ei visao", "ei ultron"),
        ]
        for pid, entrada, esperado, wake_ok, wake_outro in casos:
            with patch.object(fala, "perfil_despertar_ativo", return_value=pid):
                self.assertEqual(fala.normalizar_despertar(entrada), esperado)
                rx = fala.regex_wake()
                self.assertIsNotNone(rx.search(wake_ok))
                self.assertIsNone(rx.search(wake_outro))


if __name__ == "__main__":
    unittest.main()
