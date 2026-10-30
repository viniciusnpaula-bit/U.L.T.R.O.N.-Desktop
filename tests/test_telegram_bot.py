import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import telegram_bot


def pedido(exige_pin=False, ttl=5.0):
    return {"id": "c0ffee00", "acao": "desligar_pc", "risco": "ALTO",
            "expira": time.time() + ttl, "exige_pin": exige_pin}


class ConfirmadorTests(unittest.TestCase):
    def test_falha_ao_enviar_nega_imediatamente(self):
        def enviar(_texto, _cid):
            raise TimeoutError("telegram fora do ar")

        inicio = time.time()
        self.assertFalse(telegram_bot.Confirmador(enviar)("Confirmar?", pedido()))
        self.assertLess(time.time() - inicio, 2, "não pode esperar o timeout inteiro")
        self.assertNotIn("c0ffee00", telegram_bot._pendentes)

    def test_confirmar_pelo_botao_autoriza(self):
        with patch.object(telegram_bot.config, "TELEGRAM_USER_ID", 111):
            confirmar = telegram_bot.Confirmador(
                lambda _texto, cid: telegram_bot.resolver(111, cid, "s"))
            self.assertTrue(confirmar("Confirmar?", pedido()))

    def test_cancelar_pelo_botao_nega(self):
        with patch.object(telegram_bot.config, "TELEGRAM_USER_ID", 111):
            confirmar = telegram_bot.Confirmador(
                lambda _texto, cid: telegram_bot.resolver(111, cid, "n"))
            self.assertFalse(confirmar("Confirmar?", pedido()))

    def test_usuario_nao_autorizado_nao_resolve(self):
        with patch.object(telegram_bot.config, "TELEGRAM_USER_ID", 111):
            self.assertEqual(telegram_bot.resolver(222, "c0ffee00", "s"), "nao_autorizado")

    def test_pin_errado_nega(self):
        with patch.object(telegram_bot.config, "TELEGRAM_USER_ID", 111), \
             patch.object(telegram_bot.seguranca, "pin_valido", return_value=False):
            confirmar = telegram_bot.Confirmador(
                lambda _texto, cid: telegram_bot.resolver(111, cid, "s"),
                lambda _texto: "0000")
            self.assertFalse(confirmar("Confirmar?", pedido(exige_pin=True)))

    def test_pin_certo_autoriza(self):
        with patch.object(telegram_bot.config, "TELEGRAM_USER_ID", 111), \
             patch.object(telegram_bot.seguranca, "pin_valido", return_value=True):
            confirmar = telegram_bot.Confirmador(
                lambda _texto, cid: telegram_bot.resolver(111, cid, "s"),
                lambda _texto: "1234")
            self.assertTrue(confirmar("Confirmar?", pedido(exige_pin=True)))

    def test_pin_ausente_nega(self):
        with patch.object(telegram_bot.config, "TELEGRAM_USER_ID", 111):
            confirmar = telegram_bot.Confirmador(
                lambda _texto, cid: telegram_bot.resolver(111, cid, "s"),
                lambda _texto: None)
            self.assertFalse(confirmar("Confirmar?", pedido(exige_pin=True)))


class SkillsTelegramTests(unittest.TestCase):
    def test_skills_lista_pendentes(self):
        with patch("skills.pendentes", return_value=[SimpleNamespace(
                slug="x", nome="X", quando="quando", corpo="passo 1")]):
            self.assertIn("passo 1", telegram_bot._comando_skills("/skills"))

    def test_skills_sem_pendentes(self):
        with patch("skills.pendentes", return_value=[]):
            self.assertIn("Nenhuma skill pendente", telegram_bot._comando_skills("/skills"))

    def test_aprovar_devolve_corpo(self):
        with patch("skills.aprovar", return_value="x"), \
             patch("skills.corpo", return_value="passo 1"):
            self.assertIn("passo 1", telegram_bot._comando_skills("/aprovar x"))

    def test_erro_de_aprovacao_vira_mensagem(self):
        with patch("skills.aprovar", side_effect=ValueError("já existe skill com esse nome: x")):
            self.assertIn("já existe", telegram_bot._comando_skills("/aprovar x"))

    def test_desconhecido_devolve_none(self):
        self.assertIsNone(telegram_bot._comando_skills("oi"))


if __name__ == "__main__":
    unittest.main()
