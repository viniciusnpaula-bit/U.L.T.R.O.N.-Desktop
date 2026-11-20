"""Testes unitários do AudioFrontEnd contínuo (afe.py) sem hardware físico."""
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeVad:
    def __init__(self, speech_sequence=None):
        self.window_size = 512
        self._seq = list(speech_sequence or [True] * 20)
        self._idx = 0
        self._ativo = False

    def accept_waveform(self, chunk):
        if self._idx < len(self._seq):
            self._ativo = bool(self._seq[self._idx])
            self._idx += 1
        else:
            self._ativo = False

    def is_speech_detected(self):
        return self._ativo

    def reset(self):
        self._idx = 0
        self._ativo = False


class _FakeKwsRecognizer:
    def __init__(self, results):
        self._results = list(results)
        self._idx = 0
        self._last = ""

    def AcceptWaveform(self, _pcm_bytes):
        if self._idx < len(self._results):
            self._last = self._results[self._idx]
            self._idx += 1
        else:
            self._last = ""
        return True

    def Result(self):
        return json.dumps({"text": self._last})

    def PartialResult(self):
        return json.dumps({"partial": self._last})

    def Reset(self):
        self._last = ""


class _FakeDenoiser:
    def __init__(self):
        self.chamadas = 0

    def run(self, samples, sample_rate):
        self.chamadas += 1
        return types.SimpleNamespace(samples=np.asarray(samples, dtype=np.float32))


class AfeTests(unittest.TestCase):
    def test_preparar_modelos_em_ram_nao_abre_microfone_nem_loopback(self):
        import afe

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "silero_vad.onnx").write_bytes(b"vad")
            (base / "gtcrn_simple.onnx").write_bytes(b"gtcrn")
            (base / "vosk-model-small-pt-0.3").mkdir()
            (base / "vosk-model-small-pt-0.3" / "ok").write_bytes(b"1")

            aberturas = []
            inst = afe.AudioFrontEnd(
                modelos_dir=base,
                carregador_modelos=lambda _caminhos: {
                    "vad": _FakeVad(),
                    "denoiser": _FakeDenoiser(),
                    "kws": _FakeKwsRecognizer([]),
                },
                stream_factory=lambda *a, **k: aberturas.append("mic"),
                loopback_factory=lambda *a, **k: aberturas.append("loopback"),
            )
            ok = inst.preparar_modelos_em_ram()
            self.assertTrue(ok)
            self.assertTrue(inst.modo_neural_ativo)
            self.assertEqual(aberturas, [])

    def test_regra_para_so_dispara_enquanto_falando_e_wake_acorda_em_repouso(self):
        import afe

        eventos = []
        falando_ev = threading.Event()
        vad = _FakeVad([True] * 12)
        kws = _FakeKwsRecognizer(["para", "para", "ei ultron"])
        denoiser = _FakeDenoiser()

        inst = afe.AudioFrontEnd(
            falando_event=falando_ev,
            on_barge_in=lambda tipo, pcm: eventos.append((tipo, pcm is not None)),
        )
        inst.injetar_motores(vad=vad, kws=kws, denoiser=denoiser)

        bloco_voz = (0.15 * np.sin(2 * np.pi * 440.0 * np.arange(512) / 16000)).astype(np.float32)

        # 1) falando=False -> "para" deve ser ignorado para barge-in e não acorda
        inst.processar_bloco_sintetico(bloco_voz, None, falando=False)
        self.assertEqual(eventos, [])
        self.assertFalse(inst.tem_enunciado_pronto())

        # 2) falando=True -> "para" dispara barge-in("para")
        falando_ev.set()
        inst.processar_bloco_sintetico(bloco_voz, None, falando=True)
        self.assertEqual(eventos, [("para", False)])

        # 3) falando=True -> "ei ultron" dispara barge-in("wake")
        inst.processar_bloco_sintetico(bloco_voz, None, falando=True)
        self.assertEqual(eventos[-1][0], "wake")

    def test_enunciado_com_wake_e_comando_direto_passa_por_denoiser_e_agc(self):
        import afe

        # 6 blocos de fala + silêncio suficiente para fechar enunciado (silencio_fim=0.15s -> ~5 blocos)
        vad = _FakeVad([True] * 6 + [False] * 8)
        kws = _FakeKwsRecognizer(["", "ei ultron", "ei ultron"])
        denoiser = _FakeDenoiser()

        inst = afe.AudioFrontEnd()
        inst.injetar_motores(vad=vad, kws=kws, denoiser=denoiser)

        t = np.arange(512, dtype=np.float32) / 16000
        voz = (0.04 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        sil = np.zeros(512, dtype=np.float32)

        for _ in range(6):
            inst.processar_bloco_sintetico(voz, None, falando=False)
        for _ in range(8):
            inst.processar_bloco_sintetico(sil, None, falando=False, silencio_fim_override=0.15)

        res = inst.aguardar_enunciado(espera=0.5, silencio_fim=0.15, exigir_wake=True)
        self.assertIsNotNone(res["pcm"])
        self.assertTrue(res["wake_detectado"])
        self.assertTrue(res["comando_direto"])
        self.assertGreaterEqual(denoiser.chamadas, 1)

    def test_hot_swap_promove_de_fallback_para_neural_sem_parar_captura(self):
        import afe

        inst = afe.AudioFrontEnd()
        self.assertFalse(inst.modo_neural_ativo)
        denoiser = _FakeDenoiser()
        inst.injetar_motores(vad=_FakeVad(), kws=_FakeKwsRecognizer([]), denoiser=denoiser)
        self.assertTrue(inst.modo_neural_ativo)

    def test_watchdog_recupera_stream_travado_sem_derrubar_consumidor(self):
        import afe

        aberturas = []

        class _FakeStream:
            def __init__(self, *args, **kwargs):
                aberturas.append(len(aberturas) + 1)
                self._cb = kwargs.get("callback")

            def start(self):
                if len(aberturas) >= 2 and self._cb:
                    t = np.arange(512, dtype=np.float32) / 16000
                    voz = (0.15 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)[:, None]
                    for _ in range(5):
                        self._cb(voz, 512, None, None)

            def stop(self):
                pass

            def close(self):
                pass

        inst = afe.AudioFrontEnd(
            stream_factory=lambda *a, **k: _FakeStream(*a, **k),
            watchdog_timeout_s=0.12,
        )
        inst.iniciar_captura()
        try:
            time.sleep(0.35)
            self.assertGreaterEqual(len(aberturas), 2)
        finally:
            inst.parar_captura()

    def test_parar_captura_aguarda_e_limpa_thread_loopback(self):
        import afe

        loopback_rodando = threading.Event()
        loopback_encerrado = threading.Event()

        def _fake_loopback(self_afe):
            loopback_rodando.set()
            while not self_afe._parar_ev.is_set():
                time.sleep(0.01)
            loopback_encerrado.set()

        class _NoopStream:
            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        inst = afe.AudioFrontEnd(stream_factory=lambda *a, **k: _NoopStream())
        inst._loop_wasapi_loopback = types.MethodType(_fake_loopback, inst)
        inst.iniciar_captura()
        self.assertTrue(loopback_rodando.wait(timeout=1.0))
        inst.parar_captura()
        self.assertTrue(loopback_encerrado.is_set())
        self.assertIsNone(inst._thread_loopback)


if __name__ == "__main__":
    unittest.main()
