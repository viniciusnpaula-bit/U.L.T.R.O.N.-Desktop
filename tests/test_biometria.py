import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import biometria


class Codigo(int):
    """Imita o IntEnum do WinRT (AVAILABLE/VERIFIED = 0)."""


def api(disponibilidade=0, verificacao=0, iniciar=None):
    class Verificador:
        @staticmethod
        async def check_availability_async():
            return Codigo(disponibilidade)

        @staticmethod
        async def request_verification_async(_motivo):
            return Codigo(verificacao)

    class Disponibilidade:
        AVAILABLE = 0

    return (Verificador, Disponibilidade, None, iniciar or (lambda: None))


class BiometriaTests(unittest.TestCase):
    def tearDown(self):
        if biometria._TRAVA.locked():
            biometria._TRAVA.release()

    def test_sem_winrt_devolve_indisponivel_sem_levantar(self):
        with patch.object(biometria, "_winrt", return_value=None):
            self.assertEqual(biometria.disponivel(),
                             {"disponivel": False, "motivo": "Windows Hello indisponível"})
            self.assertFalse(biometria.verificar())

    def test_disponibilidade_mapeia_os_codigos(self):
        casos = {
            0: (True, "Windows Hello pronto"),
            1: (False, "Nenhum sensor de Windows Hello neste PC"),
            2: (False, "Windows Hello não está configurado para este usuário"),
            3: (False, "Windows Hello desativado por política"),
            4: (False, "Sensor do Windows Hello ocupado"),
            9: (False, "Windows Hello indisponível"),
        }
        for codigo, esperado in casos.items():
            with patch.object(biometria, "_winrt", return_value=api(disponibilidade=codigo)):
                self.assertEqual(biometria.disponivel(),
                                 {"disponivel": esperado[0], "motivo": esperado[1]}, codigo)

    def test_verificar_so_aceita_verified(self):
        with patch.object(biometria, "_winrt", return_value=api(verificacao=0)):
            self.assertTrue(biometria.verificar())
        for codigo in (1, 4, 5, 6):
            with patch.object(biometria, "_winrt", return_value=api(verificacao=codigo)):
                self.assertFalse(biometria.verificar(), codigo)

    def test_excecao_do_winrt_vira_false(self):
        class Quebrado:
            @staticmethod
            async def request_verification_async(_motivo):
                raise RuntimeError("winrt explodiu")

        with patch.object(biometria, "_winrt", return_value=(Quebrado, None, None, lambda: None)):
            self.assertFalse(biometria.verificar())

    def test_init_apartment_que_levanta_nao_impede_a_chamada(self):
        def iniciar():
            raise OSError("já inicializado")

        with patch.object(biometria, "_winrt", return_value=api(verificacao=0, iniciar=iniciar)):
            self.assertTrue(biometria.verificar())

    def test_prompt_concorrente_devolve_busy(self):
        biometria._TRAVA.acquire()
        with self.assertRaises(biometria.Ocupado):
            biometria.verificar()

    def test_prazo_estourado_nao_prende_a_thread(self):
        class Lento:
            @staticmethod
            async def request_verification_async(_motivo):
                await asyncio.sleep(0.5)
                return Codigo(0)

        with patch.object(biometria, "_winrt", return_value=(Lento, None, None, lambda: None)), \
                patch.object(biometria, "PRAZO_S", 0.05):
            inicio = time.monotonic()
            self.assertFalse(biometria.verificar())
            self.assertLess(time.monotonic() - inicio, 0.4)


if __name__ == "__main__":
    unittest.main()
