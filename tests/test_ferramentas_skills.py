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
        self.assertFalse([n for n in ferramentas.FERRAMENTAS if "aprov" in n])

    def test_usar_skill_devolve_corpo_e_marca_uso(self):
        with mock.patch("skills.corpo", return_value="passo 1"), \
             mock.patch("skills.marcar_uso") as uso:
            r = self.executar("usar_skill", {"nome": "Minha Skill"})
        self.assertIn("passo 1", r)
        uso.assert_called_once_with("minha-skill")

    def test_usar_skill_pendente_avisa_o_estado(self):
        with mock.patch("skills.corpo", return_value=""), \
             mock.patch("skills.pendentes", return_value=[mock.Mock(slug="minha-skill")]):
            r = self.executar("usar_skill", {"nome": "Minha Skill"})
        self.assertIn("pendente de aprovação", r)
        self.assertNotIn("não encontrada", r)

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

    def test_criar_skill_ja_existente_nao_anuncia_pendente(self):
        with mock.patch("skills.listar", return_value=[mock.Mock(slug="minha-skill")]), \
             mock.patch("skills.pendentes", return_value=[]), \
             mock.patch("skills.criar") as criar:
            r = self.executar("criar_skill",
                              {"nome": "Minha Skill", "descricao": "d",
                               "quando": "q", "corpo": "c"})
        self.assertIn("Já existe skill com esse nome: minha-skill", r)
        self.assertNotIn("guardada como pendente", r)
        criar.assert_not_called()

    def test_descardar_skill_passa_o_slug(self):
        with mock.patch("skills.descartar", return_value=True) as descartar:
            r = self.executar("descartar_skill", {"nome": "Minha Skill"})
        descartar.assert_called_once_with("minha-skill")
        self.assertIn("descartada", r)

    def test_descardar_skill_inexistente_nao_anuncia_sucesso(self):
        with mock.patch("skills.descartar", return_value=False):
            r = self.executar("descartar_skill", {"nome": "Minha Skill"})
        self.assertIn("não encontrada", r)
        self.assertNotIn("descartada", r)

    def test_desativado_responde_sem_tocar_no_disco(self):
        casos = {
            "usar_skill": {"nome": "x"},
            "listar_skills": {},
            "criar_skill": {"nome": "n", "descricao": "d", "quando": "q", "corpo": "c"},
            "descartar_skill": {"nome": "x"},
        }
        nada = mock.Mock(side_effect=AssertionError("não devia tocar no disco"))
        with mock.patch("config.SKILLS_ATIVO", False, create=True), \
             mock.patch("skills.corpo", nada), mock.patch("skills.listar", nada), \
             mock.patch("skills.pendentes", nada), mock.patch("skills.criar", nada), \
             mock.patch("skills.descartar", nada), mock.patch("skills.slugificar", nada):
            for nome, args in casos.items():
                with self.subTest(tool=nome):
                    r = self.executar(nome, args)
                    self.assertIn("desativadas", r)
