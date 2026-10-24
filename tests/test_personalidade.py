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


if __name__ == "__main__":
    unittest.main()
