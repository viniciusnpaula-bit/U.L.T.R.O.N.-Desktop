"""PIN com hash PBKDF2: validação, compatibilidade com texto e gravação no .env."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import seguranca

_spec = importlib.util.spec_from_file_location(
    "definir_pin", Path(__file__).resolve().parents[1] / "tools" / "definir_pin.py")
definir_pin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(definir_pin)


class PinHashTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, config, "PIN", config.PIN)
        self.addCleanup(setattr, config, "PIN_HASH", getattr(config, "PIN_HASH", ""))
        config.PIN = ""
        config.PIN_HASH = ""

    def test_hash_correto_e_errado(self):
        config.PIN_HASH = definir_pin.gerar_hash("4321")
        self.assertTrue(seguranca.pin_valido("4321"))
        self.assertTrue(seguranca.pin_valido(" 4321 "))
        self.assertFalse(seguranca.pin_valido("0000"))
        self.assertFalse(seguranca.pin_valido(""))
        self.assertTrue(seguranca.pin_configurado())

    def test_hash_tem_precedencia_sobre_texto(self):
        config.PIN = "1111"
        config.PIN_HASH = definir_pin.gerar_hash("4321")
        self.assertTrue(seguranca.pin_valido("4321"))
        self.assertFalse(seguranca.pin_valido("1111"))

    def test_fallback_texto_continua_funcionando(self):
        config.PIN = "4321"
        self.assertTrue(seguranca.pin_valido("4321"))
        self.assertFalse(seguranca.pin_valido("0000"))

    def test_hash_invalido_nao_quebra_nem_aceita(self):
        for ruim in ("lixo", "pbkdf2_sha256$x$y$z", "pbkdf2_sha256$1$!!!$???"):
            config.PIN_HASH = ruim
            self.assertFalse(seguranca.pin_valido("4321"))

    def test_sem_pin_nenhum(self):
        self.assertFalse(seguranca.pin_configurado())
        self.assertFalse(seguranca.pin_valido("4321"))

    def test_redigir_mascara_o_hash(self):
        config.PIN_HASH = definir_pin.gerar_hash("4321")
        self.assertNotIn(config.PIN_HASH, seguranca.redigir(f"hash={config.PIN_HASH}"))


class DefinirPinTests(unittest.TestCase):
    def test_gravar_hash_remove_o_pin_em_texto(self):
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            env = Path(pasta) / ".env"
            env.write_text("NOME_USUARIO=senhor\nULTRON_PIN=4321\nOUTRA=1\n", encoding="utf-8")
            valor = definir_pin.gerar_hash("4321")
            definir_pin.gravar_hash(env, valor)
            texto = env.read_text(encoding="utf-8")
            linhas = [linha.split("=", 1)[0] for linha in texto.splitlines()]
            self.assertNotIn("ULTRON_PIN", linhas)
            self.assertIn(f"ULTRON_PIN_HASH={valor}", texto)
            self.assertIn("NOME_USUARIO=senhor", texto)
            self.assertIn("OUTRA=1", texto)
            # E o valor gravado valida o mesmo PIN.
            with patch.object(config, "PIN_HASH", valor):
                self.assertTrue(seguranca.pin_valido("4321"))


if __name__ == "__main__":
    unittest.main()
