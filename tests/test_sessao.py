import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sessao


class SessaoTests(unittest.TestCase):
    def setUp(self):
        sessao.bloquear()

    def tearDown(self):
        sessao.bloquear()

    def test_comeca_bloqueada(self):
        self.assertEqual(sessao.estado(), {"desbloqueada": False, "metodo": None, "desde": None,
                                          "ultima_atividade": None})

    def test_desbloquear_hello_e_pin(self):
        for metodo in ("hello", "pin"):
            estado = sessao.desbloquear(metodo)
            self.assertTrue(estado["desbloqueada"])
            self.assertEqual(estado["metodo"], metodo)
            self.assertIsInstance(estado["desde"], float)
            sessao.bloquear()

    def test_metodo_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            sessao.desbloquear("senha")
        self.assertFalse(sessao.estado()["desbloqueada"])

    def test_estado_devolve_copia(self):
        estado = sessao.estado()
        estado["desbloqueada"] = True
        estado["metodo"] = "pin"
        self.assertFalse(sessao.estado()["desbloqueada"])
        self.assertIsNone(sessao.estado()["metodo"])

    def test_bloquear_volta_ao_inicio(self):
        sessao.desbloquear("pin")
        sessao.bloquear()
        self.assertEqual(sessao.estado(), {"desbloqueada": False, "metodo": None, "desde": None,
                                          "ultima_atividade": None})

    def test_desbloquear_marca_atividade(self):
        antes = time.time()
        estado = sessao.desbloquear("pin")
        self.assertGreaterEqual(estado["ultima_atividade"], antes)
        self.assertEqual(sessao.ultima_atividade(), estado["ultima_atividade"])

    def test_tocar_atualiza_a_atividade(self):
        sessao.desbloquear("pin")
        antiga = sessao.ultima_atividade()
        time.sleep(0.01)
        sessao.tocar()
        self.assertGreater(sessao.ultima_atividade(), antiga)


if __name__ == "__main__":
    unittest.main()
