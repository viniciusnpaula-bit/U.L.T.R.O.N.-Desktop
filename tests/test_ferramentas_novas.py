import sys
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ferramentas


class RiscosDasFerramentasNovasTests(unittest.TestCase):
    def test_organizar_sempre_pede_confirmacao(self):
        with patch.object(ferramentas, "_pasta_permitida", return_value=Path("C:/Users/x/Desktop")):
            cls = ferramentas.FERRAMENTAS["organizar_arquivos"]["classificar"](pasta="Desktop")
        self.assertEqual(cls.risco, ferramentas.ALTO)
        self.assertFalse(cls.negar)

    def test_prever_organizacao_nao_pede_confirmacao(self):
        with patch.object(ferramentas, "_pasta_permitida", return_value=Path("C:/Users/x/Desktop")):
            cls = ferramentas.FERRAMENTAS["prever_organizacao"]["classificar"](pasta="Desktop")
        self.assertEqual(cls.risco, ferramentas.BAIXO)

    def test_organizar_fora_da_allowlist_e_negado(self):
        with patch.object(ferramentas, "_pasta_permitida", return_value=None):
            cls = ferramentas.FERRAMENTAS["organizar_arquivos"]["classificar"](pasta="C:/Windows")
        self.assertEqual(cls.negar, "outside_allowlist")

    def test_nome_curto_de_pasta_resolve_na_home(self):
        # "Downloads" tem de resolver como C:\Users\x\Downloads, não contra a pasta do Ultron
        alvo = Path.home() / f"ultron_teste_{os.getpid()}"
        alvo.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, alvo, True)
        with patch.object(ferramentas.seguranca, "allowlist", return_value=[str(alvo)]):
            self.assertEqual(ferramentas._pasta_permitida(alvo.name), alvo.resolve())

    def test_allowlist_nao_abre_appdata_ssh_nem_a_pasta_do_ultron(self):
        for dentro in (Path.home() / "AppData" / "Local", Path.home() / ".ssh",
                       ferramentas.seguranca.BASE):
            with patch.object(ferramentas.seguranca, "allowlist", return_value=[str(Path.home())]):
                self.assertIsNone(ferramentas._pasta_permitida(str(dentro)), dentro)

    def test_recusa_diz_quais_pastas_sao_permitidas(self):
        with patch.object(ferramentas, "_pastas_permitidas", return_value=[r"C:\Users\x\Downloads"]):
            saida = ferramentas._recusa_fora_da_allowlist()
        self.assertTrue(saida.startswith("AÇÃO NEGADA"), saida)
        self.assertIn(r"C:\Users\x\Downloads", saida)

    def test_enviar_formulario_e_risco_alto(self):
        cls = ferramentas.FERRAMENTAS["enviar_formulario"]["classificar"]()
        self.assertEqual(cls.risco, ferramentas.ALTO)

    def test_clicar_e_preencher_sao_medio(self):
        self.assertEqual(ferramentas.FERRAMENTAS["clicar_pagina"]["classificar"](texto="Entrar").risco,
                         ferramentas.MEDIO)
        self.assertEqual(ferramentas.FERRAMENTAS["preencher_campo"]["classificar"](campo="Email").risco,
                         ferramentas.MEDIO)

    def test_zip_em_caminho_protegido_e_negado(self):
        cls = ferramentas.FERRAMENTAS["compactar_arquivos"]["classificar"](
            caminho=str(Path.home() / "AppData" / "algo"), destino="")
        self.assertEqual(cls.negar, "protected_path")

    def test_navegar_com_parametros_pede_confirmacao(self):
        cls = ferramentas.FERRAMENTAS["navegar"]["classificar"](url="https://example.com/?token=1")
        self.assertEqual(cls.risco, ferramentas.MEDIO)

    def test_palco_texto_e_fechar_nao_pedem_confirmacao(self):
        for tipo in ("texto", "fechar"):
            cls = ferramentas.FERRAMENTAS["mostrar_na_interface"]["classificar"](
                tipo=tipo, alvo="oi")
            self.assertEqual(cls.risco, ferramentas.BAIXO, tipo)
            self.assertTrue(cls.na_allowlist, tipo)

    def test_palco_site_pede_confirmacao(self):
        cls = ferramentas.FERRAMENTAS["mostrar_na_interface"]["classificar"](
            tipo="site", alvo="https://example.com")
        self.assertEqual(cls.risco, ferramentas.MEDIO)
        self.assertFalse(cls.na_allowlist)

    def test_palco_youtube_e_video_direto_tem_riscos_diferentes(self):
        cls = ferramentas.FERRAMENTAS["mostrar_na_interface"]["classificar"](
            tipo="video", alvo="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(cls.risco, ferramentas.BAIXO)
        self.assertTrue(cls.na_allowlist)
        cls = ferramentas.FERRAMENTAS["mostrar_na_interface"]["classificar"](
            tipo="video", alvo="https://example.com/clip.mp4")
        self.assertEqual(cls.risco, ferramentas.MEDIO)
        self.assertFalse(cls.na_allowlist)

    def test_palco_recusa_caminho_protegido(self):
        with patch.object(ferramentas, "_protegido", return_value=True):
            cls = ferramentas.FERRAMENTAS["mostrar_na_interface"]["classificar"](
                tipo="video", alvo="C:/Windows/clip.mp4")
        self.assertEqual(cls.negar, "protected_path")

    def test_palco_arquivo_local_segue_a_allowlist(self):
        with patch.object(ferramentas, "_protegido", return_value=False), \
                patch.object(ferramentas, "_pasta_ok", return_value=True):
            cls = ferramentas.FERRAMENTAS["mostrar_na_interface"]["classificar"](
                tipo="imagem", alvo="C:/Users/x/Documents/foto.png")
        self.assertEqual(cls.risco, ferramentas.BAIXO)
        self.assertTrue(cls.na_allowlist)
        with patch.object(ferramentas, "_protegido", return_value=False), \
                patch.object(ferramentas, "_pasta_ok", return_value=False):
            cls = ferramentas.FERRAMENTAS["mostrar_na_interface"]["classificar"](
                tipo="imagem", alvo="C:/Users/x/Outro/foto.png")
        self.assertEqual(cls.risco, ferramentas.MEDIO)
        self.assertFalse(cls.na_allowlist)


class ArquivosNovosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_compactar_e_descompactar_pelas_ferramentas(self):
        origem_dir = Path.home() / "Documents" / "ultron-test-origem"
        origem_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(origem_dir, ignore_errors=True))
        origem = origem_dir / "nota.txt"
        origem.write_text("oi", encoding="utf-8")
        destino_dir = Path.home() / "Documents" / "ultron-test-destino"
        destino_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(destino_dir, ignore_errors=True))
        criado = ferramentas.executar("compactar_arquivos", {"caminho": str(origem)},
                                      lambda *_: True, "teste")
        self.assertIn("ZIP criado", criado)
        arquivo_zip = Path(criado.split("em ")[1].split(" ")[0])
        self.addCleanup(lambda: arquivo_zip.unlink(missing_ok=True))
        extraido = ferramentas.executar(
            "descompactar_arquivo",
            {"arquivo": str(arquivo_zip), "destino": str(destino_dir)},
            lambda *_: True, "teste")
        self.assertIn("Extraí 1", extraido)
        self.assertEqual((destino_dir / "nota.txt").read_text(encoding="utf-8"), "oi")

    def test_info_hardware_delega_para_o_modulo(self):
        with patch("hardware.descrever", return_value="CPU X"):
            self.assertEqual(ferramentas.executar("info_hardware", {}, lambda *_: True, "teste"), "CPU X")


class CodigoTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(ferramentas._SANDBOX)
        self.addCleanup(lambda: shutil.rmtree(self.sandbox, ignore_errors=True))

    def test_rodar_codigo_e_risco_critico(self):
        cls = ferramentas.FERRAMENTAS["rodar_codigo"]["classificar"](linguagem="python", codigo="print(1)")
        self.assertEqual(cls.risco, ferramentas.CRITICO)

    def test_roda_python_e_devolve_saida(self):
        saida = ferramentas.executar(
            "rodar_codigo",
            {"linguagem": "python", "codigo": "print('ola do sandbox')", "nome": "teste-saida"},
            lambda *_: True, "teste")
        self.assertIn("ola do sandbox", saida)
        self.assertIn("ok", saida)

    def test_codigo_nao_ve_chaves_de_api(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "segredo-de-teste"}, clear=False):
            saida = ferramentas.executar(
                "rodar_codigo",
                {"linguagem": "python",
                 "codigo": "import os; print(os.environ.get('GEMINI_API_KEY', 'ausente'))",
                 "nome": "teste-env"},
                lambda *_: True, "teste")
        self.assertIn("ausente", saida)
        self.assertNotIn("segredo-de-teste", saida)

    def test_linguagem_desconhecida_nao_executa(self):
        saida = ferramentas.executar("rodar_codigo", {"linguagem": "ruby", "codigo": "puts 1"},
                                     lambda *_: True, "teste")
        self.assertIn("Só sei rodar", saida)

    def test_codigo_vazio_nao_executa(self):
        saida = ferramentas.executar("rodar_codigo", {"linguagem": "python", "codigo": "   "},
                                     lambda *_: True, "teste")
        self.assertIn("Não há código", saida)


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.pasta = Path.home() / "Documents" / "ultron-test-site"
        self.addCleanup(lambda: shutil.rmtree(self.pasta, ignore_errors=True))

    def test_criar_site_grava_html_na_allowlist(self):
        saida = ferramentas.executar(
            "criar_site",
            {"pasta": str(self.pasta), "nome": "meu-site", "titulo": "Olá <mundo>",
             "conteudo": "Primeiro parágrafo.\n\nSegundo parágrafo."},
            lambda *_: True, "teste")
        arquivo = self.pasta / "meu-site.html"
        self.assertTrue(arquivo.is_file(), saida)
        html = arquivo.read_text(encoding="utf-8")
        self.assertIn("Olá &lt;mundo&gt;", html)
        self.assertIn("<p>Primeiro parágrafo.</p>", html)
        self.assertIn("<p>Segundo parágrafo.</p>", html)

    def test_criar_site_nao_sobrescreve(self):
        self.pasta.mkdir(parents=True, exist_ok=True)
        (self.pasta / "existente.html").write_text("antigo", encoding="utf-8")
        saida = ferramentas.executar(
            "criar_site",
            {"pasta": str(self.pasta), "nome": "existente", "titulo": "Novo"},
            lambda *_: True, "teste")
        self.assertIn("já existe", saida)
        self.assertEqual((self.pasta / "existente.html").read_text(encoding="utf-8"), "antigo")

    def test_criar_site_fora_da_allowlist_pede_confirmacao(self):
        fora = str(Path.home().parent / "ultron-fora-da-home")
        cls = ferramentas.FERRAMENTAS["criar_site"]["classificar"](pasta=fora, nome="x")
        self.assertFalse(cls.na_allowlist)


class PalcoFerramentaTests(unittest.TestCase):
    def test_mostrar_na_interface_delega_para_o_modulo_do_palco(self):
        with patch("palco.mostrar",
                   return_value={"ok": True, "mensagem": "Mostrado no palco."}) as mostrar:
            saida = ferramentas.executar(
                "mostrar_na_interface", {"tipo": "texto", "alvo": "oi"},
                lambda *_: True, "teste")
        self.assertEqual(saida, "Mostrado no palco.")
        mostrar.assert_called_once_with("texto", "oi", "")

    def test_erro_do_palco_vira_texto_sem_excecao(self):
        with patch("palco.mostrar", return_value={"ok": False, "erro": "área protegida"}):
            saida = ferramentas.executar(
                "mostrar_na_interface", {"tipo": "video", "alvo": "x.mp4"},
                lambda *_: True, "teste")
        self.assertIn("Não consegui mostrar", saida)
        self.assertIn("área protegida", saida)


if __name__ == "__main__":
    unittest.main()
