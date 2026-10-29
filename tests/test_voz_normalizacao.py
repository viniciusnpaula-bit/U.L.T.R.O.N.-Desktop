"""Normalização do PCM antes do STT: fala baixa vira nível normal, silêncio fica silêncio."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

import voz


def _rms(pcm):
    amostras = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(amostras ** 2)))


def _seno(rms, amostras=1600, freq=440):
    amplitude = rms * np.sqrt(2)
    t = np.arange(amostras) / 16000
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)


class NormalizarPcmTests(unittest.TestCase):
    def test_silencio_volta_intacto(self):
        silencio = np.zeros(1600, dtype=np.int16).tobytes()
        self.assertEqual(voz._normalizar_pcm(silencio), silencio)

    def test_ruido_abaixo_do_limiar_nao_e_amplificado(self):
        fraco = _seno(20).tobytes()
        self.assertEqual(voz._normalizar_pcm(fraco), fraco)

    def test_fala_baixa_chega_ao_alvo_sem_clipping(self):
        pcm = _seno(150).tobytes()
        self.assertLess(_rms(pcm), 200)
        saida = voz._normalizar_pcm(pcm)
        self.assertAlmostEqual(_rms(saida), 3000.0, delta=60.0)
        pico = int(np.max(np.abs(np.frombuffer(saida, dtype=np.int16))))
        self.assertLessEqual(pico, 30000)

    def test_fala_alta_nao_clipa(self):
        pcm = np.full(1600, 32000, dtype=np.int16).tobytes()
        saida = voz._normalizar_pcm(pcm)
        pico = int(np.max(np.abs(np.frombuffer(saida, dtype=np.int16))))
        self.assertLessEqual(pico, 30000)
        self.assertLess(_rms(saida), _rms(pcm))

    def test_bytes_impares_e_vazio(self):
        self.assertEqual(voz._normalizar_pcm(b""), b"")
        self.assertEqual(voz._normalizar_pcm(b"\x01"), b"\x01")

    def test_pico_max_limita_o_ganho(self):
        pcm = _seno(100).tobytes()
        saida = voz._normalizar_pcm(pcm, pico_max=400)
        pico = int(np.max(np.abs(np.frombuffer(saida, dtype=np.int16))))
        self.assertLessEqual(pico, 400)


class FatorDoLimiarTests(unittest.TestCase):
    def setUp(self):
        self.ouvido = voz.Ouvido.__new__(voz.Ouvido)
        self.ouvido.limiar = 1500.0
        self.ouvido.vad = voz._Vad()
        self.ouvido.vad.disponivel = False     # força o VAD em Python puro
        self.ouvido.vad._vad = None

    def test_fala_entre_035_e_05_do_limiar_e_captada(self):
        fala = _seno(600)                      # 525 < 600 < 750
        with patch.object(voz.config, "LIMIAR_VOZ_FATOR", 0.35):
            self.assertTrue(self.ouvido._eh_voz(fala))
        with patch.object(voz.config, "LIMIAR_VOZ_FATOR", 0.5):
            self.assertFalse(self.ouvido._eh_voz(fala))

    def test_ruido_estavel_nao_dispara(self):
        # RMS acima do corte de volume (525): só o espectro/ZCR pode rejeitar.
        ruido = np.random.default_rng(0).normal(0, 600, 1600).astype(np.int16)
        with patch.object(voz.config, "LIMIAR_VOZ_FATOR", 0.35):
            self.assertFalse(self.ouvido._eh_voz(ruido))

    def test_silencio_continua_silencio(self):
        with patch.object(voz.config, "LIMIAR_VOZ_FATOR", 0.35):
            self.assertFalse(self.ouvido._eh_voz(np.zeros(1600, dtype=np.int16)))


if __name__ == "__main__":
    unittest.main()
