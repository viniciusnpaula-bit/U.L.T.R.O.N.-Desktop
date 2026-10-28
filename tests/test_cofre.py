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

    def test_dados_cifram_com_aad_propria_e_prefixo_v1(self):
        pacote = cofre.cifrar_dados("lembrar da consulta")
        self.assertTrue(pacote.startswith("v1:"))
        self.assertNotIn("consulta", pacote)
        self.assertEqual(cofre.decifrar_dados(pacote), "lembrar da consulta")
        self.assertTrue(cofre.parece_cifrado(pacote))
        self.assertFalse(cofre.parece_cifrado("texto em claro"))
        # AAD diferente do cofre: um pacote não abre como o outro
        with self.assertRaises(Exception):
            cofre._decifrar(pacote)
        with self.assertRaises(ValueError):
            cofre.decifrar_dados(cofre._cifrar("segredo"))

    def test_pacote_adulterado_levanta_erro(self):
        pacote = cofre.cifrar_dados("conteúdo")
        adulterado = pacote[:-2] + ("AA" if not pacote.endswith("AA") else "BB")
        with self.assertRaises(Exception):
            cofre.decifrar_dados(adulterado)
        with self.assertRaises(ValueError):
            cofre.decifrar_dados("v1:")
        with self.assertRaises(ValueError):
            cofre.decifrar_dados("v1:curto")

    def test_chave_ausente_nao_e_criada_para_ler(self):
        with self.assertRaises(cofre.ChaveIndisponivel):
            cofre.decifrar_dados("v1:" + "A" * 40)
        self.assertFalse(cofre.ARQUIVO_CHAVE.exists())
        self.assertFalse(cofre.chave_disponivel())

    def test_chave_existente_ilegivel_nao_e_sobrescrita(self):
        cofre.ARQUIVO_CHAVE.write_bytes(b"x" * 40)
        with self.assertRaises(cofre.ChaveIndisponivel):
            cofre._chave_local(criar=False)
        self.assertEqual(cofre.ARQUIVO_CHAVE.read_bytes(), b"x" * 40)
        status = cofre.status()
        self.assertEqual(status["modo"], "indisponivel")
        self.assertIn("indisponível", status["protecao"])

    def test_chave_criada_uma_vez_serve_para_cifrar_e_decifrar(self):
        self.assertFalse(cofre.chave_disponivel())
        pacote = cofre.cifrar_dados("primeiro")
        self.assertTrue(cofre.ARQUIVO_CHAVE.exists())
        self.assertTrue(cofre.chave_disponivel())
        self.assertEqual(cofre.decifrar_dados(pacote), "primeiro")
        outro = cofre.cifrar_dados("primeiro")
        self.assertNotEqual(pacote, outro)          # nonce novo a cada gravação
        self.assertEqual(cofre.decifrar_dados(outro), "primeiro")

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
