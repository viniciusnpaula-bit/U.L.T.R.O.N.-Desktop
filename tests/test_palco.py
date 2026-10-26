import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import palco


class PalcoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.media = Path.home() / "Documents" / "ultron-test-palco"
        self.media.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.media, ignore_errors=True))
        self.manifest = self.dir / "manifest.json"
        for alvo, valor in (("PALCO_DIR", self.dir), ("MANIFEST", self.manifest)):
            patcher = patch.object(palco, alvo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        palco.fechar()
        palco.eventos()

    def tearDown(self):
        palco.fechar()
        palco.eventos()

    def arquivo(self, nome, conteudo=b"\x00\x01\x02"):
        caminho = self.media / nome
        caminho.write_bytes(conteudo)
        self.addCleanup(caminho.unlink, missing_ok=True)
        return caminho

    def test_video_local_usa_id_opaco_e_registra_o_caminho_no_manifesto(self):
        video = self.arquivo("clip.mp4")
        resultado = palco.mostrar("video", str(video))
        self.assertTrue(resultado["ok"], resultado)
        dados = resultado["palco"]
        self.assertRegex(dados["id"], r"^[a-f0-9]{32}$")
        self.assertEqual(dados["tipo"], "video")
        self.assertEqual(dados["fonte"], f"ultron-palco://media/{dados['id']}")
        self.assertNotIn("caminho", dados)
        self.assertNotIn(str(video), json.dumps(dados, ensure_ascii=False))
        self.assertEqual(palco.estado()["id"], dados["id"])
        manifesto = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifesto[dados["id"]]["caminho"], str(video.resolve()))
        self.assertEqual(palco.eventos()[-1]["type"], "palco_show")

    def test_tipo_auto_reconhece_pela_extensao(self):
        imagem = self.arquivo("foto.png")
        resultado = palco.mostrar("auto", str(imagem))
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["palco"]["tipo"], "imagem")

    def test_arquivo_protegido_e_recusado(self):
        protegido = Path(tempfile.gettempdir()) / "ultron-palco-teste.mp4"
        protegido.write_bytes(b"x")
        self.addCleanup(protegido.unlink, missing_ok=True)
        if not palco._protegido(str(protegido)):
            self.skipTest("temporário fora de uma área protegida neste sistema")
        resultado = palco.mostrar("video", str(protegido))
        self.assertFalse(resultado["ok"])
        self.assertIn("protegida", resultado["erro"])

    def test_extensao_que_nao_e_do_tipo_e_recusada(self):
        texto = self.arquivo("nota.txt", b"oi")
        resultado = palco.mostrar("video", str(texto))
        self.assertFalse(resultado["ok"])
        self.assertIn("não é um video", resultado["erro"])

    def test_pasta_mostra_o_video_mais_recente(self):
        pasta = self.media / "Captures"
        pasta.mkdir()
        antigo = pasta / "antigo.mp4"
        antigo.write_bytes(b"a")
        novo = pasta / "novo.mp4"
        novo.write_bytes(b"b")
        (pasta / "nota.txt").write_text("oi", encoding="utf-8")
        os.utime(antigo, (1000, 1000))
        os.utime(novo, (2000, 2000))
        resultado = palco.mostrar("video", str(pasta))
        self.assertTrue(resultado["ok"], resultado)
        dados = resultado["palco"]
        self.assertEqual(dados["tipo"], "video")
        self.assertEqual(dados["titulo"], "novo.mp4")
        self.assertIn("mais recente", resultado["mensagem"])
        manifesto = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifesto[dados["id"]]["caminho"], str(novo.resolve()))

    def test_pasta_com_tipo_auto_escolhe_a_midia_mais_recente(self):
        pasta = self.media / "mistura"
        pasta.mkdir()
        video = pasta / "clip.mp4"
        video.write_bytes(b"v")
        imagem = pasta / "foto.png"
        imagem.write_bytes(b"i")
        os.utime(video, (1000, 1000))
        os.utime(imagem, (2000, 2000))
        resultado = palco.mostrar("auto", str(pasta))
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["palco"]["tipo"], "imagem")
        self.assertEqual(resultado["palco"]["titulo"], "foto.png")

    def test_pasta_sem_o_tipo_pedido_e_recusada(self):
        pasta = self.media / "so_texto"
        pasta.mkdir()
        (pasta / "nota.txt").write_text("oi", encoding="utf-8")
        resultado = palco.mostrar("video", str(pasta))
        self.assertFalse(resultado["ok"])
        self.assertIn("Não encontrei nenhum video", resultado["erro"])

    def test_file_uri_local_e_aceito(self):
        video = self.arquivo("clip-uri.mp4")
        resultado = palco.mostrar("video", video.as_uri())
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["palco"]["titulo"], "clip-uri.mp4")

    def test_texto_remove_controles_e_nao_escapa_html(self):
        resultado = palco.mostrar("texto", "linha 1\n<b>linha 2</b>\x00", "meu texto")
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["palco"]["conteudo"], "linha 1\n<b>linha 2</b>")
        self.assertEqual(resultado["palco"]["titulo"], "meu texto")
        self.assertEqual(resultado["palco"]["fonte"], "")

    def test_youtube_vira_embed_sem_cookie(self):
        with patch.object(palco, "_url_remota", side_effect=lambda url: url):
            resultado = palco.mostrar("video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(resultado["ok"], resultado)
        dados = resultado["palco"]
        self.assertTrue(dados["embed"])
        self.assertEqual(dados["fonte"],
                         "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0")
        self.assertEqual(dados["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_vimeo_vira_player_isolado(self):
        with patch.object(palco, "_url_remota", side_effect=lambda url: url):
            resultado = palco.mostrar("video", "https://vimeo.com/123456789")
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["palco"]["fonte"],
                         "https://player.vimeo.com/video/123456789?autoplay=1")

    def test_site_local_e_recusado_antes_de_qualquer_requisicao(self):
        resultado = palco.mostrar("site", "http://127.0.0.1:8080/painel")
        self.assertFalse(resultado["ok"])
        self.assertIn("local", resultado["erro"].lower())

    def test_fechar_limpa_o_estado_e_emite_evento(self):
        palco.mostrar("texto", "oi")
        palco.eventos()
        resultado = palco.fechar()
        self.assertTrue(resultado["ok"])
        self.assertIsNone(palco.estado())
        self.assertEqual(palco.eventos(), [{"type": "palco_hide"}])

    def test_tipo_fechar_pela_ferramenta_principal(self):
        palco.mostrar("texto", "oi")
        palco.eventos()
        resultado = palco.mostrar("fechar")
        self.assertTrue(resultado["ok"])
        self.assertIsNone(palco.estado())
        self.assertEqual(palco.eventos(), [{"type": "palco_hide"}])

    def test_manifesto_poda_expirados_e_respeita_o_teto(self):
        agora = time.time()
        expirados = {
            "a": {"expira": agora - 1, "criado": agora - 10},
            "b": {"expira": agora + 100, "criado": agora - 5},
        }
        self.assertEqual(set(palco._podar(expirados)), {"b"})
        muitos = {
            str(indice): {"expira": agora + 100, "criado": indice}
            for indice in range(45)
        }
        limpos = palco._podar(muitos)
        self.assertEqual(len(limpos), palco._MAX_ENTRADAS)
        self.assertNotIn("0", limpos)
        self.assertIn("44", limpos)

    def test_fila_de_eventos_nao_cresce_sem_limite(self):
        palco.eventos()
        for indice in range(80):
            palco._emitir({"type": "teste", "indice": indice})
        eventos = palco.eventos()
        self.assertLessEqual(len(eventos), 33)
        self.assertEqual(eventos[-1]["indice"], 79)


if __name__ == "__main__":
    unittest.main()
