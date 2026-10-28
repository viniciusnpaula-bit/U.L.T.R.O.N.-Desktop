import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cofre
import memoria


class RecallTests(unittest.TestCase):
    """Memória entre sessões: busca local, determinística e sem vazar segredo."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.conexao = sqlite3.connect(str(Path(self.temp.name) / "teste.db"))
        self.conexao.executescript("""
        CREATE TABLE IF NOT EXISTS mensagens(id INTEGER PRIMARY KEY, ts REAL, papel TEXT, texto TEXT);
        CREATE TABLE IF NOT EXISTS fatos(id INTEGER PRIMARY KEY, texto TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS lembretes(id INTEGER PRIMARY KEY, due REAL, texto TEXT, feito INTEGER DEFAULT 0);
        """)
        self.conexao.execute("PRAGMA user_version=0")
        self.conexao.commit()
        for alvo, nome, valor in ((memoria, "_db", self.conexao),
                                  (cofre, "ARQUIVO_CHAVE", Path(self.temp.name) / ".cofre.chave")):
            item = patch.object(alvo, nome, valor)
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.conexao.close)

    def _guardar(self, papel, texto, dias=1):
        memoria._x("INSERT INTO mensagens(ts, papel, texto) VALUES(?,?,?)",
                   (time.time() - dias * 86400, papel, texto))

    def test_encontra_conversa_antiga_pelo_assunto(self):
        self._guardar("user", "a impressora fiscal travou de novo", dias=10)
        self._guardar("assistant", "reiniciei o spooler da impressora", dias=9)

        achados = memoria.recordar("como resolvo a impressora fiscal?", limite=2)

        self.assertEqual(len(achados), 2)
        self.assertEqual(achados[0]["papel"], "user")
        self.assertIn("impressora", achados[0]["texto"])
        self.assertGreater(achados[0]["score"], achados[1]["score"])

    def test_assunto_sem_relacao_nao_volta(self):
        self._guardar("user", "comprei pão e café", dias=3)
        self.assertEqual(memoria.recordar("qual a previsão do tempo?"), [])

    def test_sem_palavra_util_nao_busca(self):
        self._guardar("user", "a impressora travou", dias=3)
        self.assertEqual(memoria.recordar("oi, tudo bem?"), [])

    def test_mais_recente_vem_primeiro_com_o_mesmo_assunto(self):
        self._guardar("user", "enviei o orçamento por e-mail", dias=100)
        self._guardar("user", "o orçamento foi aprovado", dias=2)

        achados = memoria.recordar("e o orçamento?", limite=2)

        self.assertEqual(len(achados), 2)
        self.assertIn("aprovado", achados[0]["texto"])

    def test_limite_e_respeitado(self):
        for indice in range(5):
            self._guardar("user", f"nota fiscal numero {indice}", dias=indice + 1)
        self.assertEqual(len(memoria.recordar("nota fiscal", limite=2)), 2)

    def test_pular_ignora_as_mensagens_da_sessao_atual(self):
        self._guardar("user", "a impressora antiga quebrou", dias=40)
        for _ in range(12):
            self._guardar("user", "a impressora nova chegou hoje", dias=0)

        achados = memoria.recordar("impressora", limite=4, pular=12)

        self.assertEqual(len(achados), 1)
        self.assertIn("antiga", achados[0]["texto"])

    def test_bloco_contexto_monta_trechos_e_redige_segredo(self):
        self._guardar("user", "minha chave antiga era sk-abcdefghijklmnop", dias=5)

        bloco = memoria.bloco_contexto("qual era a chave antiga?")

        self.assertIn("Trechos de conversas anteriores", bloco)
        self.assertIn("usuário:", bloco)
        self.assertIn("***", bloco)
        self.assertNotIn("sk-abcdefghijklmnop", bloco)

    def test_bloco_contexto_vazio_quando_nada_serve(self):
        self.assertEqual(memoria.bloco_contexto("qual a previsão do tempo?"), "")

    def test_bloco_contexto_nao_repete_o_historico_da_sessao(self):
        self._guardar("user", "a impressora fiscal travou", dias=0)
        self.assertEqual(
            memoria.bloco_contexto("impressora fiscal",
                                   recentes=["a impressora fiscal travou"]), "")
        self.assertIn("Trechos de conversas anteriores",
                      memoria.bloco_contexto("impressora fiscal"))

    def test_tokens_sem_acento_sem_repeticao_e_sem_palavra_vazia(self):
        self.assertEqual(memoria._tokens("não é impressão, impressão"), ["impressao"])
        self.assertEqual(memoria._tokens("para você fazer isso"), [])


if __name__ == "__main__":
    unittest.main()
