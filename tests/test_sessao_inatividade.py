"""Bloqueio automático da sessão por inatividade (ULTRON_SESSAO_MINUTOS)."""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import sessao
from desktop_runtime import DesktopRuntime


class InatividadeTests(unittest.TestCase):
    def setUp(self):
        sessao.bloquear()
        self.addCleanup(sessao.bloquear)
        self.runtime = DesktopRuntime(start_voice=False)

    def _estado_com_atividade(self, segundos_atras):
        agora = time.time()
        return {"desbloqueada": True, "metodo": "pin", "desde": agora - segundos_atras,
                "ultima_atividade": agora - segundos_atras}

    def test_bloqueia_apos_o_limite_e_emite_evento(self):
        sessao.desbloquear("pin")
        with patch.object(config, "SESSAO_MINUTOS", 0.01), \
                patch.object(sessao, "estado", return_value=self._estado_com_atividade(100)):
            self.assertTrue(self.runtime._verificar_inatividade())
        self.assertFalse(sessao.estado()["desbloqueada"])
        eventos = [e for e in self.runtime.poll_events() if e["type"] == "session_locked"]
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["motivo"], "inatividade")

    def test_atividade_recente_nao_bloqueia(self):
        sessao.desbloquear("pin")
        sessao.tocar()
        with patch.object(config, "SESSAO_MINUTOS", 15):
            self.assertFalse(self.runtime._verificar_inatividade())
        self.assertTrue(sessao.estado()["desbloqueada"])

    def test_zero_desliga_o_bloqueio(self):
        sessao.desbloquear("pin")
        with patch.object(config, "SESSAO_MINUTOS", 0), \
                patch.object(sessao, "estado", return_value=self._estado_com_atividade(10000)):
            self.assertFalse(self.runtime._verificar_inatividade())
        self.assertTrue(sessao.estado()["desbloqueada"])

    def test_sessao_ja_bloqueada_nao_emite_evento(self):
        with patch.object(config, "SESSAO_MINUTOS", 0.01):
            self.assertFalse(self.runtime._verificar_inatividade())
        self.assertEqual([e for e in self.runtime.poll_events()
                          if e["type"] == "session_locked"], [])

    def test_limite_configuravel(self):
        with patch.object(config, "SESSAO_MINUTOS", 2):
            self.assertEqual(self.runtime._inatividade_limite(), 120)
        with patch.object(config, "SESSAO_MINUTOS", 0):
            self.assertEqual(self.runtime._inatividade_limite(), 0)


if __name__ == "__main__":
    unittest.main()
