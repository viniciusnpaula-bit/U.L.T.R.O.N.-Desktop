import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cerebro


class SkillRapidaTests(unittest.TestCase):
    def test_reconhece_aprovar(self):
        self.assertEqual(cerebro._skill_rapida("Aprova a skill organizar-downloads"),
                         ("aprovar", "organizar-downloads"))

    def test_reconhece_descartar(self):
        self.assertEqual(cerebro._skill_rapida("descarta a skill lixo"),
                         ("descartar", "lixo"))

    def test_nao_casa_com_frase_comum(self):
        self.assertIsNone(cerebro._skill_rapida("organiza a pasta downloads"))

    def test_executar_aprovar_devolve_resumo_curto(self):
        with mock.patch("skills.aprovar", return_value="x") as aprovar, \
             mock.patch("skills.corpo", return_value="passo 1"):
            r = cerebro._executar_skill_rapida("aprovar", "x")
            aprovar.assert_called_once_with("x")
            self.assertIn("aprovada", r)
            self.assertNotIn("passo 1", r)          # voz não recita o corpo
            self.assertLess(len(r), 200)

    def test_system_inclui_indice(self):
        with mock.patch("skills.indice", return_value="- Skill A: quando usar"):
            self.assertIn("Skill A", cerebro._system())

    def test_system_nao_quebra_se_skills_falhar(self):
        with mock.patch("skills.indice", side_effect=RuntimeError("boom")):
            self.assertTrue(len(cerebro._system()) > 100)
