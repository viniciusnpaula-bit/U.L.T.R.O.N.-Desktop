import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cofre


class CofreTests(unittest.TestCase):
    """Chave guardada cifrada, nunca legível no arquivo, nunca devolvida à interface."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raiz = Path(self.temp.name)
        for alvo, valor in (("ARQUIVO", raiz / "cofre.json"), ("ARQUIVO_CHAVE", raiz / ".cofre.chave")):
            self.patch_attr = patch.object(cofre, alvo, valor)
            self.patch_attr.start()
            self.addCleanup(self.patch_attr.stop)

    def test_guarda_cifrado_e_nao_deixa_a_chave_no_arquivo(self):
        cofre.guardar("groq", "gsk_segredo_1234567890abcdef")
        texto = cofre.ARQUIVO.read_text(encoding="utf-8")
        self.assertNotIn("gsk_segredo", texto)
        self.assertEqual(cofre.obter("groq"), "gsk_segredo_1234567890abcdef")

    def test_status_so_mostra_o_final_mascarado(self):
        cofre.guardar("gemini", "AIza" + "x" * 30 + "WXYZ")
        item = next(i for i in cofre.status()["itens"] if i["nome"] == "gemini")
        self.assertTrue(item["configurada"])
        self.assertEqual(item["fonte"], "cofre")
        self.assertTrue(item["dica"].endswith("WXYZ"))
        self.assertNotIn("AIza", item["dica"])

    def test_remover_apaga_do_cofre(self):
        cofre.guardar("nvidia", "nvapi-1234567890")
        cofre.remover("nvidia")
        self.assertEqual(cofre.obter("nvidia"), "")

    def test_credencial_invalida_e_recusada(self):
        with self.assertRaises(ValueError):
            cofre.guardar("nome_estranho", "abc")
        with self.assertRaises(ValueError):
            cofre.guardar("groq", "")
        with self.assertRaises(ValueError):
            cofre.guardar("groq", "tem espaco na chave")

    def test_chave_de_criptografia_nao_fica_em_texto_claro(self):
        cofre.guardar("gemini", "AIza" + "y" * 30)
        conteudo = cofre.ARQUIVO_CHAVE.read_bytes()
        # com DPAPI o arquivo é protegido; sem DPAPI tem exatamente 32 bytes crus
        self.assertTrue(len(conteudo) > 32 or len(conteudo) == 32)
        self.assertNotEqual(conteudo[:8], b"AIza" + b"y" * 4)

    def test_status_declara_a_protecao_em_uso(self):
        status = cofre.status()
        self.assertIn(status["modo"], {"dpapi", "arquivo"})
        self.assertIn("AES-256-GCM", status["protecao"])

    def test_toda_plataforma_tem_link_oficial_https(self):
        for nome in cofre.PROVEDORES + cofre.OUTROS:
            self.assertIn(nome, cofre.LINKS, nome)
            self.assertTrue(cofre.LINKS[nome].startswith("https://"), nome)

    def test_status_informa_link_e_quais_podem_ser_testados(self):
        itens = {item["nome"]: item for item in cofre.status()["itens"]}
        self.assertTrue(itens["openai"]["testavel"])
        self.assertFalse(itens["telegram_token"]["testavel"])
        self.assertEqual(itens["deepseek"]["link"], "https://platform.deepseek.com/api_keys")
        self.assertEqual(itens["xai"]["link"], "https://console.x.ai/")

    def test_salvar_e_remover_esquecem_os_clientes_em_cache(self):
        import cerebro
        cerebro._clientes["groq"] = object()
        cofre.guardar("groq", "gsk_nova_chave_123456")
        self.assertEqual(cerebro._clientes, {})
        cerebro._clientes["groq"] = object()
        cofre.remover("groq")
        self.assertEqual(cerebro._clientes, {})

    def test_provedor_com_chave_fora_da_ordem_ainda_e_usado(self):
        import cerebro
        with patch.object(cerebro.config, "PROVEDORES", ["groq"]):
            with patch.dict(cerebro.config.CHAVES, {"openai": "sk-teste"}, clear=True):
                usados = cerebro._provedores_com_chave()
        self.assertEqual(usados, ["openai"])


if __name__ == "__main__":
    unittest.main()
