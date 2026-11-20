import json
import types
import unittest
from unittest.mock import patch

import cerebro
import ferramentas


class NoticiaNoPalcoTest(unittest.TestCase):
    def test_reconhece_pedido_generico_de_noticia(self):
        for texto in ("me mostra as notícias", "Ultron, mostre as manchetes",
                      "quero ver as últimas notícias", "mostre notícias de tecnologia"):
            self.assertIn("noticia", cerebro._acao_rapida(texto) or "", texto)

    def test_nao_intercepta_outros_pedidos(self):
        for texto in ("que horas são", "abra o spotify", "notícias"):
            self.assertNotIn("noticia", cerebro._acao_rapida(texto) or "", texto)

    def test_assunto_especifico_nao_e_interceptado(self):
        self.assertIsNone(cerebro._acao_rapida("mostre a notícia sobre o acidente"))

    def test_tema_entra_no_nome_da_acao(self):
        self.assertEqual(cerebro._acao_rapida("mostre notícias de tecnologia"),
                         "noticia:tecnologia")

    def test_mostra_imagem_e_devolve_so_as_manchetes(self):
        chamadas = []

        def executar(nome, args, confirmar, origem):
            chamadas.append((nome, args))
            if nome == "noticias":
                return ("[DADOS EXTERNOS: terceiros]\n- A\n- B\n\n"
                        "[IMAGEM_DESTAQUE] A || https://x/a.jpg")
            return "ok"

        resposta = cerebro._executar_acao_rapida("noticia", executar, None, "desktop")

        self.assertEqual(resposta, "- A\n- B")
        self.assertEqual([c[0] for c in chamadas], ["noticias", "mostrar_na_interface"])
        self.assertEqual(chamadas[1][1]["tipo"], "imagem")
        self.assertEqual(chamadas[1][1]["alvo"], "https://x/a.jpg")
        self.assertEqual(chamadas[1][1]["titulo"], "A")

    def test_imagem_prefere_media_content(self):
        entrada = {"media_content": [{"url": "https://x/m.jpg"}],
                   "summary": "<img src='https://x/s.jpg'>"}
        self.assertEqual(ferramentas._imagem_da_entrada(entrada), "https://x/m.jpg")

    def test_imagem_cai_para_o_summary(self):
        entrada = {"summary": '<img src="https://x/s.jpg">'}
        self.assertEqual(ferramentas._imagem_da_entrada(entrada), "https://x/s.jpg")

    def test_executar_noticia_prefere_payload_estruturado_de_noticias(self):
        chamadas = []
        payload = json.dumps({
            "tema": "tecnologia",
            "itens": [
                {"titulo": "Matéria 1", "imagem": "https://cdn/1.jpg", "url": "https://g1/1"},
                {"titulo": "Matéria 2", "imagem": "https://cdn/2.jpg", "url": "https://g1/2"},
            ],
        }, ensure_ascii=False)

        def executar(nome, args, confirmar, origem):
            chamadas.append((nome, args))
            if nome == "noticias":
                return (
                    "[DADOS EXTERNOS: terceiros]\n- Matéria 1\n- Matéria 2\n\n"
                    "[IMAGEM_DESTAQUE] Matéria 1 || https://cdn/1.jpg\n\n"
                    f"[PALCO_NOTICIAS] {payload}"
                )
            return "ok"

        resposta = cerebro._executar_acao_rapida("noticia:tecnologia", executar, None, "desktop")
        self.assertEqual(resposta, "- Matéria 1\n- Matéria 2")
        self.assertEqual([c[0] for c in chamadas], ["noticias", "mostrar_na_interface"])
        self.assertEqual(chamadas[1][1]["tipo"], "noticias")
        self.assertEqual(chamadas[1][1]["alvo"], payload)

    def test_noticias_nao_repete_mesma_imagem_entre_materias(self):
        fake_entries = [
            {
                "title": f"Notícia {i}",
                "link": f"https://exemplo.com/materia-{i}",
                "summary": "<p>Texto da matéria</p>",
                "media_content": [{"url": "https://cdn/logo-igual.jpg"}] if i < 2 else [],
            }
            for i in range(5)
        ]
        fake_feed = types.SimpleNamespace(entries=fake_entries)
        og_map = {
            "https://exemplo.com/materia-1": "https://cdn/foto-1.jpg",
            "https://exemplo.com/materia-2": "https://cdn/foto-2.jpg",
            "https://exemplo.com/materia-3": "https://cdn/foto-2.jpg",  # repetida -> deve ser descartada
            "https://exemplo.com/materia-4": "https://cdn/foto-4.jpg",
        }
        orig_auth = ferramentas._AUTORIZADO.set("noticias")
        try:
            with patch("feedparser.parse", return_value=fake_feed), \
                 patch.object(ferramentas, "_og_image_da_materia", side_effect=lambda u: og_map.get(u)):
                saida = ferramentas.noticias("geral")
        finally:
            ferramentas._AUTORIZADO.reset(orig_auth)

        _, json_str = saida.split("[PALCO_NOTICIAS] ", 1)
        dados = json.loads(json_str)
        imagens = [item["imagem"] for item in dados["itens"] if item["imagem"]]
        self.assertEqual(len(imagens), len(set(imagens)))
        self.assertEqual(
            [item["imagem"] for item in dados["itens"]],
            [
                "https://cdn/logo-igual.jpg",
                "https://cdn/foto-1.jpg",
                "https://cdn/foto-2.jpg",
                "",
                "https://cdn/foto-4.jpg",
            ],
        )

    def test_acao_rapida_aceita_tema_com_sobre_ou_palco_sem_pegar_assunto_especifico(self):
        self.assertEqual(
            cerebro._acao_rapida("me mostre notícias sobre tecnologia no modo palco"),
            "noticia:tecnologia",
        )
        self.assertEqual(
            cerebro._acao_rapida("notícias sobre tecnologia no palco"),
            "noticia:tecnologia",
        )
        self.assertIsNone(cerebro._acao_rapida("mostre a notícia sobre o acidente"))
        self.assertIsNone(cerebro._acao_rapida("notícias"))

    def test_loop_llm_ao_chamar_noticias_publica_no_palco_e_limpa_payload_da_mensagem(self):
        payload = json.dumps({
            "tema": "tecnologia",
            "itens": [
                {"titulo": "Matéria 1", "imagem": "https://cdn/1.jpg", "url": "https://g1/1"},
            ],
        }, ensure_ascii=False)
        execucoes = []
        chamadas_llm = []

        def chamar(msgs):
            chamadas_llm.append([dict(m) for m in msgs])
            if len(chamadas_llm) == 1:
                return types.SimpleNamespace(
                    content="",
                    tool_calls=[
                        types.SimpleNamespace(
                            id="call_1",
                            function=types.SimpleNamespace(
                                name="noticias",
                                arguments='{"tema": "tecnologia"}',
                            ),
                        )
                    ],
                )
            return types.SimpleNamespace(content="Principais notícias de tecnologia abertas no palco.", tool_calls=[])

        def fake_executar(nome, args, confirmar, origem):
            execucoes.append((nome, args))
            if nome == "noticias":
                return (
                    "[DADOS EXTERNOS: terceiros]\n- Matéria 1\n\n"
                    "[IMAGEM_DESTAQUE] Matéria 1 || https://cdn/1.jpg\n\n"
                    f"[PALCO_NOTICIAS] {payload}"
                )
            return "1 notícias exibidas no palco."

        with patch.object(cerebro, "_chamar", side_effect=chamar), \
                patch.object(cerebro.ferramentas, "executar", side_effect=fake_executar), \
                patch.object(cerebro, "_rastrear"):
            resposta = cerebro._loop([{"role": "user", "content": "notícias"}], lambda *a: True, "desktop")

        self.assertEqual(resposta, "Principais notícias de tecnologia abertas no palco.")
        self.assertEqual(len(execucoes), 2)
        self.assertEqual(execucoes[1][0], "mostrar_na_interface")
        self.assertEqual(execucoes[1][1]["tipo"], "noticias")
        self.assertEqual(execucoes[1][1]["alvo"], payload)
        tool_msg = next(m["content"] for m in chamadas_llm[1] if m.get("role") == "tool")
        self.assertNotIn("[PALCO_NOTICIAS]", tool_msg)
        self.assertNotIn("https://cdn/1.jpg", tool_msg)

    def test_mostrar_na_interface_com_tipo_noticias_e_tema_curto_carrega_feed_estruturado(self):
        fake_feed = types.SimpleNamespace(entries=[{
            "title": "Avanço Tech",
            "link": "https://g1.globo.com/tecnologia/noticia/2026/11/14/teste.ghtml",
            "summary": "<img src='https://s2-g1.glbimg.com/foto.jpg'><p>Resumo curto.</p>",
        }])
        publicado = {}

        def fake_mostrar(tipo="auto", alvo="", titulo=""):
            publicado["tipo"] = tipo
            publicado["alvo"] = alvo
            publicado["titulo"] = titulo
            return {"ok": True, "mensagem": "1 notícias exibidas no palco."}

        confirmar = lambda *a: True
        with patch("feedparser.parse", return_value=fake_feed), \
                patch("palco.mostrar", side_effect=fake_mostrar), \
                patch("palco.estado", return_value=None):
            res = ferramentas.executar(
                "mostrar_na_interface",
                {"tipo": "noticias", "alvo": "tecnologia", "titulo": "Notícias · tecnologia"},
                confirmar,
                origem="desktop",
            )

        self.assertIn("notícias exibidas no palco", res)
        self.assertEqual(publicado["tipo"], "noticias")
        dados = json.loads(publicado["alvo"])
        self.assertEqual(dados["tema"], "tecnologia")
        self.assertEqual(dados["itens"][0]["titulo"], "Avanço Tech")
        self.assertEqual(dados["itens"][0]["imagem"], "https://s2-g1.glbimg.com/foto.jpg")



if __name__ == "__main__":
    unittest.main()
