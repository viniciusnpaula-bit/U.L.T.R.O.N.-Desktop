import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import skills

HOJE = date.today()

VALIDO = f"""---
nome: Organizar Downloads
descricao: Separar arquivos baixados por tipo
quando: quando o usuário pedir para organizar a pasta Downloads
criado_por: usuario
criado_em: {HOJE.isoformat()}
---

1. Liste a pasta.
2. Agrupe por extensão.
"""


class StoreBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        raiz = Path(self._tmp.name)
        self._patch = [
            mock.patch.object(skills, "BASE", raiz / "skills"),
            mock.patch.object(skills, "PENDENTES", raiz / "skills" / ".pendentes"),
            mock.patch.object(skills, "USO", raiz / "skills" / ".uso.json"),
        ]
        for p in self._patch:
            p.start()
        skills.BASE.mkdir(parents=True)
        skills.PENDENTES.mkdir(parents=True)
        skills.invalidar()

    def tearDown(self):
        for p in self._patch:
            p.stop()
        self._tmp.cleanup()

    def escrever(self, slug, texto=VALIDO, pendente=False):
        pasta = (skills.PENDENTES if pendente else skills.BASE) / slug
        pasta.mkdir(parents=True)
        (pasta / "SKILL.md").write_text(texto, encoding="utf-8")
        return pasta


class LeituraTests(StoreBase):
    def test_skill_valida_aparece_em_listar(self):
        self.escrever("organizar-downloads")
        lista = skills.listar()
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0].nome, "Organizar Downloads")
        self.assertIn("Agrupe por extensão", lista[0].corpo)

    def test_frontmatter_invalido_e_ignorado(self):
        self.escrever("quebrada", "sem frontmatter nenhum")
        self.escrever("sem-campo", "---\nnome: X\n---\ncorpo")
        self.assertEqual(skills.listar(), [])

    def test_pendente_nao_entra_no_indice(self):
        self.escrever("nova", pendente=True)
        self.assertEqual(skills.indice(), "")
        self.assertEqual(len(skills.pendentes()), 1)

    def test_indice_limita_15_e_trunca_em_90(self):
        longo = "quando " + "o usuário pedir " * 12
        for i in range(20):
            self.escrever(f"skill-{i}",
                          VALIDO.replace("Organizar Downloads", f"Skill {i}")
                                .replace("quando o usuário pedir para organizar a pasta Downloads", longo))
        linhas = [l for l in skills.indice().splitlines() if l.startswith("- ")]
        self.assertEqual(len(linhas), 15)
        for linha in linhas:
            self.assertLessEqual(len(linha), 90)

    def test_corpo_de_pendente_e_vazio(self):
        self.escrever("nova", pendente=True)
        self.assertEqual(skills.corpo("nova"), "")

    def test_uso_e_lido_uma_vez_por_indice(self):
        self.escrever("a")
        self.escrever("b")
        skills.USO.write_text('{"a": "2026-01-01"}', encoding="utf-8")
        with mock.patch.object(skills.json, "loads", wraps=skills.json.loads) as loads:
            skills.indice()
        self.assertEqual(loads.call_count, 1)

    def test_corpo_trunca_no_limite(self):
        self.escrever("longa", VALIDO.replace("2. Agrupe por extensão.", "x" * 5000))
        self.assertLessEqual(len(skills.corpo("organizar-downloads")), 2000)

    def test_slug_seguro(self):
        self.assertEqual(skills.slugificar("Organizar Downloads!"), "organizar-downloads")
        for entrada in ("../../etc/passwd", "a\\b", "..", ""):
            slug = skills.slugificar(entrada)
            self.assertNotIn("..", slug)
            self.assertNotIn("/", slug)
            self.assertNotIn("\\", slug)


class EstadoTests(StoreBase):
    def test_estado_por_idade(self):
        self.escrever("velha")
        hoje = HOJE
        with mock.patch.object(skills, "_uso", return_value={}):
            self.assertEqual(skills.estado(skills.listar()[0], hoje), "ativo")
            self.assertEqual(skills.estado(skills.listar()[0], hoje + timedelta(days=45)), "obsoleto")
            self.assertEqual(skills.estado(skills.listar()[0], hoje + timedelta(days=95)), "arquivado")

    def test_arquivada_sai_do_indice(self):
        self.escrever("velha")
        antiga = (HOJE - timedelta(days=120)).isoformat()
        with mock.patch.object(skills, "_uso", return_value={"velha": antiga}):
            skills.invalidar()
            self.assertEqual(skills.indice(), "")
