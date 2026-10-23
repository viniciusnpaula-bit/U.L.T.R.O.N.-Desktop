import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memoria


class CancelarLembreteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        import sqlite3
        self.conexao = sqlite3.connect(str(Path(self.temp.name) / "t.db"))
        self.conexao.executescript("""
        CREATE TABLE mensagens(id INTEGER PRIMARY KEY, ts REAL, papel TEXT, texto TEXT);
        CREATE TABLE fatos(id INTEGER PRIMARY KEY, texto TEXT UNIQUE);
        CREATE TABLE lembretes(id INTEGER PRIMARY KEY, due REAL, texto TEXT, feito INTEGER DEFAULT 0);
        """)
        self.patch = patch.object(memoria, "_db", self.conexao)
        self.patch.start()

        def fechar():
            self.patch.stop()
            self.conexao.close()
        self.addCleanup(fechar)
        memoria.add_lembrete(1000.0, "tomar água")
        memoria.add_lembrete(2000.0, "ligar para a mãe")

    def pendentes(self):
        return [numero["texto"] for numero in memoria.lembretes_numerados()]

    def test_lista_numerada_com_hora_local(self):
        itens = memoria.lembretes_numerados()
        self.assertEqual([i["numero"] for i in itens], [1, 2])
        self.assertRegex(itens[0]["hora_local"], r"^\d{2}/\d{2} \d{2}:\d{2}$")

    def test_cancelar_por_numero(self):
        mensagem = memoria.cancelar_lembrete(numero=1)
        self.assertIn("tomar água", mensagem)
        self.assertEqual(self.pendentes(), ["ligar para a mãe"])

    def test_cancelar_por_trecho(self):
        memoria.cancelar_lembrete(trecho="mãe")
        self.assertEqual(self.pendentes(), ["tomar água"])

    def test_numero_fora_da_lista_e_recusado(self):
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.cancelar_lembrete(numero=9)
        self.assertEqual(len(self.pendentes()), 2)

    def test_sem_alvo_nao_apaga_nada(self):
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.cancelar_lembrete()
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.cancelar_lembrete(trecho="am")
        self.assertEqual(len(self.pendentes()), 2)

    def test_trecho_ambiguo_pede_numero(self):
        memoria.add_lembrete(3000.0, "ligar para o banco")
        with self.assertRaises(memoria.MemoriaLimite) as contexto:
            memoria.cancelar_lembrete(trecho="ligar")
        self.assertIn("número", str(contexto.exception))
        self.assertEqual(len(self.pendentes()), 3)


if __name__ == "__main__":
    unittest.main()
