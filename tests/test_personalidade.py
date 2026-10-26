import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import personalidade


class PersonalidadeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.arquivo = Path(self.temp.name) / "personalidade.json"
        self.patch = patch.object(personalidade, "ARQUIVO", self.arquivo)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_sem_arquivo_usa_o_padrao(self):
        atual = personalidade.carregar()
        self.assertEqual(atual["perfil"], "ultron")
        self.assertEqual(atual["tratamento"], "senhor")

    def test_perfil_muda_tom_e_e_persistido(self):
        personalidade.salvar({"perfil": "edith", "tratamento": "comandante"})
        atual = personalidade.carregar()
        self.assertEqual(atual["perfil"], "edith")
        self.assertEqual(atual["tratamento"], "comandante")
        self.assertIn("tático", atual["tom"])

    def test_arquivo_corrompido_volta_ao_padrao_sem_quebrar(self):
        self.arquivo.write_text("{isso nao é json", encoding="utf-8")
        self.assertEqual(personalidade.carregar()["perfil"], "ultron")

    def test_restaurar_padrao_apaga_o_arquivo(self):
        personalidade.salvar({"perfil": "jarvis"})
        personalidade.restaurar_padrao()
        self.assertFalse(self.arquivo.exists())
        self.assertEqual(personalidade.carregar()["perfil"], "ultron")

    def test_frase_do_sistema_reflete_a_escolha(self):
        personalidade.salvar({"perfil": "jarvis", "tratamento": "meu senhor"})
        frase = personalidade.frase_do_sistema()
        self.assertIn("meu senhor", frase)
        self.assertIn("JARVIS" if "JARVIS" in frase else "formal", frase)

    def test_perfil_invalido_nao_quebra(self):
        salvo = personalidade.salvar({"perfil": "inexistente"})
        self.assertEqual(salvo["perfil"], "ultron")

    def test_cada_perfil_guarda_o_proprio_tratamento(self):
        personalidade.salvar({"perfil": "ultron", "tratamento": "senhor"})
        personalidade.salvar({"perfil": "jarvis", "tratamento": "meu senhor"})
        atual = personalidade.carregar()
        self.assertEqual(atual["perfil"], "jarvis")
        self.assertEqual(atual["tratamento"], "meu senhor")
        self.assertEqual(atual["tratamentos"]["ultron"], "senhor")
        # voltar ao ULTRON devolve o tratamento dele, não o do JARVIS
        voltou = personalidade.salvar({"perfil": "ultron"})
        self.assertEqual(voltou["tratamento"], "senhor")
        self.assertEqual(voltou["tratamentos"]["jarvis"], "meu senhor")

    def test_arquivo_antigo_migra_o_tratamento_para_o_perfil_ativo(self):
        self.arquivo.write_text(
            json.dumps({"perfil": "edith", "tratamento": "comandante"}), encoding="utf-8")
        atual = personalidade.carregar()
        self.assertEqual(atual["perfil"], "edith")
        self.assertEqual(atual["tratamento"], "comandante")
        self.assertEqual(atual["tratamentos"]["edith"], "comandante")
        self.assertEqual(atual["tratamentos"]["ultron"], "senhor")

    def test_perfis_disponiveis_trazem_o_tratamento_de_cada_um(self):
        personalidade.salvar({"perfil": "visao", "tratamento": "doutor"})
        perfis = {p["id"]: p["tratamento"] for p in personalidade.perfis_disponiveis()}
        self.assertEqual(perfis["visao"], "doutor")
        self.assertEqual(perfis["ultron"], "senhor")

    def test_padrao_traz_jeito_neutro_e_saudacao_ligada(self):
        atual = personalidade.carregar()
        self.assertEqual(atual["jeito"], "equilibrado")
        self.assertTrue(atual["saudacao"])
        self.assertEqual(atual["usuario"], {
            "nome": "", "apelido": "", "idade": "", "genero": "", "sobre": "",
        })

    def test_jeito_valido_e_persistido_e_invalido_nao_quebra(self):
        personalidade.salvar({"jeito": "mordomo"})
        self.assertEqual(personalidade.carregar()["jeito"], "mordomo")
        salvo = personalidade.salvar({"jeito": "inexistente"})
        self.assertEqual(salvo["jeito"], "mordomo")

    def test_jeitos_disponiveis_tem_catalogo_estavel(self):
        jeitos = personalidade.jeitos_disponiveis()
        ids = [item["id"] for item in jeitos]
        self.assertGreaterEqual(len(ids), 8)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("equilibrado", ids)
        for item in jeitos:
            self.assertTrue(item["rotulo"])
            self.assertTrue(item["descricao"])
            self.assertTrue(item["tom"])
            self.assertTrue(item["instrucao"])
            self.assertIsInstance(item["exemplos"], list)

    def test_cada_jeito_tem_regra_de_fala_concreta(self):
        for chave, jeito in personalidade.JEITOS.items():
            self.assertTrue(jeito["instrucao"].strip(), chave)
            if chave == personalidade.PADRAO_JEITO:
                self.assertEqual(jeito["exemplos"], [], chave)
            else:
                self.assertTrue(jeito["exemplos"], chave)
                for exemplo in jeito["exemplos"]:
                    self.assertTrue(exemplo.strip(), chave)

    def test_dados_do_usuario_sao_saneados(self):
        personalidade.salvar({"usuario": {
            "nome": "  " + "Pedro" * 20 + "  ",
            "apelido": "Pedrinho",
            "idade": "150",
            "genero": "PREFIRO NÃO DIZER",
            "sobre": "trabalha com design",
        }})
        usuario = personalidade.carregar()["usuario"]
        self.assertEqual(len(usuario["nome"]), 60)
        self.assertEqual(usuario["apelido"], "Pedrinho")
        self.assertEqual(usuario["idade"], "")
        self.assertEqual(usuario["genero"], "prefiro não dizer")
        self.assertEqual(usuario["sobre"], "trabalha com design")

    def test_genero_e_idade_invalidos_viram_vazio(self):
        personalidade.salvar({"usuario": {"idade": "abc", "genero": "alienígena"}})
        usuario = personalidade.carregar()["usuario"]
        self.assertEqual(usuario["idade"], "")
        self.assertEqual(usuario["genero"], "")

    def test_salvar_so_o_jeito_preserva_os_dados_do_usuario(self):
        personalidade.salvar({"usuario": {"nome": "Ana"}, "saudacao": False})
        personalidade.salvar({"jeito": "amigo"})
        atual = personalidade.carregar()
        self.assertEqual(atual["usuario"]["nome"], "Ana")
        self.assertFalse(atual["saudacao"])
        self.assertEqual(atual["jeito"], "amigo")

    def test_saudacao_desligada_e_persistida(self):
        personalidade.salvar({"saudacao": False})
        self.assertFalse(personalidade.saudacao_ao_abrir())
        personalidade.salvar({"saudacao": True})
        self.assertTrue(personalidade.saudacao_ao_abrir())

    def test_frase_do_sistema_inclui_jeito_e_dados_do_usuario(self):
        personalidade.salvar({
            "jeito": "mordomo",
            "usuario": {"nome": "Pedro", "apelido": "Pedrinho", "sobre": "gosta de café"},
        })
        frase = personalidade.frase_do_sistema()
        self.assertIn("Jeito:", frase)
        self.assertIn("Pedro", frase)
        self.assertIn("Pedrinho", frase)
        self.assertIn("gosta de café", frase)
        self.assertIn("nenhum jeito muda as regras de segurança", frase)

    def test_jeito_equilibrado_nao_forca_modo_de_fala(self):
        personalidade.salvar({"jeito": "equilibrado"})
        frase = personalidade.frase_do_sistema()
        self.assertNotIn("MODO DE FALA OBRIGATÓRIO", frase)
        self.assertTrue(frase.startswith("Personalidade:"))

    def test_jeito_ignorante_abre_o_prompt_com_modo_obrigatorio(self):
        personalidade.salvar({"jeito": "ignorante"})
        frase = personalidade.frase_do_sistema()
        # a regra vem antes de tudo e nomeia o estilo
        self.assertTrue(frase.startswith("MODO DE FALA OBRIGATÓRIO — IGNORANTE"))
        self.assertLess(frase.index("MODO DE FALA OBRIGATÓRIO"), frase.index("Personalidade:"))
        self.assertIn("prioridade sobre o tom do perfil", frase)
        self.assertIn(personalidade.JEITOS["ignorante"]["instrucao"], frase)
        for exemplo in personalidade.JEITOS["ignorante"]["exemplos"]:
            self.assertIn(exemplo.rstrip("."), frase)
        # vale em toda resposta e não fura a segurança
        self.assertIn("TODA resposta", frase)
        self.assertIn("não responda no tom neutro", frase)
        self.assertIn("nunca muda as regras de segurança", frase)
        self.assertIn("Nunca seja hostil", frase)

    def test_todos_os_jeitos_nao_neutros_levam_o_bloco(self):
        for chave, jeito in personalidade.JEITOS.items():
            if chave == personalidade.PADRAO_JEITO:
                continue
            personalidade.salvar({"jeito": chave})
            frase = personalidade.frase_do_sistema()
            self.assertTrue(
                frase.startswith(f"MODO DE FALA OBRIGATÓRIO — {jeito['rotulo'].upper()}"), chave)
            self.assertIn(jeito["instrucao"], frase, chave)

    def test_frase_de_saudacao_usa_perfil_e_tratamento(self):
        personalidade.salvar({"perfil": "jarvis", "tratamento": "meu senhor"})
        self.assertEqual(
            personalidade.frase_saudacao(),
            "JARVIS online. À sua disposição, meu senhor.",
        )


if __name__ == "__main__":
    unittest.main()
