"""Desfazer no nível das ferramentas: portão, classificação, confirmação e atalho local.

A Lixeira real não é tocada aqui: `send2trash` e o restaurador são substituídos
por funções que imitam o comportamento, para o teste ser rápido e não sujar a
Lixeira do computador. A restauração real já foi validada fora da suíte.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cerebro
import desfazer
import ferramentas
import seguranca
import sessao


class DesfazerFerramentasTests(unittest.TestCase):
    def setUp(self):
        sessao.bloquear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.diario_dir = Path(self.temp.name)
        self.diario = self.diario_dir / "diario.json"
        for alvo, valor in (("DIARIO_DIR", self.diario_dir), ("DIARIO", self.diario)):
            patcher = patch.object(desfazer, alvo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.base = Path.home() / "Documents" / "ultron-test-desfazer-ferramentas"
        shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.base, ignore_errors=True))

        self.resposta = True
        self.pedidos = []

    def confirmar(self, mensagem, pedido):
        self.pedidos.append((mensagem, pedido))
        return self.resposta

    def executar(self, nome, args=None):
        return ferramentas.executar(nome, args or {}, self.confirmar, "teste")

    # ---------------------------------------------------------- criar
    def test_criar_arquivo_e_desfazer_apaga_so_o_que_foi_criado(self):
        alvo = self.base / "nota.txt"
        self.assertIn("Arquivo criado", self.executar(
            "criar_arquivo", {"caminho": str(alvo), "conteudo": "oi"}))
        self.assertTrue(alvo.is_file())
        saida = self.executar("desfazer")
        self.assertIn("apaguei", saida)
        self.assertFalse(alvo.exists())

    def test_criar_pasta_e_desfazer_remove_a_pasta_vazia(self):
        pasta = self.base / "nova"
        self.assertIn("Pasta criada", self.executar("criar_pasta", {"caminho": str(pasta)}))
        self.assertTrue(pasta.is_dir())
        self.executar("desfazer")
        self.assertFalse(pasta.exists())

    # ---------------------------------------------------------- confirmação
    def test_desfazer_sempre_pede_confirmacao_mesmo_com_medio_nunca(self):
        alvo = self.base / "confirmar.txt"
        self.executar("criar_arquivo", {"caminho": str(alvo), "conteudo": "x"})
        cls = ferramentas.FERRAMENTAS["desfazer"]["classificar"]()
        self.assertEqual(cls.risco, ferramentas.MEDIO)
        self.assertFalse(cls.na_allowlist)
        self.assertIn("apagar", cls.resumo)

        cfg = seguranca.permissoes()
        cfg["confirmacao"]["medio"] = "nunca"
        cfg["allowlist"]["operacoes"].append("arquivo.desfazer")
        with patch.object(seguranca, "permissoes", return_value=cfg):
            decisao, motivo = seguranca.autorizar(cls)
        self.assertEqual(decisao, seguranca.CONFIRM, motivo)

        self.resposta = False
        saida = self.executar("desfazer")
        self.assertIn("cancelada", saida)
        self.assertTrue(alvo.exists())
        self.assertEqual(len(self.pedidos), 1)
        self.assertIn("apagar", self.pedidos[0][0])

    def test_desfazer_sem_nada_no_diario_nao_pede_confirmacao(self):
        saida = self.executar("desfazer")
        self.assertIn("Não há nada para desfazer", saida)
        self.assertEqual(self.pedidos, [])

    def test_desfazer_alterado_recusa_e_nao_apaga(self):
        alvo = self.base / "editado.txt"
        self.executar("criar_arquivo", {"caminho": str(alvo), "conteudo": "original"})
        alvo.write_text("editado pelo usuário", encoding="utf-8")
        saida = self.executar("desfazer")
        self.assertIn("Não desfiz", saida)
        self.assertIn("mudou", saida)
        self.assertEqual(alvo.read_text(encoding="utf-8"), "editado pelo usuário")

    def test_desfazer_volta_uma_operacao_por_vez(self):
        primeiro = self.base / "p1.txt"
        segundo = self.base / "p2.txt"
        self.executar("criar_arquivo", {"caminho": str(primeiro), "conteudo": "1"})
        self.executar("criar_arquivo", {"caminho": str(segundo), "conteudo": "2"})
        self.executar("desfazer")
        self.assertFalse(segundo.exists())
        self.assertTrue(primeiro.exists())
        self.executar("desfazer")
        self.assertFalse(primeiro.exists())

    # ---------------------------------------------------------- mover
    def test_mover_e_desfazer_devolve_ao_lugar_original(self):
        origem = self.base / "m.txt"
        origem.write_text("m", encoding="utf-8")
        destino = self.base / "sub" / "m.txt"
        destino.parent.mkdir()
        self.assertIn("Movido", self.executar(
            "mover_arquivo", {"origem": str(origem), "destino": str(destino)}))
        self.assertTrue(destino.exists())
        saida = self.executar("desfazer")
        self.assertIn("devolvi", saida)
        self.assertTrue(origem.exists())
        self.assertFalse(destino.exists())

    # ---------------------------------------------------------- compactar
    def test_compactar_e_desfazer_apaga_apenas_o_zip(self):
        origem = self.base / "c.txt"
        origem.write_text("c", encoding="utf-8")
        self.executar("compactar_arquivos", {"caminho": str(origem)})
        zipado = self.base / "c.txt.zip"
        self.assertTrue(zipado.is_file())
        self.executar("desfazer")
        self.assertFalse(zipado.exists())
        self.assertTrue(origem.exists())

    # ---------------------------------------------------------- descompactar
    def test_descompactar_e_desfazer_apaga_a_arvore_extraida(self):
        pasta = self.base / "para-zipar"
        pasta.mkdir()
        (pasta / "dentro.txt").write_text("d", encoding="utf-8")
        zipado = self.base / "pacote.zip"
        self.executar("compactar_arquivos", {"caminho": str(pasta), "destino": str(zipado)})
        self.executar("descompactar_arquivo", {"arquivo": str(zipado), "destino": str(self.base / "saida")})
        saida = self.base / "saida"
        self.assertTrue((saida / "para-zipar" / "dentro.txt").is_file())
        self.executar("desfazer")
        self.assertFalse(saida.exists())
        self.assertTrue(zipado.is_file())

    # ---------------------------------------------------------- site
    def test_criar_site_e_desfazer_remove_html_e_pasta(self):
        pasta = self.base / "site-novo"
        self.assertIn("Site criado", self.executar(
            "criar_site", {"pasta": str(pasta), "nome": "index", "titulo": "Teste"}))
        html = pasta / "index.html"
        self.assertTrue(html.is_file())
        self.executar("desfazer")
        self.assertFalse(html.exists())
        self.assertFalse(pasta.exists())

    # ---------------------------------------------------------- organizar
    def test_organizar_e_desfazer_devolve_arquivos_e_remove_subpastas(self):
        bagunca = self.base / "bagunca"
        bagunca.mkdir()
        foto = bagunca / "foto.jpg"
        nota = bagunca / "nota.txt"
        foto.write_bytes(b"x")
        nota.write_text("n", encoding="utf-8")
        self.executar("organizar_arquivos", {"pasta": str(bagunca)})
        self.assertTrue((bagunca / "Imagens" / "foto.jpg").is_file())
        self.assertTrue((bagunca / "Documentos" / "nota.txt").is_file())
        self.executar("desfazer")
        self.assertTrue(foto.is_file())
        self.assertTrue(nota.is_file())
        self.assertFalse((bagunca / "Imagens").exists())
        self.assertFalse((bagunca / "Documentos").exists())

    def test_organizar_por_data_e_desfazer_remove_ano_e_mes(self):
        import os
        from datetime import datetime

        bagunca = self.base / "por-data"
        bagunca.mkdir()
        nota = bagunca / "nota.txt"
        nota.write_text("n", encoding="utf-8")
        os.utime(nota, (datetime(2022, 7, 1, 12).timestamp(),) * 2)

        self.executar("organizar_arquivos", {"pasta": str(bagunca), "modo": "data"})
        self.assertTrue((bagunca / "2022" / "07" / "nota.txt").is_file())

        self.executar("desfazer")
        self.assertTrue(nota.is_file())
        self.assertFalse((bagunca / "2022").exists())

    def test_organizar_recusa_modo_invalido_sem_mover(self):
        bagunca = self.base / "modo-invalido"
        bagunca.mkdir()
        nota = bagunca / "nota.txt"
        nota.write_text("n", encoding="utf-8")
        saida = self.executar("organizar_arquivos", {"pasta": str(bagunca), "modo": "por-cor"})
        self.assertIn("Modo inválido", saida)
        self.assertTrue(nota.is_file())

    # ---------------------------------------------------------- apagar
    def test_apagar_e_desfazer_restaura_pela_lixeira(self):
        alvo = self.base / "apagado.txt"
        alvo.write_text("conteudo original", encoding="utf-8")
        antes = alvo.stat()

        def lixeira_falsa(caminho):
            Path(caminho).unlink()

        def restaurador_falso(caminho, dados):
            caminho.write_text("conteudo original", encoding="utf-8")
            import os
            os.utime(caminho, ns=(antes.st_atime_ns, antes.st_mtime_ns))
            return True, ""

        with patch("send2trash.send2trash", side_effect=lixeira_falsa):
            self.assertIn("lixeira", self.executar("apagar_arquivo", {"caminho": str(alvo)}))
        self.assertFalse(alvo.exists())

        cls = ferramentas.FERRAMENTAS["apagar_arquivo"]["classificar"](caminho=str(alvo))
        self.assertEqual(cls.risco, ferramentas.ALTO)

        with patch.object(desfazer, "_restaurar_da_lixeira", side_effect=restaurador_falso):
            saida = self.executar("desfazer")
        self.assertIn("restaurei", saida)
        self.assertTrue(alvo.is_file())
        self.assertEqual(alvo.read_text(encoding="utf-8"), "conteudo original")
        self.assertEqual(alvo.stat().st_mtime_ns, antes.st_mtime_ns)

    def test_confirmacao_do_apagar_avisa_que_vai_para_a_lixeira(self):
        alvo = self.base / "aviso.txt"
        alvo.write_text("x", encoding="utf-8")
        with patch("send2trash.send2trash", side_effect=lambda c: Path(c).unlink()):
            self.executar("apagar_arquivo", {"caminho": str(alvo)})
        self.assertEqual(len(self.pedidos), 1)
        self.assertIn("lixeira", self.pedidos[0][0])

    # ---------------------------------------------------------- classificação
    def test_desfazer_fora_do_diario_e_baixo_risco(self):
        cls = ferramentas.FERRAMENTAS["desfazer"]["classificar"]()
        self.assertEqual(cls.risco, ferramentas.BAIXO)
        self.assertFalse(cls.negar)

    # ---------------------------------------------------------- atalho local
    def test_atalho_local_reconhece_desfazer(self):
        for texto in ("desfazer", "desfaz", "desfaz isso", "desfazer a última ação",
                      "desfazer a ultima", "Undo", "Ei Ultron, desfaz isso"):
            self.assertEqual(cerebro._acao_rapida(texto), "desfazer", texto)

    def test_atalho_local_nao_captura_frases_com_outro_sentido(self):
        for texto in ("desfaz o nó", "como desfazer um nó", "desfazer tudo",
                      "por favor desfazer", "desfaz a conta"):
            self.assertIsNone(cerebro._acao_rapida(texto), texto)

    def test_acao_rapida_chama_a_ferramenta_desfazer(self):
        chamadas = []

        def executar(nome, argumentos, confirmar, origem):
            chamadas.append((nome, argumentos, origem))
            return "apaguei a nota.txt"

        with patch.object(cerebro, "_rastrear"):
            resultado = cerebro._executar_acao_rapida("desfazer", executar, self.confirmar, "desktop")
        self.assertEqual(resultado, "apaguei a nota.txt")
        self.assertEqual(chamadas, [("desfazer", {}, "desktop")])

    def test_acao_rapida_marca_negacao_do_desfazer(self):
        with patch.object(cerebro, "_rastrear") as rastrear:
            cerebro._executar_acao_rapida(
                "desfazer", lambda *a: "Não desfiz: o arquivo mudou.", self.confirmar, "desktop")
        estados = [c.args[4] for c in rastrear.call_args_list if c.args[1] == "step_finished"]
        self.assertEqual(estados, ["failure"])

    # ---------------------------------------------------------- rastreamento
    def test_desfazer_esta_no_rastreamento_de_seguranca(self):
        self.assertIn("desfazer", seguranca._RASTREIO_ACOES)
        self.assertIn("desfazer", seguranca._RASTREIO_ETAPAS)


if __name__ == "__main__":
    unittest.main()
