import sys
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


if __name__ == "__main__":
    unittest.main()
