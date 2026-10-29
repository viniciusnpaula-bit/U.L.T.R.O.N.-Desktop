"""PIN do terminal: pedido com getpass, sem eco e sem aparecer na saída."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import main
import sessao


class DesbloqueioInicialTests(unittest.TestCase):
    def setUp(self):
        sessao.bloquear()
        self.addCleanup(sessao.bloquear)
        patcher = patch("biometria.disponivel", return_value={"disponivel": False})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pin_digitado_sem_eco_na_saida(self):
        with patch.object(config, "PIN", "1234"), \
                patch("getpass.getpass", return_value="1234") as pedir, \
                patch("seguranca.pin_valido", return_value=True), \
                redirect_stdout(io.StringIO()) as saida:
            self.assertTrue(main._desbloquear_inicial())
        pedir.assert_called_once()
        self.assertNotIn("1234", saida.getvalue())
        self.assertTrue(sessao.estado()["desbloqueada"])
        self.assertEqual(sessao.estado()["metodo"], "pin")

    def test_pin_errado_nao_vaza_nem_desbloqueia(self):
        with patch.object(config, "PIN", "1234"), \
                patch("getpass.getpass", return_value="0000"), \
                patch("seguranca.pin_valido", return_value=False), \
                redirect_stdout(io.StringIO()) as saida:
            self.assertFalse(main._desbloquear_inicial())
        self.assertNotIn("0000", saida.getvalue())
        self.assertIn("PIN incorreto", saida.getvalue())
        self.assertFalse(sessao.estado()["desbloqueada"])

    def test_sem_entrada_nao_quebra(self):
        with patch.object(config, "PIN", "1234"), \
                patch("getpass.getpass", side_effect=EOFError), \
                redirect_stdout(io.StringIO()):
            self.assertFalse(main._desbloquear_inicial())


if __name__ == "__main__":
    unittest.main()
