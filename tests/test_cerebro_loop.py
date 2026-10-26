import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cerebro


class LoopDeFerramentasTests(unittest.TestCase):
    def test_limite_de_passos_permite_seis_rodadas_de_ferramentas(self):
        chamadas = []

        def chamar(_msgs):
            chamadas.append(1)
            return SimpleNamespace(content="", tool_calls=[SimpleNamespace(
                id=f"call_{len(chamadas)}",
                function=SimpleNamespace(name="listar_pasta",
                                        arguments='{"pasta": "C:/Users/exemplo/Videos"}'))])

        with patch.object(cerebro, "_chamar", side_effect=chamar), \
                patch.object(cerebro.ferramentas, "executar", return_value="ok") as executar, \
                patch.object(cerebro, "_rastrear"):
            resposta = cerebro._loop([], lambda *args: True, "teste")

        self.assertEqual(len(chamadas), cerebro.MAX_PASSOS_FERRAMENTA)
        self.assertEqual(len(chamadas), 6)
        self.assertEqual(executar.call_count, 6)
        self.assertIn("limite de passos", resposta)

    def test_resposta_final_encerra_o_laco_antes_do_limite(self):
        chamadas = []

        def chamar(_msgs):
            chamadas.append(1)
            if len(chamadas) == 1:
                return SimpleNamespace(content="", tool_calls=[SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(name="listar_pasta", arguments='{"pasta": "C:/x"}'))])
            return SimpleNamespace(content="Pronto.", tool_calls=[])

        with patch.object(cerebro, "_chamar", side_effect=chamar), \
                patch.object(cerebro.ferramentas, "executar", return_value="ok"), \
                patch.object(cerebro, "_rastrear"):
            resposta = cerebro._loop([], lambda *args: True, "teste")

        self.assertEqual(len(chamadas), 2)
        self.assertEqual(resposta, "Pronto.")


if __name__ == "__main__":
    unittest.main()
