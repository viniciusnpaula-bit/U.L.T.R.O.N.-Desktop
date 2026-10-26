import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import voz_nativa


class MotorNativoTests(unittest.TestCase):
    """O motor do Windows é opcional: sem ele, tudo devolve None sem erro."""

    def setUp(self):
        voz_nativa._CULTURAS = None
        self.addCleanup(setattr, voz_nativa, "_CULTURAS", None)

    def _arquivo(self):
        arquivo = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        arquivo.close()
        return Path(arquivo.name)

    def test_lista_culturas_instaladas(self):
        saida = SimpleNamespace(returncode=0, stdout="pt-BR\nen-US\n")
        with patch.object(voz_nativa, "_executar", return_value=saida) as executar:
            self.assertEqual(voz_nativa.culturas(), ["pt-BR", "en-US"])
            self.assertEqual(voz_nativa.culturas(), ["pt-BR", "en-US"])
        executar.assert_called_once()

    def test_maquina_sem_reconhecedor_devolve_lista_vazia(self):
        saida = SimpleNamespace(returncode=0, stdout="")
        with patch.object(voz_nativa, "_executar", return_value=saida):
            self.assertEqual(voz_nativa.culturas(), [])

    def test_falha_do_powershell_nao_quebra(self):
        with patch.object(voz_nativa, "_executar", side_effect=OSError("sem powershell")):
            self.assertEqual(voz_nativa.culturas(), [])

    def test_disponivel_para_portugues(self):
        voz_nativa._CULTURAS = ("pt-BR",)
        self.assertTrue(voz_nativa.disponivel("pt-BR"))
        self.assertTrue(voz_nativa.disponivel("pt"))
        self.assertFalse(voz_nativa.disponivel("en-US"))

    def test_instalado_apenas_em_ingles_nao_serve(self):
        voz_nativa._CULTURAS = ("en-US",)
        self.assertFalse(voz_nativa.disponivel("pt-BR"))

    def test_reconhecer_sem_audio_nao_chama_o_motor(self):
        with patch.object(voz_nativa, "_executar") as executar:
            self.assertIsNone(voz_nativa.reconhecer(b""))
        executar.assert_not_called()

    def test_reconhecer_devolve_texto_e_apaga_o_wav(self):
        criados = []

        def wav(pcm, taxa):
            caminho = self._arquivo()
            caminho.write_bytes(b"RIFF")
            criados.append(caminho)
            return caminho

        saida = SimpleNamespace(returncode=0, stdout="  ligar as luzes  \n")
        with patch.object(voz_nativa, "_wav", side_effect=wav), \
                patch.object(voz_nativa, "_executar", return_value=saida):
            texto = voz_nativa.reconhecer(b"\x00\x00" * 160)

        self.assertEqual(texto, "ligar as luzes")
        self.assertEqual(len(criados), 1)
        self.assertFalse(criados[0].exists())

    def test_reconhecer_sem_fala_devolve_none(self):
        saida = SimpleNamespace(returncode=0, stdout="\n")
        with patch.object(voz_nativa, "_wav", return_value=self._arquivo()), \
                patch.object(voz_nativa, "_executar", return_value=saida):
            self.assertIsNone(voz_nativa.reconhecer(b"\x00\x00" * 160))

    def test_erro_do_motor_devolve_none(self):
        saida = SimpleNamespace(returncode=1, stdout="", stderr="sem motor")
        with patch.object(voz_nativa, "_wav", return_value=self._arquivo()), \
                patch.object(voz_nativa, "_executar", return_value=saida):
            self.assertIsNone(voz_nativa.reconhecer(b"\x00\x00" * 160))

    def test_timeout_devolve_none(self):
        import subprocess
        with patch.object(voz_nativa, "_wav", return_value=self._arquivo()), \
                patch.object(voz_nativa, "_executar", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertIsNone(voz_nativa.reconhecer(b"\x00\x00" * 160))

    def test_wav_gerado_e_pcm_16_bits_mono(self):
        caminho = voz_nativa._wav(b"\x00\x00" * 160, 16000)
        self.addCleanup(caminho.unlink)
        with wave.open(str(caminho), "rb") as arquivo:
            self.assertEqual(arquivo.getnchannels(), 1)
            self.assertEqual(arquivo.getsampwidth(), 2)
            self.assertEqual(arquivo.getframerate(), 16000)
            self.assertEqual(arquivo.getnframes(), 160)


class FallbackDoOuvidoTests(unittest.TestCase):
    """voz.py usa o nativo só quando configurado ou quando o Google falha."""

    def _ouvido(self):
        import voz
        ouvido = voz.Ouvido.__new__(voz.Ouvido)
        ouvido.pausado = threading.Event()
        ouvido.pedido_manual = threading.Event()
        ouvido.pedido_manual.set()
        ouvido.ultimo_erro = None
        ouvido.FS = 16000
        ouvido._gravar = lambda *a, **k: b"\x00\x00" * 160
        return ouvido

    def test_modo_nunca_desliga_o_nativo(self):
        import voz
        ouvido = self._ouvido()
        with patch.object(voz.config, "VOZ_NATIVA", "nunca"), \
                patch.object(voz, "voz_nativa", SimpleNamespace(disponivel=lambda: True)) as nativo:
            self.assertFalse(ouvido._nativo_disponivel())
        self.assertFalse(ouvido._preferir_nativo())

    def test_modo_sempre_prefere_o_nativo_e_nao_chama_google(self):
        import voz
        ouvido = self._ouvido()
        ouvido._tentar_nativo = lambda pcm: "ligar as luzes"
        chamou = []
        ouvido.rec = SimpleNamespace(recognize_google=lambda *a, **k: chamou.append(1))
        with patch.object(voz.config, "VOZ_NATIVA", "sempre"), patch.object(voz, "seguranca"):
            self.assertEqual(ouvido.escutar_manual(), "ligar as luzes")
        self.assertEqual(chamou, [])

    def test_modo_auto_usa_google_quando_ele_responde(self):
        import voz
        ouvido = self._ouvido()
        ouvido._tentar_nativo = lambda pcm: "nativo"
        ouvido.rec = SimpleNamespace(recognize_google=lambda *a, **k: "google")
        fake_sr = SimpleNamespace(AudioData=lambda pcm, fs, w: ("audio", pcm, fs, w))
        with patch.object(voz.config, "VOZ_NATIVA", "auto"), \
                patch.object(voz, "sr", fake_sr), patch.object(voz, "seguranca"):
            self.assertEqual(ouvido.escutar_manual(), "google")

    def test_falha_do_google_cai_no_nativo(self):
        import voz
        ouvido = self._ouvido()

        def falhar(*_a, **_k):
            raise RuntimeError("sem internet")

        ouvido.rec = SimpleNamespace(recognize_google=falhar)
        ouvido._tentar_nativo = lambda pcm: "texto nativo"
        fake_sr = SimpleNamespace(AudioData=lambda pcm, fs, w: ("audio", pcm, fs, w))
        with patch.object(voz.config, "VOZ_NATIVA", "auto"), \
                patch.object(voz, "sr", fake_sr), patch.object(voz, "seguranca"):
            self.assertEqual(ouvido.escutar_manual(), "texto nativo")

    def test_sem_nativo_a_falha_do_google_mantem_o_erro(self):
        import voz
        ouvido = self._ouvido()

        def falhar(*_a, **_k):
            raise RuntimeError("sem internet")

        ouvido.rec = SimpleNamespace(recognize_google=falhar)
        ouvido._tentar_nativo = lambda pcm: None
        fake_sr = SimpleNamespace(AudioData=lambda pcm, fs, w: ("audio", pcm, fs, w))
        with patch.object(voz.config, "VOZ_NATIVA", "auto"), \
                patch.object(voz, "sr", fake_sr), patch.object(voz, "seguranca"):
            self.assertIsNone(ouvido.escutar_manual())
        self.assertIn("sem internet", ouvido.ultimo_erro)

    def test_detalhado_usa_nativo_quando_nao_ha_internet(self):
        import voz
        ouvido = self._ouvido()

        class SemInternet(Exception):
            pass

        def falhar(*_a, **_k):
            raise SemInternet("offline")

        ouvido.rec = SimpleNamespace(recognize_google=falhar)
        ouvido._tentar_nativo = lambda pcm: "abrir a pasta"
        fake_sr = SimpleNamespace(AudioData=lambda pcm, fs, w: ("audio", pcm, fs, w),
                                  UnknownValueError=ValueError, RequestError=SemInternet)
        with patch.object(voz.config, "VOZ_NATIVA", "auto"), \
                patch.object(voz, "sr", fake_sr), patch.object(voz, "seguranca"):
            resultado = ouvido.escutar_detalhado()
        self.assertEqual(resultado, {"texto": "abrir a pasta",
                                     "alternativas": ["abrir a pasta"], "erro": None})


if __name__ == "__main__":
    unittest.main()
