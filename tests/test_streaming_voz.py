import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FalarPartesTests(unittest.TestCase):
    """Streaming de voz: a 1ª frase deve tocar antes de a última existir."""

    def test_primeira_frase_toca_antes_da_ultima_ser_gerada(self):
        import voz

        tocadas = []
        liberar = threading.Event()

        def partes():
            yield "Primeira frase pronta."
            liberar.wait(2.0)          # a "IA" ainda está gerando
            yield "Segunda frase."

        def sintetizar(_texto, arquivo):
            Path(arquivo).write_bytes(b"mp3")
            return None

        def tocar(arquivo):
            tocadas.append(Path(arquivo).name)
            if len(tocadas) == 1:
                liberar.set()          # depois de tocar a 1ª, o gerador pode soltar a 2ª

        async def sintetizar_async(texto, arquivo, *_args):
            sintetizar(texto, arquivo)

        with patch.object(voz, "_sintetizar", sintetizar_async), \
             patch.object(voz, "_tocar", tocar), \
             patch.object(voz, "_falar_offline", lambda *_a, **_k: None), \
             patch.object(voz.time, "sleep", lambda *_a: None), patch.object(voz, "glob"):
            completo = voz.falar_partes(partes(), eco=0)

        self.assertEqual(len(tocadas), 2)
        self.assertIn("Primeira frase pronta.", completo)
        self.assertIn("Segunda frase.", completo)

    def test_parada_interrompe_o_resto(self):
        import voz

        tocadas = []
        async def sintetizar_async(_t, arquivo, *_args):
            Path(arquivo).write_bytes(b"mp3")
        def tocar(_arquivo):
            tocadas.append(1)
            voz._parar.set()

        def partes():
            yield "Um."
            yield "Dois."
            yield "Três."

        with patch.object(voz, "_sintetizar", sintetizar_async), \
             patch.object(voz, "_tocar", tocar), \
             patch.object(voz, "glob"), patch.object(voz.time, "sleep", lambda *_a: None):
            voz.falar_partes(partes(), eco=0)
        voz._parar.clear()
        self.assertEqual(len(tocadas), 1)


class StreamDeFrasesTests(unittest.TestCase):
    """cerebro._stream_frases entrega frases completas, sem depender do provedor real."""

    def _fluxo(self, pedacos):
        def criar(**_kwargs):
            return iter([
                types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=p))])
                for p in pedacos
            ])
        cliente = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=criar)))
        return cliente

    def test_entrega_apenas_frases_fechadas(self):
        import cerebro
        pedacos = ["Olá, senhor. ", "Tudo ", "certo por aqui! ", "Fim"]
        with patch.object(cerebro, "_cliente", lambda _p: self._fluxo(pedacos)), \
             patch.object(cerebro.config, "PROVEDORES", ["gemini"]), \
             patch.object(cerebro.config, "CHAVES", {"gemini": "x"}):
            frases = list(cerebro._stream_frases([{"role": "user", "content": "oi"}], "gemini"))
        self.assertEqual(frases[0], "Olá, senhor.")
        self.assertEqual(frases[1], "Tudo certo por aqui!")
        self.assertEqual(frases[-1], "Fim")

    def test_falha_do_stream_cai_no_modo_normal(self):
        import cerebro

        def explode(**_kwargs):
            raise RuntimeError("sem streaming")

        cliente = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=explode)))
        with patch.object(cerebro, "_cliente", lambda _p: cliente), \
             patch.object(cerebro.config, "PROVEDORES", ["gemini"]), \
             patch.object(cerebro.config, "CHAVES", {"gemini": "x"}), \
             patch.object(cerebro, "_loop", return_value="resposta normal") as loop, \
             patch.object(cerebro.memoria, "salvar_msg"), \
             patch.object(cerebro, "_system", lambda: "sys"), \
             patch.object(cerebro.memoria, "historico", lambda _n: []):
            partes, finalizar = cerebro.processar_stream("oi", None, "teste")
            self.assertEqual(list(partes), [])
            self.assertEqual(finalizar(), "resposta normal")
        loop.assert_called_once()


class SegurarParaFalarTests(unittest.TestCase):
    """escutar_manual: grava só com o gatilho ligado e respeita a pausa."""

    def _ouvido(self):
        import voz
        ouvido = voz.Ouvido.__new__(voz.Ouvido)
        ouvido.pausado = threading.Event()
        ouvido.pedido_manual = threading.Event()
        ouvido.ultimo_erro = None
        ouvido.FS = 16000
        return ouvido

    def test_pausado_nunca_grava(self):
        ouvido = self._ouvido()
        ouvido.pausado.set()
        ouvido.pedido_manual.set()
        chamou = []
        ouvido._gravar = lambda *a, **k: chamou.append(1)
        self.assertIsNone(ouvido.escutar_manual())
        self.assertEqual(chamou, [])

    def test_grava_apenas_com_gatilho_e_usa_reconhecimento_normal(self):
        import voz
        ouvido = self._ouvido()
        vistos = {}

        def gravar(espera, max_seg=15, silencio=None, min_voz=3, fator=1.0, gatilho=None):
            vistos["gatilho"] = gatilho
            return b"\x00\x00" * 1600

        ouvido._gravar = gravar
        fake_sr = types.SimpleNamespace(
            AudioData=lambda pcm, fs, w: ("audio", pcm, fs, w),
        )

        class Rec:
            def recognize_google(self, _audio, language="pt-BR"):
                return "ligar as luzes"

        ouvido.rec = Rec()
        # sem o motor remoto: o teste quer exercitar o reconhecimento "normal"
        with patch.object(voz, "sr", fake_sr), patch.object(voz, "seguranca"), \
                patch.object(voz, "transcricao", None):
            texto = ouvido.escutar_manual()
        self.assertEqual(texto, "ligar as luzes")
        self.assertIs(vistos["gatilho"], ouvido.pedido_manual)


if __name__ == "__main__":
    unittest.main()
