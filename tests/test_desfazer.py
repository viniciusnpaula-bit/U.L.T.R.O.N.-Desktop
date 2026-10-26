import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import desfazer


class DesfazerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.diario = self.dir / "diario.json"
        for alvo, valor in (("DIARIO_DIR", self.dir), ("DIARIO", self.diario)):
            patcher = patch.object(desfazer, alvo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.base = Path.home() / "Documents" / "ultron-test-desfazer"
        shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.base, ignore_errors=True))

    def arquivo(self, nome, texto="conteudo"):
        p = self.base / nome
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8")
        return p

    def test_criar_e_desfazer_apaga_o_arquivo_e_as_pastas_criadas(self):
        alvo = self.base / "nova" / "sub" / "a.txt"
        alvo.parent.mkdir(parents=True)
        alvo.write_text("a", encoding="utf-8")
        pastas = [str(alvo.parent), str(alvo.parent.parent)]
        desfazer.registrar("arquivo.criar", "criar a.txt",
                           desfazer.inversa_remover(alvo, pastas_criadas=pastas))
        resultado = desfazer.desfazer()
        self.assertTrue(resultado["ok"], resultado)
        self.assertFalse(alvo.exists())
        self.assertFalse((self.base / "nova").exists())

    def test_desfazer_recusa_arquivo_alterado(self):
        alvo = self.arquivo("mudou.txt", "original")
        desfazer.registrar("arquivo.criar", "criar mudou.txt", desfazer.inversa_remover(alvo))
        alvo.write_text("editado pelo usuário", encoding="utf-8")
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("mudou", resultado["mensagem"])
        self.assertEqual(alvo.read_text(encoding="utf-8"), "editado pelo usuário")

    def test_pasta_criada_so_e_apagada_se_continuar_vazia(self):
        pasta = self.base / "vazia"
        pasta.mkdir()
        desfazer.registrar("pasta.criar", "criar vazia", desfazer.inversa_remover_pasta(pasta))
        (pasta / "meu.txt").write_text("meu", encoding="utf-8")
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("não está vazia", resultado["mensagem"])
        self.assertTrue((pasta / "meu.txt").exists())
        (pasta / "meu.txt").unlink()
        resultado = desfazer.desfazer()
        self.assertTrue(resultado["ok"], resultado)
        self.assertFalse(pasta.exists())

    def test_mover_e_desfazer_devolve_ao_lugar_original(self):
        origem = self.arquivo("b.txt", "b")
        destino = self.base / "sub" / "b.txt"
        destino.parent.mkdir()
        inversa = desfazer.inversa_mover([{"de": destino, "para": origem, "de_antes": origem}])
        shutil.move(str(origem), str(destino))
        desfazer.registrar("arquivo.mover", "mover b.txt", inversa)
        resultado = desfazer.desfazer()
        self.assertTrue(resultado["ok"], resultado)
        self.assertTrue(origem.exists())
        self.assertFalse(destino.exists())
        self.assertEqual(origem.read_text(encoding="utf-8"), "b")

    def test_mover_recusa_destino_alterado_e_origem_ocupada(self):
        origem = self.arquivo("c.txt", "c")
        destino = self.base / "c-movido.txt"
        inversa = desfazer.inversa_mover([{"de": destino, "para": origem, "de_antes": origem}])
        shutil.move(str(origem), str(destino))
        desfazer.registrar("arquivo.mover", "mover c.txt", inversa)
        destino.write_text("mexido", encoding="utf-8")
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("mudou", resultado["mensagem"])
        self.assertTrue(destino.exists())

        destino.write_text("c", encoding="utf-8")
        origem.write_text("ocupou o lugar", encoding="utf-8")
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("já existe", resultado["mensagem"])
        self.assertEqual(origem.read_text(encoding="utf-8"), "ocupou o lugar")

    def test_mover_varios_volta_tudo_e_remove_pastas_criadas(self):
        foto = self.arquivo("foto.jpg", "foto")
        nota = self.arquivo("nota.txt", "nota")
        imagens = self.base / "Imagens"
        documentos = self.base / "Documentos"
        imagens.mkdir()
        documentos.mkdir()
        destino_foto = imagens / "foto.jpg"
        destino_nota = documentos / "nota.txt"
        shutil.move(str(foto), str(destino_foto))
        shutil.move(str(nota), str(destino_nota))
        inversa = desfazer.inversa_mover(
            [{"de": destino_foto, "para": foto}, {"de": destino_nota, "para": nota}],
            pastas_criadas=[str(imagens), str(documentos)])
        desfazer.registrar("arquivo.organizar", "organizar", inversa)
        resultado = desfazer.desfazer()
        self.assertTrue(resultado["ok"], resultado)
        self.assertTrue(foto.exists() and nota.exists())
        self.assertFalse(imagens.exists() or documentos.exists())

    def test_restaurar_usa_o_restaurador_e_confere_o_resultado(self):
        alvo = self.arquivo("d.txt", "d")
        inversa = desfazer.inversa_restaurar(alvo)
        alvo.unlink()
        desfazer.registrar("arquivo.apagar", "apagar d.txt", inversa)
        chamados = []

        def falso(caminho, dados):
            chamados.append((caminho, dados))
            caminho.write_text("d", encoding="utf-8")
            return True, ""

        resultado = desfazer.desfazer(restaurador=falso)
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(chamados[0][0], alvo.resolve())
        self.assertTrue(alvo.exists())

    def test_restaurar_recusa_se_o_caminho_ja_estiver_ocupado(self):
        alvo = self.arquivo("e.txt", "e")
        inversa = desfazer.inversa_restaurar(alvo)
        desfazer.registrar("arquivo.apagar", "apagar e.txt", inversa)
        chamados = []
        resultado = desfazer.desfazer(restaurador=lambda c, d: chamados.append(c) or (True, ""))
        self.assertFalse(resultado["ok"])
        self.assertIn("já existe", resultado["mensagem"])
        self.assertEqual(chamados, [])

    def test_restaurar_informa_falha_do_restaurador(self):
        alvo = self.arquivo("f.txt", "f")
        inversa = desfazer.inversa_restaurar(alvo)
        alvo.unlink()
        desfazer.registrar("arquivo.apagar", "apagar f.txt", inversa)
        resultado = desfazer.desfazer(restaurador=lambda c, d: (False, "a Lixeira está vazia"))
        self.assertFalse(resultado["ok"])
        self.assertIn("Lixeira está vazia", resultado["mensagem"])

    def test_arvore_apaga_exatamente_o_que_foi_extraido(self):
        arvore = self.base / "extraido"
        (arvore / "sub").mkdir(parents=True)
        (arvore / "a.txt").write_text("a", encoding="utf-8")
        (arvore / "sub" / "b.txt").write_text("b", encoding="utf-8")
        inversa = desfazer.inversa_arvore(arvore)
        desfazer.registrar("arquivo.descompactar", "extrair", inversa)
        resultado = desfazer.desfazer()
        self.assertTrue(resultado["ok"], resultado)
        self.assertFalse(arvore.exists())

    def test_arvore_recusa_se_algo_mudou_ou_apareceu(self):
        arvore = self.base / "extraido2"
        arvore.mkdir()
        (arvore / "a.txt").write_text("a", encoding="utf-8")
        inversa = desfazer.inversa_arvore(arvore)
        desfazer.registrar("arquivo.descompactar", "extrair 2", inversa)
        (arvore / "novo.txt").write_text("novo", encoding="utf-8")
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("mudou", resultado["mensagem"])
        self.assertTrue((arvore / "novo.txt").exists())
        self.assertTrue((arvore / "a.txt").exists())

    def test_arvore_recusa_arquivo_alterado(self):
        arvore = self.base / "extraido3"
        arvore.mkdir()
        alvo = arvore / "a.txt"
        alvo.write_text("a", encoding="utf-8")
        inversa = desfazer.inversa_arvore(arvore)
        desfazer.registrar("arquivo.descompactar", "extrair 3", inversa)
        alvo.write_text("conteudo maior", encoding="utf-8")
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("mudou", resultado["mensagem"])
        self.assertEqual(alvo.read_text(encoding="utf-8"), "conteudo maior")

    def test_arvore_sem_remover_raiz_preserva_a_pasta(self):
        arvore = self.base / "extraido4"
        arvore.mkdir()
        (arvore / "a.txt").write_text("a", encoding="utf-8")
        desfazer.registrar("arquivo.descompactar", "extrair 4",
                           desfazer.inversa_arvore(arvore, remover_raiz=False))
        resultado = desfazer.desfazer()
        self.assertTrue(resultado["ok"], resultado)
        self.assertTrue(arvore.is_dir())
        self.assertFalse((arvore / "a.txt").exists())

    def test_ttl_descarta_a_entrada(self):
        alvo = self.arquivo("velho.txt")
        desfazer.registrar("arquivo.criar", "criar velho.txt", desfazer.inversa_remover(alvo))
        resultado = desfazer.desfazer(agora=time.time() + desfazer.TTL + 5)
        self.assertFalse(resultado["ok"])
        self.assertIn("Não há nada", resultado["mensagem"])
        self.assertTrue(alvo.exists())

    def test_diario_corrompido_nao_derruba_e_e_refeito(self):
        self.diario.write_text("{isto não é json", encoding="utf-8")
        self.assertIsNone(desfazer.proxima())
        alvo = self.arquivo("depois.txt")
        identificador = desfazer.registrar("arquivo.criar", "criar depois.txt",
                                            desfazer.inversa_remover(alvo))
        self.assertRegex(identificador, r"^[a-f0-9]{32}$")
        dados = json.loads(self.diario.read_text(encoding="utf-8"))
        self.assertEqual(len(dados["entradas"]), 1)
        self.assertIsNotNone(desfazer.proxima())

    def test_diario_ignora_entrada_malformada(self):
        valida = {"id": "a" * 32, "criado": time.time(), "expira": time.time() + 60,
                  "operacao": "x", "resumo": "x", "desfeito": 0,
                  "inversa": {"tipo": "remover", "caminho": "C:/nada"}}
        self.diario.write_text(json.dumps({"versao": 1, "entradas": [
            {"id": "curto", "inversa": {}}, valida]}), encoding="utf-8")
        entrada = desfazer.proxima()
        self.assertIsNotNone(entrada)
        self.assertEqual(entrada["id"], "a" * 32)

    def test_desfazer_repetido_pela_id_informa_que_ja_foi(self):
        alvo = self.arquivo("g.txt")
        identificador = desfazer.registrar("arquivo.criar", "criar g.txt",
                                           desfazer.inversa_remover(alvo))
        self.assertTrue(desfazer.desfazer(identificador)["ok"])
        repetido = desfazer.desfazer(identificador)
        self.assertFalse(repetido["ok"])
        self.assertIn("já foi desfeita", repetido["mensagem"])

    def test_id_invalido_e_recusado(self):
        resultado = desfazer.desfazer("../../etc/passwd")
        self.assertFalse(resultado["ok"])
        self.assertIn("não é válido", resultado["mensagem"])

    def test_desfazer_sem_nada(self):
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("Não há nada", resultado["mensagem"])

    def test_desfazer_volta_uma_operacao_por_vez(self):
        primeiro = self.arquivo("h1.txt")
        segundo = self.arquivo("h2.txt")
        desfazer.registrar("arquivo.criar", "criar h1.txt", desfazer.inversa_remover(primeiro))
        desfazer.registrar("arquivo.criar", "criar h2.txt", desfazer.inversa_remover(segundo))
        self.assertTrue(desfazer.desfazer()["ok"])
        self.assertFalse(segundo.exists())
        self.assertTrue(primeiro.exists())
        self.assertTrue(desfazer.desfazer()["ok"])
        self.assertFalse(primeiro.exists())

    def test_caminho_protegido_nunca_e_tocado(self):
        protegido = Path.home() / "AppData" / "ultron-desfazer-nao-toque.txt"
        desfazer.registrar("arquivo.criar", "criar em AppData",
                           {"tipo": "remover", "caminho": str(protegido)})
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("protegida", resultado["mensagem"])
        self.assertFalse(protegido.exists())

    def test_caminho_fora_da_casa_e_da_allowlist_e_recusado(self):
        fora = Path("D:/ultron-desfazer-nao-toque.txt")
        desfazer.registrar("arquivo.criar", "criar fora",
                           {"tipo": "remover", "caminho": str(fora)})
        resultado = desfazer.desfazer()
        self.assertFalse(resultado["ok"])
        self.assertIn("fora da pasta do usuário", resultado["mensagem"])

    def test_limite_de_entradas_mantem_as_mais_novas(self):
        for numero in range(desfazer.MAX_ENTRADAS + 5):
            desfazer.registrar("arquivo.criar", f"operação {numero}",
                               {"tipo": "remover", "caminho": str(self.base / f"x{numero}.txt")})
        dados = json.loads(self.diario.read_text(encoding="utf-8"))
        self.assertEqual(len(dados["entradas"]), desfazer.MAX_ENTRADAS)
        self.assertEqual(dados["entradas"][-1]["resumo"], f"operação {desfazer.MAX_ENTRADAS + 4}")

    def test_inversa_invalida_nao_cria_entrada(self):
        self.assertEqual(desfazer.registrar("x", "y", {}), "")
        self.assertEqual(desfazer.registrar("x", "y", {"tipo": ""}), "")
        self.assertIsNone(desfazer.proxima())
        self.assertFalse(self.diario.exists())

    def test_escrita_e_atomica(self):
        alvo = self.arquivo("i.txt")
        desfazer.registrar("arquivo.criar", "criar i.txt", desfazer.inversa_remover(alvo))
        self.assertFalse(self.diario.with_suffix(".tmp").exists())
        self.assertTrue(self.diario.is_file())

    def test_resumo_inversa_descreve_o_que_vai_acontecer(self):
        alvo = self.arquivo("j.txt")
        entrada = {"inversa": desfazer.inversa_restaurar(alvo)}
        self.assertIn("restaurar", desfazer.resumo_inversa(entrada))
        entrada = {"inversa": desfazer.inversa_remover(alvo)}
        self.assertIn("apagar", desfazer.resumo_inversa(entrada))
        entrada = {"inversa": desfazer.inversa_mover(
            [{"de": alvo, "para": self.base / "j2.txt"}])}
        self.assertIn("devolver", desfazer.resumo_inversa(entrada))

    def test_listar_mostra_as_recentes(self):
        for nome in ("k1.txt", "k2.txt"):
            alvo = self.arquivo(nome)
            desfazer.registrar("arquivo.criar", f"criar {nome}",
                               desfazer.inversa_remover(alvo))
        recentes = desfazer.listar(1)
        self.assertEqual(len(recentes), 1)
        self.assertEqual(recentes[0]["resumo"], "criar k2.txt")
        self.assertFalse(recentes[0]["desfeito"])


if __name__ == "__main__":
    unittest.main()
