"""Testes de integração de config, barge-in completo e continuidade no Ouvido/Runtime."""
import importlib
import os
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ConfigDefaultsTests(unittest.TestCase):
    def test_defaults_silencio_e_janela_continuidade(self):
        import config

        with patch.dict(os.environ, {}, clear=False), \
             patch("dotenv.load_dotenv", lambda *_a, **_k: False):
            os.environ.pop("SILENCIO_FIM", None)
            os.environ.pop("JANELA_SEGUIMENTO", None)
            os.environ.pop("AFE_ATIVO", None)
            importlib.reload(config)
            self.assertAlmostEqual(config.SILENCIO_FIM, 1.3)
            self.assertAlmostEqual(config.JANELA_SEGUIMENTO, 15.0)
            self.assertTrue(config.AFE_ATIVO)


class BargeInEContinuidadeTests(unittest.TestCase):
    def test_parar_fala_marca_interrupcao_e_aciona_ganchos(self):
        import voz

        chamados = []
        gancho = lambda: chamados.append("flush")
        voz.registrar_gancho_parada(gancho)
        try:
            async def sintetizar_async(_t, arquivo, *_args):
                Path(arquivo).write_bytes(b"mp3")

            def tocar(_arquivo):
                voz.parar_fala()

            def partes():
                yield "Primeira frase."
                yield "Segunda frase que não deve tocar."

            with patch.object(voz, "_sintetizar", sintetizar_async), \
                 patch.object(voz, "_tocar", tocar), \
                 patch.object(voz, "glob"), \
                 patch.object(voz.time, "sleep", lambda *_a: None):
                voz.falar_partes(partes(), eco=0.5)

            self.assertTrue(voz.foi_interrompido())
            self.assertIn("flush", chamados)
        finally:
            voz.remover_gancho_parada(gancho)
            voz._parar.clear()
            voz._interrompido.clear()

    def test_ouvido_com_afe_nao_recalibra_limiar_neural_e_repassa_comando_direto(self):
        import voz

        class _FakeAfe:
            def __init__(self):
                self.modo_neural_ativo = True
                self.aec_ativo = True
                self.capturando = threading.Event()
                self.capturando.set()
                self.nivel_atual = 120.0
                self.ultimo_erro = None

            def aguardar_enunciado(self, **_kwargs):
                return {
                    "pcm": (b"\x10\x00" * 1600),
                    "wake_detectado": True,
                    "comando_direto": True,
                    "erro": None,
                }

            def set_device(self, _idx):
                pass

        ou = voz.Ouvido.__new__(voz.Ouvido)
        ou.limiar = 400.0
        ou.capturando = threading.Event()
        ou.pausado = None
        ou.device_index = None
        ou.device_id = None
        ou.device_generation = 0
        ou.ultimo_erro = None
        ou.ultimo_stt = None
        ou.nivel_atual = 0.0
        ou.nativo_tentado = True
        ou.nativo_ok = False
        ou.rec = types.SimpleNamespace()
        ou._ultimo_comando_ok = 0.0
        ou._nao_entendi_consecutivos = 5
        ou.afe = _FakeAfe()

        self.assertFalse(ou.recalibrar_se_necessario())

        with patch.object(ou, "_tentar_remoto", return_value={"texto": "Ei, Ultron que horas são", "alternativas": ["Ei, Ultron que horas são"], "confianca": {"nivel": "alta"}}):
            detalhe = ou.escutar_detalhado(espera=1.0, exigir_wake=True)
        self.assertEqual(detalhe["texto"], "Ei, Ultron que horas são")
        self.assertTrue(detalhe["wake_detectado"])
        self.assertTrue(detalhe["comando_direto"])

    def test_desktop_runtime_limpa_speech_queue_no_barge_in(self):
        import voz
        from desktop_runtime import DesktopRuntime

        rt = DesktopRuntime(start_voice=False)
        rt._speech_queue.put(("notificacao", "aviso pendente"))
        rt._registrar_barge_in_voz(voz)
        try:
            voz.parar_fala()
            self.assertTrue(rt._speech_queue.empty())
        finally:
            rt._remover_barge_in_voz(voz)
            voz._parar.clear()
            voz._interrompido.clear()


if __name__ == "__main__":
    unittest.main()
