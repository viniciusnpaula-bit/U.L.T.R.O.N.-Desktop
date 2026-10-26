import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arquivos


class CompactarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_compacta_arquivo_e_extrai_de_volta(self):
        origem = self.base / "nota.txt"
        origem.write_text("conteúdo", encoding="utf-8")
        feito = arquivos.compactar(origem)
        self.assertTrue(feito["ok"], feito)
        self.assertTrue(feito["destino"].is_file())
        with zipfile.ZipFile(feito["destino"]) as z:
            self.assertEqual(z.namelist(), ["nota.txt"])
        destino = self.base / "saida"
        extraido = arquivos.descompactar(feito["destino"], destino)
        self.assertTrue(extraido["ok"], extraido)
        self.assertEqual((destino / "nota.txt").read_text(encoding="utf-8"), "conteúdo")

    def test_compacta_pasta_preservando_o_nome(self):
        pasta = self.base / "projetos"
        (pasta / "sub").mkdir(parents=True)
        (pasta / "a.txt").write_text("a", encoding="utf-8")
        (pasta / "sub" / "b.txt").write_text("b", encoding="utf-8")
        feito = arquivos.compactar(pasta)
        self.assertTrue(feito["ok"], feito)
        with zipfile.ZipFile(feito["destino"]) as z:
            nomes = set(z.namelist())
        self.assertEqual(nomes, {"projetos/a.txt", "projetos/sub/b.txt"})

    def test_nao_sobrescreve_zip_existente(self):
        origem = self.base / "nota.txt"
        origem.write_text("x", encoding="utf-8")
        (self.base / "nota.txt.zip").write_text("ocupado", encoding="utf-8")
        feito = arquivos.compactar(origem)
        self.assertFalse(feito["ok"])
        self.assertIn("já existe", feito["motivo"])

    def test_recusa_zip_com_caminho_para_fora(self):
        malicioso = self.base / "mau.zip"
        with zipfile.ZipFile(malicioso, "w") as z:
            z.writestr("../fora.txt", "invasão")
        resultado = arquivos.descompactar(malicioso, self.base / "saida")
        self.assertFalse(resultado["ok"])
        self.assertIn("insegura", resultado["motivo"])
        self.assertFalse((self.base / "fora.txt").exists())

    def test_recusa_destino_nao_vazio(self):
        zipado = self.base / "a.zip"
        with zipfile.ZipFile(zipado, "w") as z:
            z.writestr("a.txt", "a")
        destino = self.base / "destino"
        destino.mkdir()
        (destino / "existente.txt").write_text("x", encoding="utf-8")
        resultado = arquivos.descompactar(zipado, destino)
        self.assertFalse(resultado["ok"])
        self.assertIn("não está vazia", resultado["motivo"])


class OrganizarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_move_por_categoria_sem_sobrescrever(self):
        (self.base / "foto.jpg").write_bytes(b"x")
        (self.base / "nota.txt").write_text("n", encoding="utf-8")
        (self.base / "programa.exe").write_bytes(b"x")
        (self.base / "Documentos").mkdir()
        (self.base / "Documentos" / "nota.txt").write_text("antigo", encoding="utf-8")

        resultado = arquivos.organizar(self.base)
        self.assertEqual(resultado["total"], 3)
        self.assertEqual(resultado["erros"], [])
        self.assertTrue((self.base / "Imagens" / "foto.jpg").is_file())
        self.assertTrue((self.base / "Instaladores" / "programa.exe").is_file())
        # o arquivo que já existia não foi tocado; o novo entrou como "nota (2).txt"
        self.assertEqual((self.base / "Documentos" / "nota.txt").read_text(encoding="utf-8"), "antigo")
        self.assertTrue((self.base / "Documentos" / "nota (2).txt").is_file())

    def test_plano_nao_move_nada(self):
        (self.base / "a.pdf").write_bytes(b"x")
        plano = arquivos.plano_organizacao(self.base)
        self.assertEqual(list(plano), ["Documentos"])
        self.assertTrue((self.base / "a.pdf").is_file())
        self.assertFalse((self.base / "Documentos").exists())


if __name__ == "__main__":
    unittest.main()
