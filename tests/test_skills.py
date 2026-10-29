import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
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

    def test_encoding_ruim_nao_derruba_listar(self):
        self.escrever("valida")
        for codificacao in ("utf-16", "cp1252"):
            with self.subTest(codificacao=codificacao):
                pasta = skills.BASE / f"salva-{codificacao}"
                pasta.mkdir(parents=True, exist_ok=True)
                (pasta / "SKILL.md").write_bytes(VALIDO.encode(codificacao))
                self.assertEqual([s.slug for s in skills.listar()], ["valida"])

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
        self.assertEqual(len(skills.corpo("longa")), 2000)

    def test_cache_invalida_quando_skill_muda(self):
        pasta = self.escrever("organizar-downloads")
        self.assertEqual(skills.listar()[0].nome, "Organizar Downloads")
        caminho = pasta / "SKILL.md"
        caminho.write_text(VALIDO.replace("Organizar Downloads", "Organizar Fotos"), encoding="utf-8")
        # mtime distinto: não depender da resolução do sistema de arquivos
        ns = caminho.stat().st_mtime_ns + 1_000_000_000
        os.utime(caminho, ns=(ns, ns))
        self.assertEqual(skills.listar()[0].nome, "Organizar Fotos")

    def test_cache_nao_invalida_quando_uso_e_escrito(self):
        self.escrever("organizar-downloads")
        antes = skills.listar()[0]
        skills.USO.write_text('{"organizar-downloads": "2026-01-01"}', encoding="utf-8")
        self.assertIs(skills.listar()[0], antes)

    def test_corpo_vazio_quando_desligado(self):
        self.escrever("organizar-downloads")
        with mock.patch.object(config, "SKILLS_ATIVO", False, create=True), \
             mock.patch.object(skills, "listar", side_effect=AssertionError("leu disco")):
            self.assertEqual(skills.corpo("organizar-downloads"), "")

    def test_indice_vazio_com_limite_zero(self):
        self.escrever("organizar-downloads")
        with mock.patch.object(config, "SKILLS_MAX_INDICE", 0, create=True):
            self.assertEqual(skills.indice(), "")

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

    def test_sem_criado_em_usa_mtime_do_arquivo(self):
        pasta = self.escrever("antiga", VALIDO.replace(f"criado_em: {HOJE.isoformat()}\n", ""))
        antigo = (datetime.now() - timedelta(days=120)).timestamp()
        os.utime(pasta / "SKILL.md", (antigo, antigo))
        skills.invalidar()
        with mock.patch.object(skills, "_uso", return_value={}):
            self.assertEqual(skills.estado(skills.listar()[0]), "arquivado")


class CicloTests(StoreBase):
    def test_criar_grava_pendente(self):
        slug = skills.criar("Nova Skill", "faz algo", "quando pedirem", "passo 1")
        self.assertEqual(slug, "nova-skill")
        self.assertEqual(len(skills.pendentes()), 1)
        self.assertEqual(skills.listar(), [])

    def test_criar_recusa_quarta_pendente(self):
        for i in range(3):
            skills.criar(f"Skill {i}", "d", "q", "c")
        with mock.patch.object(config, "SKILLS_PENDENTES_MAX", 3, create=True):
            with self.assertRaises(ValueError) as erro:
                skills.criar("Skill 4", "d", "q", "c")
        self.assertIn("fila de skills cheia", str(erro.exception))

    def test_criar_deduplica_nome_existente(self):
        skills.criar("Repetida", "d", "q", "c")
        self.assertEqual(skills.criar("Repetida", "d", "q", "c"), "repetida")
        self.assertEqual(len(skills.pendentes()), 1)

    def test_criar_deduplica_contra_ativa(self):
        self.escrever("organizar-downloads")
        self.assertEqual(skills.criar("Organizar Downloads", "d", "q", "c"), "organizar-downloads")
        self.assertEqual(skills.pendentes(), [])

    def test_criado_por_nao_injeta_frontmatter(self):
        slug = skills.criar("Injecao", "d", "q", "c", criado_por="eu\nnome: falsa")
        texto = (skills.PENDENTES / slug / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual([l for l in texto.splitlines() if l.startswith("nome:")], ["nome: Injecao"])

    def test_aprovar_move_para_raiz(self):
        slug = skills.criar("Aprovar", "d", "q", "c")
        skills.aprovar(slug)
        self.assertEqual([s.slug for s in skills.listar()], [slug])
        self.assertEqual(skills.pendentes(), [])

    def test_aprovar_recusa_colisao(self):
        self.escrever("colide")
        self.escrever("colide", pendente=True)
        with self.assertRaises(ValueError):
            skills.aprovar("colide")
        self.assertEqual([s.slug for s in skills.pendentes()], ["colide"])

    def test_aprovar_recusa_acima_do_total(self):
        self.escrever("ja-ativa")
        slug = skills.criar("Nova", "d", "q", "c")
        with mock.patch.object(config, "SKILLS_MAX_TOTAL", 1, create=True):
            with self.assertRaises(ValueError) as erro:
                skills.aprovar(slug)
        self.assertIn("limite", str(erro.exception))
        self.assertEqual([s.slug for s in skills.pendentes()], [slug])

    def test_descartar_remove_pendente(self):
        slug = skills.criar("Lixo", "d", "q", "c")
        skills.descartar(slug)
        self.assertEqual(skills.pendentes(), [])

    def test_descartar_nao_remove_ativa_de_mesmo_slug(self):
        self.escrever("mesmo")
        self.escrever("mesmo", pendente=True)
        skills.descartar("mesmo")
        self.assertEqual([s.slug for s in skills.listar()], ["mesmo"])
        self.assertEqual(skills.pendentes(), [])

    def test_descartar_recusa_slug_destrutivo(self):
        slug = skills.criar("Intacta", "d", "q", "c")
        for entrada in (".", "..", "C:", "a/b"):
            with self.subTest(entrada=entrada):
                with self.assertRaises(ValueError):
                    skills.descartar(entrada)
                self.assertEqual([s.slug for s in skills.pendentes()], [slug])
                self.assertTrue(skills.BASE.is_dir())

    def test_marcar_uso_grava_json(self):
        self.escrever("usada")
        skills.marcar_uso("usada")
        self.assertEqual(json.loads(skills.USO.read_text(encoding="utf-8"))["usada"],
                         date.today().isoformat())

    def test_cada_escrita_usa_temporario_proprio(self):
        alvo = skills.BASE / "corrida" / "SKILL.md"
        origens, real = [], skills.os.replace

        def espiao(origem, destino):
            origens.append(Path(origem).name)
            return real(origem, destino)

        with mock.patch.object(skills.os, "replace", side_effect=espiao):
            skills._escrever(alvo, "A")
            skills._escrever(alvo, "B")

        # tmp fixo faria as duas escritas usarem o mesmo nome
        self.assertEqual(len(set(origens)), 2, origens)
        self.assertEqual(alvo.read_text(encoding="utf-8"), "B")

    def test_escrita_que_falha_nao_deixa_temporario(self):
        alvo = skills.BASE / "falha" / "SKILL.md"
        with mock.patch.object(skills.os, "replace", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                skills._escrever(alvo, "texto")
        self.assertEqual(list(alvo.parent.iterdir()), [])

    def test_curar_conta_e_avisa_pendente_antiga(self):
        self.escrever("ativa")
        velha = (HOJE - timedelta(days=30)).isoformat()
        antiga = VALIDO.replace(HOJE.isoformat(), velha).replace("Organizar Downloads", "Antiga")
        self.escrever("antiga", antiga, pendente=True)
        r = skills.curar()
        self.assertEqual(r["ativos"], 1)
        self.assertEqual(r["pendentes"], 1)
        self.assertTrue(any("antiga" in a for a in r["avisos"]))

    def test_curar_nao_move_nem_apaga(self):
        velha = (HOJE - timedelta(days=30)).isoformat()
        antiga = VALIDO.replace(HOJE.isoformat(), velha).replace("Organizar Downloads", "Antiga")
        pasta = self.escrever("antiga", antiga, pendente=True)
        skills.curar()
        self.assertEqual([s.slug for s in skills.pendentes()], ["antiga"])
        self.assertTrue((pasta / "SKILL.md").is_file())
