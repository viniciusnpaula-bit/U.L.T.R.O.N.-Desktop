import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fluxos


class FluxosTests(unittest.TestCase):
    def test_modo_jogo_tem_as_tres_etapas_na_ordem(self):
        fluxo = fluxos.obter("modo_jogo")
        self.assertEqual([p.rotulo for p in fluxo.passos],
                         ["abrir o Rocket League", "abrir o Spotify", "minimizar as janelas"])

    def test_fluxo_completo_quando_todas_as_etapas_passam(self):
        chamadas = []
        def executar(nome, args, confirmar, origem):
            chamadas.append(nome)
            return "ok"
        r = fluxos.executar("modo_jogo", executar)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["etapas"]), 3)
        self.assertEqual(chamadas, ["abrir_programa", "abrir_programa", "minimizar_janelas"])

    def test_para_na_primeira_falha_e_nomeia_a_etapa(self):
        chamadas = []
        def executar(nome, args, confirmar, origem):
            chamadas.append(args.get("nome") or nome)
            if args.get("nome") == "Spotify":
                return "Erro ao executar: não encontrei"
            return "Abrindo."
        r = fluxos.executar("modo_jogo", executar)
        self.assertFalse(r["ok"])
        self.assertEqual(r["falhou_em"], "abrir o Spotify")
        self.assertIn("Spotify", r["resumo"])
        # a terceira etapa NÃO pode ter sido executada
        self.assertNotIn("minimizar_janelas", chamadas)
        self.assertEqual(len(chamadas), 2)

    def test_negacao_da_seguranca_interrompe_o_fluxo(self):
        def executar(nome, args, confirmar, origem):
            return "AÇÃO NEGADA: sem permissão."
        r = fluxos.executar("modo_jogo", executar)
        self.assertFalse(r["ok"])
        self.assertIn("negada", r["resumo"])
        self.assertEqual(len(r["etapas"]), 1)

    def test_fluxo_desconhecido_nao_executa_nada(self):
        chamadas = []
        r = fluxos.executar("nao_existe", lambda *a: chamadas.append(1))
        self.assertFalse(r["ok"])
        self.assertEqual(chamadas, [])

    def test_roteiro_de_abertura_so_abre_o_jogo(self):
        chamadas = []
        fluxos.executar("abrir.rocket", lambda n, a, c, o: chamadas.append(a.get("nome")))
        self.assertEqual(chamadas, ["Rocket League"])


if __name__ == "__main__":
    unittest.main()
