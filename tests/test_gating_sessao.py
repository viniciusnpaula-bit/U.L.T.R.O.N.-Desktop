import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seguranca
import sessao


def cls(risco):
    return seguranca.Classificacao(risco)


class GatingSessaoTests(unittest.TestCase):
    def setUp(self):
        sessao.bloquear()

    def tearDown(self):
        sessao.bloquear()

    def test_alto_local_reversivel_so_libera_desbloqueado(self):
        for origem in sorted(seguranca.ORIGENS_LOCAIS):
            self.assertEqual(seguranca.autorizar(cls(seguranca.ALTO), "pressionar_tecla", origem),
                             (seguranca.CONFIRM, "high_risk_action"), origem)
        sessao.desbloquear("pin")
        for origem in sorted(seguranca.ORIGENS_LOCAIS):
            self.assertEqual(seguranca.autorizar(cls(seguranca.ALTO), "pressionar_tecla", origem),
                             (seguranca.ALLOW, "unlocked_session_high_risk"), origem)

    def test_alto_de_fora_continua_confirmando_desbloqueado(self):
        sessao.desbloquear("pin")
        for origem in ("telegram", "fluxo", "teste", "desconhecida"):
            self.assertEqual(seguranca.autorizar(cls(seguranca.ALTO), "pressionar_tecla", origem),
                             (seguranca.CONFIRM, "high_risk_action"), origem)

    def test_irreversiveis_e_privacidade_confirmam_desbloqueado(self):
        sessao.desbloquear("hello")
        for nome in sorted(seguranca.IRREVERSIVEIS | seguranca.SEMPRE_CONFIRMAR):
            self.assertEqual(seguranca.autorizar(cls(seguranca.ALTO), nome, "desktop"),
                             (seguranca.CONFIRM, "high_risk_action"), nome)

    def test_negar_vence_o_desbloqueio(self):
        sessao.desbloquear("pin")
        negada = seguranca.Classificacao(seguranca.BAIXO, negar="regra_local")
        self.assertEqual(seguranca.autorizar(negada, "pressionar_tecla", "desktop"),
                         (seguranca.DENY, "regra_local"))


if __name__ == "__main__":
    unittest.main()
