"""Autoconhecimento em runtime: bloco do system prompt derivado do sistema vivo."""
import os
import unittest
from unittest import mock

import autoconhecimento
import cerebro
import ferramentas
import personalidade


class BlocoTests(unittest.TestCase):
    def setUp(self):
        autoconhecimento._CACHE.update(ts=0.0, texto="")

    def test_traz_identidade_sistema_e_habilidades(self):
        texto = autoconhecimento.bloco()
        self.assertIn("Autoconhecimento", texto)
        self.assertIn("- Nome:", texto)
        self.assertIn("- Sistema:", texto)
        self.assertIn("- Versão:", texto)
        self.assertIn("ferramentas", texto)
        self.assertIn("- Limites fixos:", texto)
        self.assertIn("- Segurança:", texto)
        self.assertIn("- Voz:", texto)

    def test_limites_sao_os_decididos_pelo_produto(self):
        texto = autoconhecimento.bloco()
        for limite in autoconhecimento.LIMITES:
            self.assertIn(limite, texto)

    def test_contagem_de_ferramentas_bate_com_o_registro(self):
        total, resumo = autoconhecimento._grupos()
        self.assertEqual(total, len(ferramentas.FERRAMENTAS))
        numeros = [int(pedaco.rsplit("(", 1)[1].rstrip(")")) for pedaco in resumo.split("; ")]
        self.assertEqual(sum(numeros), total)

    def test_ferramenta_desconhecida_cai_em_outras(self):
        registro = dict(ferramentas.FERRAMENTAS)
        registro["ferramenta_de_plugin"] = {"risco": "baixo"}
        with mock.patch.object(ferramentas, "FERRAMENTAS", registro):
            total, resumo = autoconhecimento._grupos()
        self.assertEqual(total, len(registro))
        self.assertIn("outras (1)", resumo)

    def test_nome_vem_do_perfil_ativo(self):
        perfil = dict(personalidade.carregar())
        perfil.update({"rotulo": "NOVA", "perfil": "ultron", "jeito": "equilibrado"})
        with mock.patch.object(personalidade, "carregar", lambda: perfil):
            texto = autoconhecimento.bloco(forcar=True)
        self.assertIn("Nome: NOVA", texto)
        self.assertIn("perfil ultron", texto)
        self.assertIn("Jeito atual: Equilibrado", texto)

    def test_nao_vaza_caminho_nem_usuario(self):
        texto = autoconhecimento.bloco()
        self.assertNotIn(str(autoconhecimento.RAIZ), texto)
        usuario = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if usuario:
            self.assertNotIn(usuario, texto)

    def test_cache_evita_recalculo(self):
        autoconhecimento.bloco(forcar=True)
        with mock.patch.object(autoconhecimento, "_estatico", side_effect=AssertionError("recalculou")):
            texto = autoconhecimento.bloco()
        self.assertIn("Autoconhecimento", texto)

    def test_falha_na_leitura_nao_impede_resposta(self):
        with mock.patch.object(autoconhecimento, "_estatico", side_effect=OSError("sem WMI")):
            texto = autoconhecimento.bloco(forcar=True)
        self.assertIn("Autoconhecimento", texto)
        self.assertIn("não consegui ler", texto)

    def test_system_prompt_inclui_o_bloco_e_o_nome(self):
        texto = cerebro._system()
        self.assertIn("Autoconhecimento", texto)
        self.assertIn("Seu nome é", texto)
        self.assertIn("- Sistema:", texto)


if __name__ == "__main__":
    unittest.main()
