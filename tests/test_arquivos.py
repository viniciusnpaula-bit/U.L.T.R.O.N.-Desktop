import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
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

    def test_modo_data_agrupa_por_ano_e_mes(self):
        antigo = self.base / "velho.txt"
        antigo.write_text("a", encoding="utf-8")
        recente = self.base / "novo.txt"
        recente.write_text("b", encoding="utf-8")
        os.utime(antigo, (datetime(2023, 5, 10, 12).timestamp(),) * 2)
        os.utime(recente, (datetime(2024, 2, 3, 9).timestamp(),) * 2)

        plano = arquivos.plano_organizacao(self.base, "data")
        self.assertEqual(sorted(plano), ["2023/05", "2024/02"])

        resultado = arquivos.organizar(self.base, "data")
        self.assertEqual(resultado["total"], 2)
        self.assertTrue((self.base / "2023" / "05" / "velho.txt").is_file())
        self.assertTrue((self.base / "2024" / "02" / "novo.txt").is_file())
        # o desfazer precisa dos dois níveis criados para removê-los depois
        self.assertIn(str(self.base / "2023"), resultado["pastas_criadas"])
        self.assertIn(str(self.base / "2023" / "05"), resultado["pastas_criadas"])

    def test_modo_extensao_usa_o_sufixo(self):
        (self.base / "a.pdf").write_bytes(b"x")
        (self.base / "b.JPG").write_bytes(b"x")
        (self.base / "LEIAME").write_text("x", encoding="utf-8")
        resultado = arquivos.organizar(self.base, "extensao")
        self.assertEqual(resultado["total"], 3)
        self.assertTrue((self.base / "PDF" / "a.pdf").is_file())
        self.assertTrue((self.base / "JPG" / "b.JPG").is_file())
        self.assertTrue((self.base / "SEM-EXTENSAO" / "LEIAME").is_file())

    def test_modo_desconhecido_e_recusado(self):
        with self.assertRaises(ValueError):
            arquivos.plano_organizacao(self.base, "por-cor")

    def test_subpastas_inclui_arquivos_dentro_das_pastas(self):
        dentro = self.base / "antiga"
        dentro.mkdir()
        (dentro / "nota.txt").write_text("n", encoding="utf-8")
        (self.base / "foto.jpg").write_bytes(b"x")

        plano = arquivos.plano_organizacao(self.base, "tipo", subpastas=True)
        self.assertEqual(len(plano["Documentos"]), 1)
        resultado = arquivos.organizar(self.base, "tipo", subpastas=True)
        self.assertEqual(resultado["total"], 2)
        self.assertTrue((self.base / "Documentos" / "nota.txt").is_file())
        self.assertTrue((self.base / "Imagens" / "foto.jpg").is_file())

    def test_subpastas_nao_duplica_o_que_ja_esta_no_destino(self):
        documentos = self.base / "Documentos"
        documentos.mkdir()
        (documentos / "nota.txt").write_text("n", encoding="utf-8")

        plano = arquivos.plano_organizacao(self.base, "tipo", subpastas=True)
        self.assertEqual(plano, {})
        resultado = arquivos.organizar(self.base, "tipo", subpastas=True)
        self.assertEqual(resultado["total"], 0)
        self.assertFalse((documentos / "nota (2).txt").exists())

    def test_subpastas_nao_duplica_pasta_de_data_existente(self):
        mes = self.base / "2023" / "05"
        mes.mkdir(parents=True)
        nota = mes / "nota.txt"
        nota.write_text("n", encoding="utf-8")
        os.utime(nota, (datetime(2023, 5, 10, 12).timestamp(),) * 2)

        plano = arquivos.plano_organizacao(self.base, "data", subpastas=True)
        self.assertEqual(plano, {})
        self.assertTrue((mes / "nota.txt").is_file())
        self.assertFalse((mes / "nota (2).txt").exists())

    def test_ignora_lixo_de_sistema_e_arquivos_ocultos(self):
        for nome in (".oculto", "~$contrato.docx", "rascunho.tmp", "desktop.ini"):
            (self.base / nome).write_text("x", encoding="utf-8")
        (self.base / "nota.txt").write_text("n", encoding="utf-8")

        resultado = arquivos.organizar(self.base)
        self.assertEqual(resultado["total"], 1)
        self.assertTrue((self.base / "Documentos" / "nota.txt").is_file())
        for nome in (".oculto", "~$contrato.docx", "rascunho.tmp", "desktop.ini"):
            self.assertTrue((self.base / nome).is_file(), nome)

    def test_codigo_tem_categoria_propria(self):
        self.assertEqual(arquivos.categoria(".py"), "Código")
        self.assertEqual(arquivos.categoria(".json"), "Código")
        self.assertEqual(arquivos.categoria(".desconhecido"), "Outros")


if __name__ == "__main__":
    unittest.main()
