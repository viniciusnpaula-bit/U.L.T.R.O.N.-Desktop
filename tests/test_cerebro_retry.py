import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cerebro


class ErroHTTP(Exception):
    """Erro com o mesmo formato que o SDK expõe: status_code + headers."""

    def __init__(self, status, retry_after=None, texto=None):
        super().__init__(texto or f"HTTP {status}")
        self.status_code = status
        self.response = types.SimpleNamespace(
            headers={} if retry_after is None else {"retry-after": str(retry_after)})


class BackoffTests(unittest.TestCase):
    def setUp(self):
        cerebro.esquecer_clientes()

    def _config(self, **valores):
        padroes = {
            "IA_TENTATIVAS": 4,
            "IA_BACKOFF_BASE": 1.0,
            "IA_BACKOFF_TETO": 16.0,
            "IA_BACKOFF_JITTER": 0.0,
            "IA_TEMPO_MAX_PROVEDOR": 45.0,
            "IA_TEMPO_MAX_TOTAL": 60.0,
        }
        padroes.update(valores)
        return patch.multiple(cerebro.config, **padroes)

    def test_429_repete_com_espera_exponencial(self):
        chamadas, esperas = [], []

        def tentar():
            chamadas.append(1)
            if len(chamadas) < 3:
                raise ErroHTTP(429)
            return "ok"

        with self._config(), \
                patch.object(cerebro.time, "sleep", esperas.append), \
                patch.object(cerebro.random, "uniform", return_value=0.0):
            self.assertEqual(cerebro._com_backoff("groq", tentar), "ok")

        self.assertEqual(len(chamadas), 3)
        self.assertEqual(esperas, [1.0, 2.0])

    def test_erro_permanente_nao_repete_nem_dorme(self):
        chamadas = []

        def tentar():
            chamadas.append(1)
            raise ErroHTTP(401)

        with self._config(), patch.object(cerebro.time, "sleep") as dormir:
            with self.assertRaises(ErroHTTP):
                cerebro._com_backoff("groq", tentar)

        self.assertEqual(len(chamadas), 1)
        self.assertEqual(dormir.call_count, 0)

    def test_teto_limita_a_espera(self):
        with self._config():
            self.assertEqual(cerebro._espera(10), 16.0)

    def test_retry_after_tem_prioridade_e_respeita_o_teto(self):
        with self._config():
            self.assertEqual(cerebro._espera(0, retry_after=0.25), 0.25)
            self.assertEqual(cerebro._espera(0, retry_after=99), 16.0)

    def test_jitter_adiciona_ate_o_percentual_configurado(self):
        with self._config(IA_BACKOFF_JITTER=0.5), \
                patch.object(cerebro.random, "uniform", return_value=0.5):
            self.assertEqual(cerebro._espera(0), 1.5)

    def test_orcamento_de_tempo_interrompe_as_tentativas(self):
        chamadas = []

        def tentar():
            chamadas.append(1)
            raise ErroHTTP(429)

        with self._config(IA_TEMPO_MAX_PROVEDOR=1.0), \
                patch.object(cerebro.time, "sleep", lambda _s: None), \
                patch.object(cerebro.time, "monotonic", side_effect=[0.0, 5.0]):
            with self.assertRaises(ErroHTTP):
                cerebro._com_backoff("groq", tentar)

        self.assertEqual(len(chamadas), 1)

    def test_erros_transitorios_reconhecidos(self):
        self.assertTrue(cerebro._transitorio(ErroHTTP(429)))
        self.assertTrue(cerebro._transitorio(ErroHTTP(500)))
        self.assertTrue(cerebro._transitorio(ErroHTTP(503)))
        self.assertTrue(cerebro._transitorio(TimeoutError()))
        self.assertTrue(cerebro._transitorio(ConnectionError()))
        self.assertFalse(cerebro._transitorio(ErroHTTP(401)))
        self.assertFalse(cerebro._transitorio(ErroHTTP(400)))
        self.assertFalse(cerebro._transitorio(ErroHTTP(404)))

    def test_excecoes_reais_do_sdk_sao_transitorias(self):
        import openai

        resposta429 = types.SimpleNamespace(status_code=429, headers={}, request=None)
        resposta500 = types.SimpleNamespace(status_code=500, headers={}, request=None)
        self.assertTrue(cerebro._transitorio(
            openai.RateLimitError("limite", response=resposta429, body=None)))
        self.assertTrue(cerebro._transitorio(openai.APITimeoutError(request=object())))
        self.assertTrue(cerebro._transitorio(openai.APIConnectionError(request=object())))
        self.assertTrue(cerebro._transitorio(
            openai.InternalServerError("erro", response=resposta500, body=None)))

    def test_retry_after_invalido_cai_no_exponencial(self):
        erro = ErroHTTP(429)
        erro.response.headers["retry-after"] = "not-a-number"

        with self._config(), patch.object(cerebro.random, "uniform", return_value=0.0):
            self.assertIsNone(cerebro._retry_after(erro))
            self.assertEqual(cerebro._espera(1, cerebro._retry_after(erro)), 2.0)

    def test_prazo_total_interrompe_antes_do_limite_do_provedor(self):
        chamadas = []

        def tentar():
            chamadas.append(1)
            raise ErroHTTP(429)

        with self._config(IA_TEMPO_MAX_PROVEDOR=45.0), \
                patch.object(cerebro.time, "sleep", lambda _s: None), \
                patch.object(cerebro.time, "monotonic", side_effect=[0.0, 0.5, 0.5]):
            with self.assertRaises(ErroHTTP):
                cerebro._com_backoff("groq", tentar, prazo=1.0)

        self.assertEqual(len(chamadas), 1)

    def test_log_de_retry_nao_vaza_texto_do_erro(self):
        def tentar():
            raise ErroHTTP(500, texto="segredo do usuário")

        with self._config(), \
                patch.object(cerebro.time, "sleep", lambda _s: None), \
                patch.object(cerebro.seguranca.log, "warning") as aviso:
            with self.assertRaises(ErroHTTP):
                cerebro._com_backoff("groq", tentar)

        self.assertTrue(aviso.called)
        self.assertIn("ErroHTTP 500", str(aviso.call_args))
        self.assertNotIn("segredo", str(aviso.call_args))

    def test_parada_de_emergencia_interrompe_o_backoff(self):
        chamadas = []

        def tentar():
            chamadas.append(1)
            raise ErroHTTP(429)

        cerebro.seguranca.parada.set()
        self.addCleanup(cerebro.seguranca.parada.clear)
        with self._config(), patch.object(cerebro.time, "sleep") as dormir:
            with self.assertRaises(ErroHTTP):
                cerebro._com_backoff("groq", tentar)

        self.assertEqual(len(chamadas), 1)
        self.assertEqual(dormir.call_count, 0)

    def test_cliente_desliga_retry_do_sdk(self):
        with patch.object(cerebro, "OpenAI") as construtor:
            cerebro.esquecer_clientes()
            cerebro._cliente("groq")

        self.assertEqual(construtor.call_args.kwargs["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
