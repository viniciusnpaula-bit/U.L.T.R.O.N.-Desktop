import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memoria


class MemoriaTests(unittest.TestCase):
    """A memória de fatos precisa sobreviver a "%" e "_" e recusar abusos."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "teste.db"
        import sqlite3
        self.conexao = sqlite3.connect(str(self.db))
        self.conexao.executescript("""
        CREATE TABLE IF NOT EXISTS mensagens(id INTEGER PRIMARY KEY, ts REAL, papel TEXT, texto TEXT);
        CREATE TABLE IF NOT EXISTS fatos(id INTEGER PRIMARY KEY, texto TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS lembretes(id INTEGER PRIMARY KEY, due REAL, texto TEXT, feito INTEGER DEFAULT 0);
        """)
        self.patch = patch.object(memoria, "_db", self.conexao)
        self.patch.start()

        def fechar():
            self.patch.stop()
            self.conexao.close()      # no Windows, fechar antes de apagar a pasta
        self.addCleanup(fechar)

    def fatos(self):
        return self.conexao.execute("SELECT texto FROM fatos ORDER BY id").fetchall()

    def test_curinga_nao_apaga_tudo(self):
        memoria.salvar_fato("senha do wifi é abacaxi")
        memoria.salvar_fato("gosto de café sem açúcar")
        # antes, "%%%" apagava todos os fatos; agora é recusado
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.apagar_fato("%%%")
        self.assertEqual(len(self.fatos()), 2)
        # e mesmo quando passa do mínimo, "%" continua sendo texto, não curinga
        memoria.salvar_fato("progresso 100% concluído")
        memoria.apagar_fato("100%")
        self.assertEqual(len(self.fatos()), 2)

    def test_underline_e_tratado_como_texto(self):
        memoria.salvar_fato("arquivo a_b.txt está na área de trabalho")
        memoria.salvar_fato("nada a ver")
        # "_" não pode virar curinga: o trecho só apaga o fato que o contém
        memoria.salvar_fato("nota axb qualquer")
        self.assertEqual(memoria.apagar_fato("arquivo a_b.txt"), 1)
        self.assertEqual(sorted(f[0] for f in self.fatos()),
                         ["nada a ver", "nota axb qualquer"])

    def test_busca_curta_demais_e_recusada(self):
        memoria.salvar_fato("senha do wifi é abacaxi")
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.apagar_fato("%")
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.apagar_fato("ab")
        self.assertEqual(len(self.fatos()), 1)

    def test_trecho_longo_apaga_o_fato_certo(self):
        memoria.salvar_fato("senha do wifi é abacaxi")
        memoria.salvar_fato("aniversário em maio")
        self.assertEqual(memoria.apagar_fato("wifi"), 1)
        self.assertEqual([f[0] for f in self.fatos()], ["aniversário em maio"])

    def test_fato_longo_demais_e_recusado(self):
        with patch.object(memoria, "_limites", return_value=(50, 50, 3)):
            with self.assertRaises(memoria.MemoriaLimite):
                memoria.salvar_fato("x" * 51)

    def test_limite_total_de_fatos(self):
        with patch.object(memoria, "_limites", return_value=(300, 2, 3)):
            memoria.salvar_fato("primeiro fato")
            memoria.salvar_fato("segundo fato")
            with self.assertRaises(memoria.MemoriaLimite):
                memoria.salvar_fato("terceiro fato")

    def test_fato_vazio_e_recusado(self):
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.salvar_fato("   ")


if __name__ == "__main__":
    unittest.main()
