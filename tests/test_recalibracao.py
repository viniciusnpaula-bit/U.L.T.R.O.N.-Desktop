"""Testes da recalibração automática do limiar de voz.

Nada aqui abre o microfone de verdade: `calibrar` é substituído por um contador,
então os testes rodam em qualquer máquina, inclusive sem áudio.
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import voz


def _ouvido():
    """Ouvido sem __init__ (não toca em hardware) com o estado da recalibração."""
    ou = voz.Ouvido.__new__(voz.Ouvido)
    ou.limiar = 400.0
    ou.capturando = threading.Event()
    ou.device_index = None
    ou.device_id = None
    ou._ultimo_comando_ok = time.time()
    ou._nao_entendi_consecutivos = 0
    ou.chamadas_calibrar = 0
    return ou


class RecalibracaoTests(unittest.TestCase):
    def setUp(self):
        self._falando_original = voz.falando.is_set()
        voz.falando.clear()

    def tearDown(self):
        if self._falando_original:
            voz.falando.set()
        else:
            voz.falando.clear()

    def test_nao_recalibra_logo_apos_comando(self):
        ou = _ouvido()
        self.assertFalse(ou.precisa_recalibrar())

    def test_recalibra_apos_tres_nao_entendi_seguidos(self):
        ou = _ouvido()
        ou.notificar_nao_entendido()
        ou.notificar_nao_entendido()
        self.assertFalse(ou.precisa_recalibrar())
        ou.notificar_nao_entendido()
        self.assertTrue(ou.precisa_recalibrar())

    def test_comando_reconhecido_zera_o_contador(self):
        ou = _ouvido()
        for _ in range(3):
            ou.notificar_nao_entendido()
        ou.notificar_comando_reconhecido()
        self.assertFalse(ou.precisa_recalibrar())
        self.assertEqual(ou._nao_entendi_consecutivos, 0)

    def test_recalibra_apos_tempo_sem_comando(self):
        ou = _ouvido()
        ou._ultimo_comando_ok = time.time() - (ou.RECALIBRAR_SEM_COMANDO_SEG + 1)
        self.assertTrue(ou.precisa_recalibrar())

    def test_nao_recalibra_enquanto_o_ultron_fala(self):
        ou = _ouvido()
        ou._ultimo_comando_ok = time.time() - (ou.RECALIBRAR_SEM_COMANDO_SEG + 1)

        def calibrar_falso():
            ou.chamadas_calibrar += 1

        ou.calibrar = calibrar_falso
        voz.falando.set()
        self.assertFalse(ou.recalibrar_se_necessario())
        self.assertEqual(ou.chamadas_calibrar, 0)

    def test_recalibra_e_reinicia_gatilhos_quando_pode(self):
        ou = _ouvido()
        ou._ultimo_comando_ok = time.time() - (ou.RECALIBRAR_SEM_COMANDO_SEG + 1)

        def calibrar_falso():
            ou.chamadas_calibrar += 1
            # o calibrar de verdade reinicia os gatilhos; reproduzimos aqui
            ou._ultimo_comando_ok = time.time()
            ou._nao_entendi_consecutivos = 0

        ou.calibrar = calibrar_falso
        self.assertTrue(ou.recalibrar_se_necessario())
        self.assertEqual(ou.chamadas_calibrar, 1)
        self.assertFalse(ou.precisa_recalibrar())

    def test_calibrar_reinicia_gatilhos(self):
        """Uma calibração manual (ou a do início) não pode ser refeita em seguida."""
        ou = _ouvido()
        ou._nao_entendi_consecutivos = 99
        ou._ultimo_comando_ok = 0.0

        # calibrar() de verdade só mexe em _ultimo_comando_ok / contador no fim;
        # substituímos a captura de áudio para não abrir o microfone.
        import numpy as np

        class _FakeSd:
            @staticmethod
            def rec(*args, **kwargs):
                return np.zeros((24000, 1), dtype=np.int16)

            @staticmethod
            def wait():
                return None

        original = voz.sd
        voz.sd = _FakeSd
        try:
            ou.calibrar()
        finally:
            voz.sd = original
        self.assertFalse(ou.precisa_recalibrar())
        self.assertEqual(ou._nao_entendi_consecutivos, 0)


if __name__ == "__main__":
    unittest.main()
