"""Testes do VAD (detecção de atividade de voz): distingue fala de silêncio."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np


class VadTests(unittest.TestCase):
    def setUp(self):
        import voz
        self.ouvido = voz.Ouvido.__new__(voz.Ouvido)
        self.ouvido.limiar = 400.0
        self.ouvido.vad = voz._Vad()

    def test_silencio_nao_e_voz(self):
        """Um bloco de silêncio puro nunca é considerado fala pelo VAD."""
        silencio = np.zeros(1600, dtype=np.int16)
        self.assertFalse(self.ouvido._eh_voz(silencio))

    def test_seno_na_faixa_da_voz_e_voz(self):
        """Um tom de 440 Hz (dentro da banda da fala) é detectado como voz."""
        t = np.arange(1600) / 16000
        tom = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        self.assertTrue(self.ouvido._eh_voz(tom))

    def test_ruido_agudo_nao_e_voz(self):
        """Ruído de alta frequência (fora da banda da fala) não é voz."""
        t = np.arange(1600) / 16000
        agudo = (0.3 * np.sin(2 * np.pi * 9000 * t) * 32767).astype(np.int16)
        self.assertFalse(self.ouvido._eh_voz(agudo))

    def test_ruido_grave_nao_e_voz(self):
        """Ruído de baixa frequência (fora da banda da fala) não é voz."""
        t = np.arange(1600) / 16000
        grave = (0.3 * np.sin(2 * np.pi * 100 * t) * 32767).astype(np.int16)
        self.assertFalse(self.ouvido._eh_voz(grave))

    def test_ouvido_tem_vad(self):
        import voz
        self.assertIsNotNone(self.ouvido.vad)

    def test_limiar_calibrado_controla_o_corte(self):
        """A recalibração só tem valor se o VAD respeitar o limiar calibrado."""
        t = np.arange(1600) / 16000
        tom = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        self.ouvido.limiar = 400.0        # sala silenciosa: fala normal passa
        self.assertTrue(self.ouvido._eh_voz(tom))
        self.ouvido.limiar = 30000.0      # sala muito ruidosa: o mesmo tom não passa
        self.assertFalse(self.ouvido._eh_voz(tom))


if __name__ == "__main__":
    unittest.main()
