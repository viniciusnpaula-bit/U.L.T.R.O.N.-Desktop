import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ferramentas
import seguranca


class FerramentasSkillsTests(unittest.TestCase):
    def setUp(self):
        # O gate é o dono da autorização; aqui ele aprova para isolar a ferramenta.
        autorizar = mock.patch("seguranca.autorizar", return_value=(seguranca.ALLOW, "ok"))
        autorizar.start()
        self.addCleanup(autorizar.stop)

    def executar(self, nome, args):
        return ferramentas.executar(nome, args, lambda *_: True)

    def test_tools_registradas(self):
        for nome in ("usar_skill", "listar_skills", "criar_skill", "descartar_skill"):
            self.assertIn(nome, ferramentas.FERRAMENTAS)

    def test_nao_existe_ferramenta_de_aprovacao(self):
        self.assertNotIn("aprovar_skill", ferramentas.FERRAMENTAS)

    def test_usar_skill_devolve_corpo_e_marca_uso(self):
        with mock.patch("skills.corpo", return_value="passo 1"), \
             mock.patch("skills.marcar_uso") as uso:
            r = self.executar("usar_skill", {"nome": "x"})
        self.assertIn("passo 1", r)
        uso.assert_called_once_with("x")

    def test_criar_skill_devolve_erro_sem_estourar(self):
        with mock.patch("skills.criar", side_effect=ValueError("fila de skills cheia")):
            r = self.executar("criar_skill",
                              {"nome": "n", "descricao": "d", "quando": "q", "corpo": "c"})
        self.assertIn("fila de skills cheia", r)

    def test_criar_skill_classifica_medio(self):
        cls = ferramentas.FERRAMENTAS["criar_skill"]["classificar"](
            nome="n", descricao="d", quando="q", corpo="c")
        self.assertEqual(cls.risco, "MEDIO")
        self.assertEqual(cls.operacao, "skill.criar")

    def test_desativado_responde_sem_tocar_no_disco(self):
        with mock.patch("config.SKILLS_ATIVO", False, create=True), \
             mock.patch("skills.corpo", side_effect=AssertionError("não devia ler o disco")):
            self.assertIn("desativadas", self.executar("usar_skill", {"nome": "x"}))
