import unittest

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


if __name__ == "__main__":
    unittest.main()
