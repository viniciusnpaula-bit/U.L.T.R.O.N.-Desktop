"""Testes da integração do Ouvido com o motor Groq (com fallback em cascata)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import voz


def resultado_remoto(texto="Ei, ULTRON, abrir o Chrome", nivel="alta"):
    return {
        "texto": texto,
        "alternativas": [texto],
        "confianca": {"nivel": nivel, "motivo": ""},
        "motor": "groq",
        "erro": None,
        "motivo": None,
        "latencia": 0.4,
    }


class OuvidoGroqTests(unittest.TestCase):
    def setUp(self):
        self.ouvido = voz.Ouvido.__new__(voz.Ouvido)
        self.ouvido.FS = 16000
        self.ouvido.rec = Mock()
        self.ouvido.ultimo_erro = None
        self.ouvido.ultimo_stt = None
        self.ouvido.pausado = None
        self.ouvido._gravar = lambda *a, **k: b"\x00\x00" * 1600
        self.ouvido._tentar_nativo = lambda pcm: None

    def test_motor_invalido_vira_auto(self):
        with patch.object(config, "VOZ_MOTOR", "inventado", create=True):
            self.assertEqual(self.ouvido._motor_escuta(), "auto")

    def test_detalhado_usa_groq_antes_do_google(self):
        falso = SimpleNamespace(transcrever=Mock(return_value=resultado_remoto()))
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            r = self.ouvido.escutar_detalhado()
        self.assertEqual(r["texto"], "Ei, ULTRON, abrir o Chrome")
        self.assertEqual(r["confianca"]["nivel"], "alta")
        self.ouvido.rec.recognize_google.assert_not_called()

    def test_detalhado_cai_para_google_quando_groq_falha(self):
        falso = SimpleNamespace(transcrever=Mock(return_value={
            "texto": None, "alternativas": [], "confianca": None,
            "motor": "groq", "erro": "http_429", "motivo": None, "latencia": 0.1}))
        self.ouvido.rec.recognize_google.return_value = {
            "alternative": [{"transcript": "abrir o chrome"}]}
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            r = self.ouvido.escutar_detalhado()
        self.assertEqual(r["texto"], "abrir o chrome")
        self.assertIsNone(r["confianca"])
        self.ouvido.rec.recognize_google.assert_called_once()

    def test_motor_google_nao_chama_groq(self):
        falso = SimpleNamespace(transcrever=Mock())
        self.ouvido.rec.recognize_google.return_value = {
            "alternative": [{"transcript": "abrir o chrome"}]}
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "google", create=True):
            r = self.ouvido.escutar_detalhado()
        self.assertEqual(r["texto"], "abrir o chrome")
        falso.transcrever.assert_not_called()

    def test_motor_nativo_usa_windows_primeiro(self):
        falso = SimpleNamespace(transcrever=Mock())
        self.ouvido._tentar_nativo = lambda pcm: "do Windows"
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "nativo", create=True):
            r = self.ouvido.escutar_detalhado()
        self.assertEqual(r["texto"], "do Windows")
        falso.transcrever.assert_not_called()
        self.ouvido.rec.recognize_google.assert_not_called()

    def test_escutar_curto_devolve_lista(self):
        falso = SimpleNamespace(transcrever=Mock(
            return_value=resultado_remoto("sim", "alta")))
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            r = self.ouvido.escutar(curto=True)
        self.assertEqual(r, ["sim"])

    def test_escutar_devolve_texto(self):
        falso = SimpleNamespace(transcrever=Mock(
            return_value=resultado_remoto("que horas são", "alta")))
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            r = self.ouvido.escutar()
        self.assertEqual(r, "que horas são")

    def test_escutar_manual_usa_groq(self):
        self.ouvido.pedido_manual = Mock()
        falso = SimpleNamespace(transcrever=Mock(
            return_value=resultado_remoto("abrir o chrome", "alta")))
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            r = self.ouvido.escutar_manual()
        self.assertEqual(r, "abrir o chrome")
        self.ouvido.rec.recognize_google.assert_not_called()

    def test_sem_modulo_remoto_cai_para_google(self):
        self.ouvido.rec.recognize_google.return_value = {
            "alternative": [{"transcript": "abrir o chrome"}]}
        with patch.object(voz, "transcricao", None), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            r = self.ouvido.escutar_detalhado()
        self.assertEqual(r["texto"], "abrir o chrome")

    def test_silencio_confirmado_pela_groq_nao_chama_google(self):
        falso = SimpleNamespace(transcrever=Mock(return_value={
            "texto": None, "alternativas": [], "confianca": {"nivel": "baixa"},
            "motor": "groq", "erro": None, "motivo": "sem_fala", "latencia": 0.2}))
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            r = self.ouvido.escutar_detalhado()
        self.assertIsNone(r["texto"])
        self.assertIsNone(r["erro"])
        self.ouvido.rec.recognize_google.assert_not_called()

    def test_silencio_confirmado_no_manual_nao_chama_google(self):
        self.ouvido.pedido_manual = Mock()
        falso = SimpleNamespace(transcrever=Mock(return_value={
            "texto": None, "alternativas": [], "confianca": {"nivel": "baixa"},
            "motor": "groq", "erro": None, "motivo": "sem_fala", "latencia": 0.2}))
        with patch.object(voz, "transcricao", falso), \
                patch.object(config, "VOZ_MOTOR", "auto", create=True):
            self.assertIsNone(self.ouvido.escutar_manual())
        self.ouvido.rec.recognize_google.assert_not_called()


if __name__ == "__main__":
    unittest.main()
