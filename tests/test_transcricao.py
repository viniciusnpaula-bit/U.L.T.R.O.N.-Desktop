"""Testes da transcrição remota (Groq Whisper) — grátis, com confiança e fallback."""
import io
import json
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import transcricao


class RespostaFalsa:
    def __init__(self, status=200, corpo=None, headers=None):
        self.status_code = status
        self._corpo = corpo if corpo is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._corpo)

    def json(self):
        return self._corpo


def corpo_ok(texto="Ei, ULTRON, abrir o Chrome!", avg=-0.291,
             sem_fala=0.001, compressao=0.778):
    return {
        "text": texto,
        "duration": 2.64,
        "segments": [{
            "avg_logprob": avg,
            "no_speech_prob": sem_fala,
            "compression_ratio": compressao,
        }],
    }


class WavTests(unittest.TestCase):
    def test_wav_e_16k_mono_16_bits(self):
        dados = transcricao.wav(b"\x00\x00" * 1600, 16000)
        with wave.open(io.BytesIO(dados), "rb") as arquivo:
            self.assertEqual(arquivo.getnchannels(), 1)
            self.assertEqual(arquivo.getsampwidth(), 2)
            self.assertEqual(arquivo.getframerate(), 16000)
            self.assertEqual(arquivo.getnframes(), 1600)
        self.assertTrue(dados.startswith(b"RIFF"))


class PromptTests(unittest.TestCase):
    def test_prompt_tem_despertar_comandos_e_limite(self):
        prompt = transcricao.montar_prompt()
        self.assertIn("Ei, ULTRON", prompt)
        self.assertIn("Chrome", prompt)
        self.assertLessEqual(len(prompt), 900)


class ConfiancaTests(unittest.TestCase):
    def test_logprob_bom_e_alta(self):
        r = transcricao.nivel_confianca([{
            "avg_logprob": -0.113, "no_speech_prob": 0.0,
            "compression_ratio": 0.873}])
        self.assertEqual(r["nivel"], "alta")

    def test_logprob_no_limite_e_media(self):
        r = transcricao.nivel_confianca([{
            "avg_logprob": -0.358, "no_speech_prob": 0.0,
            "compression_ratio": 0.771}])
        self.assertEqual(r["nivel"], "media")

    def test_logprob_ruim_e_baixa(self):
        r = transcricao.nivel_confianca([{
            "avg_logprob": -0.8, "no_speech_prob": 0.0,
            "compression_ratio": 0.8}])
        self.assertEqual(r["nivel"], "baixa")

    def test_sem_fala_provavel_e_baixa(self):
        r = transcricao.nivel_confianca([{
            "avg_logprob": -0.2, "no_speech_prob": 0.9,
            "compression_ratio": 0.8}])
        self.assertEqual(r["nivel"], "baixa")
        self.assertIn("fala", r["motivo"])

    def test_compressao_extrema_e_baixa(self):
        r = transcricao.nivel_confianca([{
            "avg_logprob": -0.2, "no_speech_prob": 0.0,
            "compression_ratio": 3.0}])
        self.assertEqual(r["nivel"], "baixa")

    def test_sem_segmentos_nao_inventa_confianca(self):
        r = transcricao.nivel_confianca([])
        self.assertEqual(r["nivel"], "alta")
        self.assertIsNone(r["avg_logprob"])


class TranscreverTests(unittest.TestCase):
    def setUp(self):
        transcricao.reiniciar_disjuntor()
        self.pcm = b"\x00\x00" * 1600

    def test_sem_chave_nao_chama_api(self):
        with patch.dict(config.CHAVES, {"groq": ""}), \
                patch.object(transcricao.requests, "post") as post:
            r = transcricao.transcrever(self.pcm)
        self.assertIsNone(r["texto"])
        self.assertEqual(r["erro"], "sem_chave")
        post.assert_not_called()

    def test_devolve_texto_confianca_e_wav(self):
        with patch.dict(config.CHAVES, {"groq": "gsk_teste"}), \
                patch.object(transcricao.requests, "post",
                             return_value=RespostaFalsa(corpo=corpo_ok())) as post:
            r = transcricao.transcrever(self.pcm, 16000)
        self.assertEqual(r["texto"], "Ei, ULTRON, abrir o Chrome!")
        self.assertEqual(r["motor"], "groq")
        self.assertEqual(r["confianca"]["nivel"], "alta")
        self.assertEqual(r["alternativas"], ["Ei, ULTRON, abrir o Chrome!"])
        self.assertGreaterEqual(r["latencia"], 0)
        envio = post.call_args
        self.assertEqual(envio.kwargs["data"]["model"], "whisper-large-v3")
        self.assertEqual(envio.kwargs["data"]["language"], "pt")
        self.assertEqual(envio.kwargs["data"]["response_format"], "verbose_json")
        self.assertEqual(envio.kwargs["data"]["temperature"], "0")
        self.assertEqual(envio.kwargs["files"]["file"][0], "fala.wav")
        self.assertEqual(envio.kwargs["files"]["file"][2], "audio/wav")
        self.assertTrue(envio.kwargs["files"]["file"][1].startswith(b"RIFF"))

    def test_429_tenta_de_novo_uma_vez(self):
        respostas = [
            RespostaFalsa(status=429, corpo={"error": "rate_limit"},
                          headers={"retry-after": "0"}),
            RespostaFalsa(corpo=corpo_ok()),
        ]
        with patch.dict(config.CHAVES, {"groq": "gsk_teste"}), \
                patch.object(transcricao.requests, "post",
                             side_effect=respostas) as post, \
                patch.object(transcricao.time, "sleep"):
            r = transcricao.transcrever(self.pcm)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(r["texto"], "Ei, ULTRON, abrir o Chrome!")

    def test_401_nao_retenta(self):
        with patch.dict(config.CHAVES, {"groq": "gsk_teste"}), \
                patch.object(transcricao.requests, "post",
                             return_value=RespostaFalsa(status=401,
                                                        corpo={"error": "bad_key"})) as post:
            r = transcricao.transcrever(self.pcm)
        self.assertEqual(post.call_count, 1)
        self.assertIsNone(r["texto"])
        self.assertIn("401", r["erro"])

    def test_disjuntor_abre_apos_duas_falhas(self):
        with patch.dict(config.CHAVES, {"groq": "gsk_teste"}), \
                patch.object(transcricao.requests, "post",
                             return_value=RespostaFalsa(status=401,
                                                        corpo={"error": "bad_key"})) as post:
            transcricao.transcrever(self.pcm)
            transcricao.transcrever(self.pcm)
            r = transcricao.transcrever(self.pcm)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(r["erro"], "disjuntor")

    def test_texto_vazio_vira_sem_fala(self):
        with patch.dict(config.CHAVES, {"groq": "gsk_teste"}), \
                patch.object(transcricao.requests, "post",
                             return_value=RespostaFalsa(corpo=corpo_ok(texto=""))):
            r = transcricao.transcrever(self.pcm)
        self.assertIsNone(r["texto"])
        self.assertEqual(r["motivo"], "sem_fala")

    def test_no_speech_alto_descarta_texto(self):
        with patch.dict(config.CHAVES, {"groq": "gsk_teste"}), \
                patch.object(transcricao.requests, "post",
                             return_value=RespostaFalsa(
                                 corpo=corpo_ok(texto="texto inventado", sem_fala=0.95))):
            r = transcricao.transcrever(self.pcm)
        self.assertIsNone(r["texto"])
        self.assertEqual(r["motivo"], "sem_fala")


if __name__ == "__main__":
    unittest.main()
