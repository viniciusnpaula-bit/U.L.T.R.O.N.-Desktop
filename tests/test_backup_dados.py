import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.backup_dados import criar_backup


class BackupDadosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dados = Path(self.temp.name) / "dados"
        self.dados.mkdir()
        (self.dados / "ultron.db").write_bytes(b"banco")
        (self.dados / ".cofre.chave").write_bytes(b"chave")
        self.zip = Path(self.temp.name) / "saida" / "backup.zip"

    def test_zip_leva_banco_e_chave_juntos(self):
        caminho = criar_backup(self.zip, self.dados)
        self.assertEqual(caminho, self.zip)
        with zipfile.ZipFile(caminho) as pacote:
            self.assertEqual(sorted(pacote.namelist()), ["dados/.cofre.chave", "dados/ultron.db"])
            self.assertEqual(pacote.read("dados/ultron.db"), b"banco")
            self.assertEqual(pacote.read("dados/.cofre.chave"), b"chave")

    def test_sem_banco_falha_sem_criar_zip(self):
        (self.dados / "ultron.db").unlink()
        with self.assertRaises(FileNotFoundError):
            criar_backup(self.zip, self.dados)
        self.assertFalse(self.zip.exists())

    def test_sem_chave_leva_so_o_banco(self):
        (self.dados / ".cofre.chave").unlink()
        with zipfile.ZipFile(criar_backup(self.zip, self.dados)) as pacote:
            self.assertEqual(pacote.namelist(), ["dados/ultron.db"])


if __name__ == "__main__":
    unittest.main()
