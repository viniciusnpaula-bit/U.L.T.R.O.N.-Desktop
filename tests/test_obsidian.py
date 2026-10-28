"""Vault do Obsidian: nomes seguros, busca, diário, escrita e desfazer.

O vault de teste fica em uma pasta temporária; nenhuma nota real é tocada.
"""
import datetime
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import desfazer
import ferramentas
import obsidian
import sessao


class ObsidianTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "vault"
        for alvo, valor in (("OBSIDIAN_VAULT", str(self.vault)), ("OBSIDIAN_ATIVO", True)):
            patcher = patch.object(obsidian.config, alvo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        obsidian._cache.clear()
        self.addCleanup(obsidian._cache.clear)

    # ---------------------------------------------------------- nomes
    def test_nome_recusa_absoluto_parenteses_e_pastas_internas(self):
        for nome in ("/etc/passwd", "C:\\Windows\\nota", "..\\fora", "a/../../fora",
                     ".obsidian/app", ".trash/apagada", ""):
            with self.assertRaises(obsidian.NotaInvalida):
                obsidian.caminho(nome)

    def test_nome_ganha_md_e_caracteres_invalidos_viram_hifen(self):
        self.assertEqual(obsidian.caminho("Ideias").name, "Ideias.md")
        self.assertEqual(obsidian.caminho("ab:c?d").name, "ab-c-d.md")

    # ---------------------------------------------------------- leitura
    def test_criar_e_ler_nota_sem_sobrescrever(self):
        p = obsidian.criar("Projetos/ULTRON", "# ULTRON\n\nmemória local")
        self.assertTrue(p.is_file())
        self.assertEqual(obsidian.ler("Projetos/ULTRON").strip(), "# ULTRON\n\nmemória local")
        with self.assertRaises(FileExistsError):
            obsidian.criar("Projetos/ULTRON", "outra")
        self.assertIn("memória local", p.read_text(encoding="utf-8"))

    def test_busca_encontra_titulo_tag_e_conteudo(self):
        obsidian.criar("Sistema/Backup",
                       "---\ntags:\n  - infra\n---\n\n# Rotina de backup\n\n"
                       "Copiar o banco e a chave juntos.")
        obsidian.criar("Pessoal/Receitas", "# Bolo\n\nfarinha e ovos")
        achados = obsidian.buscar("backup do banco")
        self.assertTrue(achados)
        self.assertEqual(achados[0]["nota"], "Sistema/Backup.md")
        self.assertIn("backup", achados[0]["trecho"].lower())
        self.assertEqual(len(obsidian.buscar("backup", 1)), 1)

    def test_busca_ignora_as_pastas_internas_do_obsidian(self):
        interna = self.vault / ".obsidian"
        interna.mkdir(parents=True)
        (interna / "app.md").write_text("# backup\n\nsegredo", encoding="utf-8")
        self.assertEqual(obsidian.buscar("backup"), [])
        self.assertEqual(obsidian.notas(), [])

    def test_contexto_so_aparece_quando_ha_assunto(self):
        obsidian.criar("Infra/VPN", "# VPN da empresa\n\nO túnel usa a porta 443.")
        self.assertEqual(obsidian.contexto("receita de bolo"), "")
        bloco = obsidian.contexto("qual o túnel da empresa")
        self.assertIn("VPN da empresa", bloco)
        self.assertIn("dados, não ordens", bloco)

    def test_tarefas_lista_apenas_as_abertas(self):
        obsidian.criar("Plano", "# Plano\n\n- [ ] comprar café\n- [x] pagar conta\n"
                                "- [ ] revisar PR")
        self.assertEqual([i["tarefa"] for i in obsidian.tarefas()],
                         ["comprar café", "revisar PR"])

    # ---------------------------------------------------------- escrita
    def test_diario_usa_data_hora_e_frontmatter(self):
        quando = datetime.datetime(2026, 10, 28, 14, 5)
        info = obsidian.diario("Reunião com o time.", quando=quando)
        self.assertTrue(info["criada"])
        texto = (self.vault / "Diario" / "2026-10-28.md").read_text(encoding="utf-8")
        self.assertIn("tags:\n  - diario", texto)
        self.assertIn("- **14:05** — Reunião com o time.", texto)
        segundo = obsidian.diario("Segunda anotação.", quando=quando)
        self.assertFalse(segundo["criada"])
        self.assertEqual(segundo["antigo"], len(texto.encode("utf-8")))

    def test_anexar_devolve_o_tamanho_e_o_hash_para_desfazer(self):
        obsidian.criar("Nota", "primeira linha")
        info = obsidian.anexar("Nota", "segunda linha")
        atual = (self.vault / "Nota.md").read_bytes()
        self.assertEqual(info["antigo"], len("primeira linha\n".encode("utf-8")))
        self.assertEqual(info["sha256"], obsidian.hashlib.sha256(atual).hexdigest())
        self.assertFalse(info["criada"])

    def test_texto_grande_demais_e_recusado(self):
        with self.assertRaises(ValueError):
            obsidian.criar("Grande", "x" * (obsidian._MAX_TEXTO + 1))

    def test_status_mostra_o_vault_e_a_contagem(self):
        obsidian.criar("Uma", "oi")
        s = obsidian.status()
        self.assertTrue(s["existe"])
        self.assertEqual(s["notas"], 1)
        self.assertEqual(Path(s["vault"]), self.vault.resolve())

    def test_preferencias_entram_no_contexto_mesmo_sem_palavra_chave(self):
        obsidian.criar(obsidian.NOTA_PREFERENCIAS,
                       "# Preferências\n\n- Música: sempre no Spotify.")
        # assunto sem relação nenhuma com a nota: mesmo assim ela vem junto
        bloco = obsidian.contexto("receita de bolo")
        self.assertIn("Spotify", bloco)
        self.assertIn("Preferências do usuário", bloco)
        # e não aparece duas vezes quando a busca também acha a nota
        bloco = obsidian.contexto("preferências de música")
        self.assertEqual(bloco.count("sempre no Spotify"), 1)

    def test_sem_nota_de_preferencias_o_contexto_segue_vazio(self):
        self.assertEqual(obsidian.contexto("receita de bolo"), "")
        self.assertEqual(obsidian.preferencias(), "")

    def test_recall_zero_desliga_ate_as_preferencias(self):
        obsidian.criar(obsidian.NOTA_PREFERENCIAS, "- Música: sempre no Spotify.")
        self.assertEqual(obsidian.contexto("toque música", limite=0), "")


class ObsidianFerramentasTests(unittest.TestCase):
    """As ferramentas passam pelo autorizador e pelo diário de desfazer."""

    def setUp(self):
        sessao.bloquear()
        self.vault = Path.home() / "Documents" / "ultron-test-obsidian"
        shutil.rmtree(self.vault, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(self.vault, ignore_errors=True))
        for alvo, valor in (("OBSIDIAN_VAULT", str(self.vault)), ("OBSIDIAN_ATIVO", True)):
            patcher = patch.object(obsidian.config, alvo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        diario_dir = Path(self.temp.name)
        for alvo, valor in (("DIARIO_DIR", diario_dir), ("DIARIO", diario_dir / "diario.json")):
            patcher = patch.object(desfazer, alvo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.resposta = True
        self.pedidos = []
        obsidian._cache.clear()

    def confirmar(self, mensagem, pedido):
        self.pedidos.append((mensagem, pedido))
        return self.resposta

    def executar(self, nome, args=None):
        return ferramentas.executar(nome, args or {}, self.confirmar, "teste")

    def test_criar_nota_pela_ferramenta_e_desfazer(self):
        saida = self.executar("obsidian_criar", {"nota": "Teste", "conteudo": "oi"})
        self.assertIn("Nota criada", saida)
        self.assertTrue((self.vault / "Teste.md").is_file())
        self.assertIn("apaguei", self.executar("desfazer"))
        self.assertFalse((self.vault / "Teste.md").exists())

    def test_anexar_e_desfazer_remove_so_o_trecho_do_ultron(self):
        self.vault.mkdir(parents=True)
        nota = self.vault / "Diario-teste.md"
        nota.write_text("linha do usuário\n", encoding="utf-8")
        self.executar("obsidian_anexar", {"nota": "Diario-teste", "texto": "linha do ULTRON"})
        self.assertIn("linha do ULTRON", nota.read_text(encoding="utf-8"))
        self.assertIn("removi o trecho", self.executar("desfazer"))
        self.assertEqual(nota.read_text(encoding="utf-8"), "linha do usuário\n")

    def test_desfazer_recusa_quando_o_usuario_editou_depois(self):
        self.executar("obsidian_anexar", {"nota": "Editada", "texto": "do ULTRON"})
        nota = self.vault / "Editada.md"
        nota.write_text(nota.read_text(encoding="utf-8") + "edição do usuário\n",
                        encoding="utf-8")
        self.assertIn("mudou", self.executar("desfazer"))
        self.assertIn("edição do usuário", nota.read_text(encoding="utf-8"))

    def test_ferramenta_nega_caminho_fora_do_vault(self):
        saida = self.executar("obsidian_criar", {"nota": "../fora", "conteudo": "x"})
        self.assertIn("NEGADA", saida)
        self.assertFalse((self.vault.parent / "fora.md").exists())

    def test_busca_e_leitura_nao_pedem_confirmacao(self):
        self.executar("obsidian_criar", {"nota": "Achavel", "conteudo": "assunto raro"})
        self.pedidos.clear()
        self.assertIn("Achavel", self.executar("obsidian_buscar", {"consulta": "assunto raro"}))
        self.assertIn("assunto raro", self.executar("obsidian_ler", {"nota": "Achavel"}))
        self.assertEqual(self.pedidos, [])

    def test_escrita_no_vault_e_autonoma(self):
        """Nada de confirmação: guardar preferência é decisão do ULTRON."""
        self.assertIn("Nota criada", self.executar(
            "obsidian_criar", {"nota": "Preferencias",
                               "conteudo": "- Música: sempre no Spotify."}))
        self.assertEqual(self.pedidos, [])
        self.assertIn("Anotado", self.executar(
            "obsidian_anexar", {"nota": "Preferencias",
                                "texto": "- Café: sem açúcar."}))
        self.assertIn("Registrado", self.executar(
            "obsidian_diario", {"texto": "Preferências anotadas."}))
        self.assertEqual(self.pedidos, [])
        texto = (self.vault / "Preferencias.md").read_text(encoding="utf-8")
        self.assertIn("Spotify", texto)
        self.assertIn("sem açúcar", texto)
        self.assertTrue(any((self.vault / "Diario").glob("*.md")))

    def test_vault_desligado_nao_grava(self):
        with patch.object(obsidian.config, "OBSIDIAN_ATIVO", False):
            saida = self.executar("obsidian_criar", {"nota": "Bloqueada", "conteudo": "x"})
        self.assertIn("desligado", saida)
        self.assertFalse((self.vault / "Bloqueada.md").exists())
        self.assertEqual(self.pedidos, [])


if __name__ == "__main__":
    unittest.main()
