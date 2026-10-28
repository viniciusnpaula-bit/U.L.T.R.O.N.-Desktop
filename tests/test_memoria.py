import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cofre
import memoria


class MemoriaTests(unittest.TestCase):
    """Fatos cifrados em repouso, com migração e busca ainda corretas."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raiz = Path(self.temp.name)
        self.conexao = sqlite3.connect(str(raiz / "teste.db"))
        self.conexao.executescript("""
        CREATE TABLE IF NOT EXISTS mensagens(id INTEGER PRIMARY KEY, ts REAL, papel TEXT, texto TEXT);
        CREATE TABLE IF NOT EXISTS fatos(id INTEGER PRIMARY KEY, texto TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS lembretes(id INTEGER PRIMARY KEY, due REAL, texto TEXT, feito INTEGER DEFAULT 0);
        """)
        self.conexao.execute("PRAGMA user_version=0")
        self.conexao.commit()
        for alvo, nome, valor in ((memoria, "_db", self.conexao),
                                  (cofre, "ARQUIVO_CHAVE", raiz / ".cofre.chave")):
            item = patch.object(alvo, nome, valor)
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.conexao.close)

    def fatos(self):
        return memoria.listar_fatos()

    def crus(self):
        return [linha[0] for linha in self.conexao.execute("SELECT texto FROM fatos ORDER BY id")]

    def test_curinga_nao_apaga_tudo(self):
        memoria.salvar_fato("senha do wifi é abacaxi")
        memoria.salvar_fato("gosto de café sem açúcar")
        with self.assertRaises(memoria.MemoriaLimite):
            memoria.apagar_fato("%%%")
        self.assertEqual(len(self.fatos()), 2)
        memoria.salvar_fato("progresso 100% concluído")
        memoria.apagar_fato("100%")
        self.assertEqual(len(self.fatos()), 2)

    def test_underline_e_tratado_como_texto(self):
        memoria.salvar_fato("arquivo a_b.txt está na área de trabalho")
        memoria.salvar_fato("nada a ver")
        memoria.salvar_fato("nota axb qualquer")
        self.assertEqual(memoria.apagar_fato("arquivo a_b.txt"), 1)
        self.assertEqual(sorted(self.fatos()), ["nada a ver", "nota axb qualquer"])

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
        self.assertEqual(self.fatos(), ["aniversário em maio"])

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

    def test_grava_cifrado_e_decifra_na_leitura(self):
        memoria.salvar_fato("senha do wifi é abacaxi")
        cru = self.crus()[0]
        self.assertTrue(cru.startswith("v1:"))
        self.assertNotIn("abacaxi", cru)
        self.assertEqual(self.fatos(), ["senha do wifi é abacaxi"])

    def test_migra_texto_em_claro_uma_vez(self):
        self.conexao.execute("INSERT INTO fatos(texto) VALUES(?)", ("aniversário em maio",))
        self.conexao.execute("INSERT INTO mensagens(ts, papel, texto) VALUES(?,?,?)",
                             (1.0, "user", "a impressora travou"))
        self.conexao.commit()
        self.assertEqual(self.fatos(), ["aniversário em maio"])
        self.assertTrue(all(texto.startswith("v1:") for texto in self.crus()))
        self.assertEqual(self.conexao.execute("PRAGMA user_version").fetchone()[0], 1)
        linhas = self.conexao.execute("SELECT texto FROM mensagens").fetchall()
        self.assertTrue(all(texto.startswith("v1:") for (texto,) in linhas))
        self.assertEqual(memoria.historico(), [{"role": "user", "content": "a impressora travou"}])
        antes = self.crus()
        memoria._garantir_migracao()
        self.assertEqual(self.crus(), antes)

    def test_linha_corrompida_e_ignorada(self):
        memoria.salvar_fato("fato bom")
        self.conexao.execute("INSERT INTO fatos(texto) VALUES(?)", ("v1:nao-e-base64",))
        self.conexao.commit()
        self.assertEqual(self.fatos(), ["fato bom"])

    def test_linha_sem_prefixo_depois_da_migracao_nao_aparece(self):
        memoria._garantir_migracao()
        self.conexao.execute("INSERT INTO fatos(texto) VALUES(?)", ("texto em claro",))
        self.conexao.commit()
        self.assertEqual(self.fatos(), [])

    def test_chave_ilegivel_degrada_sem_sobrescrever(self):
        memoria.salvar_fato("fato antigo")
        cofre.ARQUIVO_CHAVE.write_bytes(b"x" * 40)
        antes = cofre.ARQUIVO_CHAVE.read_bytes()
        self.assertEqual(self.fatos(), [])
        memoria.salvar_fato("fato novo")
        self.assertEqual(cofre.ARQUIVO_CHAVE.read_bytes(), antes)
        self.assertEqual(memoria.status_criptografia()["chave"], "indisponivel")

    def test_lembretes_e_busca_funcionam_cifrados(self):
        memoria.add_lembrete(1.0, "pagar a conta de luz")
        self.assertEqual(memoria.lembretes_vencidos()[0][1], "pagar a conta de luz")
        self.assertEqual(memoria.lembretes_numerados()[0]["texto"], "pagar a conta de luz")
        self.assertEqual(memoria.cancelar_lembrete(trecho="conta de luz"),
                         "Lembrete cancelado: pagar a conta de luz")
        memoria.salvar_fato("arquivo a_b.txt")
        memoria.salvar_fato("progresso 100% concluído")
        self.assertEqual(memoria.buscar_fatos("a_b")[0]["texto"], "arquivo a_b.txt")
        # "%" é literal: só encontra o fato que realmente tem o sinal
        self.assertEqual(memoria.buscar_fatos("%")[0]["texto"], "progresso 100% concluído")

    def test_status_criptografia_nao_levanta(self):
        status = memoria.status_criptografia()
        self.assertEqual(status["algoritmo"], "AES-256-GCM")
        self.assertIn(status["chave"], {"DPAPI", "arquivo", "indisponivel"})
        self.assertIn("migrado", status)


if __name__ == "__main__":
    unittest.main()
