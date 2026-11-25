"""Testes unitários da Fase 1 (Barge-in livre + PCM stream) e Fase 3 (Gemini Live seguro)."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeVad:
    def __init__(self, speech_sequence):
        self._seq = list(speech_sequence)
        self._idx = 0
        self._ativo = False

    def accept_waveform(self, _chunk):
        if self._idx < len(self._seq):
            self._ativo = bool(self._seq[self._idx])
            self._idx += 1
        else:
            self._ativo = False

    def is_speech_detected(self):
        return self._ativo


class _FakeRawOutputStream:
    def __init__(self, **_kwargs):
        self.escritas: list[bytes] = []
        self.abortado = False
        self.fechado = False
        self.iniciado = False

    def start(self):
        self.iniciado = True

    def write(self, chunk: bytes):
        self.escritas.append(bytes(chunk))
        time.sleep(0.005)

    def abort(self):
        self.abortado = True

    def stop(self):
        pass

    def close(self):
        self.fechado = True


class _FakeWebSocket:
    def __init__(self, mensagens_entrada: list[dict], pausa_final: float = 0.12):
        self.enviadas: list[dict] = []
        self._entrada = list(mensagens_entrada)
        self._pausa_final = pausa_final
        self.fechado = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        self.fechado = True

    async def send(self, data: str):
        self.enviadas.append(json.loads(data))

    async def recv(self):
        if self._entrada:
            await asyncio.sleep(0.01)
            return json.dumps(self._entrada.pop(0))
        await asyncio.sleep(self._pausa_final)
        return None


class Fase1BargeInTests(unittest.TestCase):
    def test_barge_in_livre_dispara_com_fala_sustentada_e_preserva_enunciado(self):
        import afe

        eventos = []
        vad = _FakeVad([True] * 10 + [False] * 8)
        inst = afe.AudioFrontEnd(
            on_barge_in=lambda tipo, pcm: eventos.append((tipo, pcm)),
            barge_in_livre=True,
            barge_in_blocos_min=4,
            barge_in_rms_min=0.01,
        )
        inst.injetar_motores(vad=vad, kws=None, denoiser=None)

        t = np.arange(512, dtype=np.float32) / 16000
        voz = (0.12 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        sil = np.zeros(512, dtype=np.float32)

        # 5 blocos de fala durante falando=True -> dispara barge-in ("fala") no 4º bloco
        for _ in range(5):
            inst.processar_bloco_sintetico(voz, None, falando=True)
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0][0], "fala")
        self.assertIsNotNone(eventos[0][1])
        self.assertGreater(len(eventos[0][1]), 0)

        # Reprodução cortada (falando=False) + resto da fala + silêncio -> enunciado pronto sem exigir wake
        for _ in range(5):
            inst.processar_bloco_sintetico(voz, None, falando=False)
        for _ in range(8):
            inst.processar_bloco_sintetico(sil, None, falando=False, silencio_fim_override=0.15)

        res = inst.aguardar_enunciado(espera=0.5, silencio_fim=0.15, exigir_wake=True)
        self.assertIsNotNone(res["pcm"])
        self.assertTrue(res["wake_detectado"])
        self.assertTrue(res["comando_direto"])

    def test_consumidor_audio_recebe_frames_limpos_e_ignora_erro_do_callback(self):
        import afe

        frames = []
        inst = afe.AudioFrontEnd()
        inst.registrar_consumidor_audio(lambda b: (_ for _ in ()).throw(RuntimeError("falha isolada")))
        inst.registrar_consumidor_audio(frames.append)

        bloco = np.full(512, 0.05, dtype=np.float32)
        inst.processar_bloco_sintetico(bloco, None, falando=False)
        self.assertEqual(len(frames), 1)
        self.assertEqual(len(frames[0]), 512 * 2)  # int16 = 2 bytes por amostra

        inst.remover_consumidor_audio(frames.append)
        inst.processar_bloco_sintetico(bloco, None, falando=False)
        self.assertEqual(len(frames), 1)

    def test_reprodutor_pcm_stream_reproduz_e_corta_imediato_em_parar_fala(self):
        import voz

        streams = []

        def factory(**kwargs):
            st = _FakeRawOutputStream(**kwargs)
            streams.append(st)
            return st

        rep = voz.ReprodutorPcmStream(sample_rate=24000, stream_factory=factory)
        rep.iniciar()
        try:
            for _ in range(6):
                rep.escrever(b"\x01\x00" * 240)
            time.sleep(0.04)
            self.assertGreaterEqual(rep.chunks_reproduzidos, 1)
            voz.parar_fala()
            time.sleep(0.03)
            self.assertFalse(voz.falando.is_set())
            self.assertTrue(any(s.abortado for s in streams))
        finally:
            rep.fechar()

    def test_preferencias_salvam_modo_e_barge_in_livre(self):
        import config
        import voz

        antigo_arq = voz.ARQUIVO_PREFERENCIAS
        antigo_modo = config.VOZ_MODO
        antigo_barge = config.VOZ_BARGE_IN_LIVRE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                voz.ARQUIVO_PREFERENCIAS = Path(tmp) / "voz.json"
                salvo = voz.salvar_preferencias({"modo": "live", "barge_in_livre": False})
                self.assertEqual(salvo["modo"], "live")
                self.assertFalse(salvo["barge_in_livre"])
                self.assertEqual(config.VOZ_MODO, "live")
                self.assertFalse(config.VOZ_BARGE_IN_LIVRE)

                lido = voz.preferencias()
                self.assertEqual(lido["modo"], "live")
                self.assertFalse(lido["barge_in_livre"])
        finally:
            voz.ARQUIVO_PREFERENCIAS = antigo_arq
            config.VOZ_MODO = antigo_modo
            config.VOZ_BARGE_IN_LIVRE = antigo_barge


class Fase3GeminiLiveTests(unittest.TestCase):
    def setUp(self):
        import seguranca
        import sessao
        seguranca.parada.clear()
        sessao.desbloquear("pin")

    def test_converter_schemas_e_montar_setup(self):
        import voz_live

        schemas = [{
            "type": "function",
            "function": {
                "name": "delegar_tarefa",
                "description": "Inicia pesquisa em segundo plano.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "objetivo": {"type": "string", "description": "Tema"},
                        "abrir_palco": {"type": "boolean", "description": "Abrir no palco"},
                    },
                    "required": ["objetivo"],
                },
            },
        }]
        setup = voz_live.montar_payload_setup(
            model="gemini-2.5-flash-native-audio-preview",
            voice_name="Charon",
            system_text="Sistema teste",
            tool_schemas=schemas,
        )
        self.assertEqual(setup["setup"]["model"], "models/gemini-2.5-flash-native-audio-preview")
        self.assertEqual(
            setup["setup"]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"],
            "Charon",
        )
        decls = setup["setup"]["tools"][0]["functionDeclarations"]
        self.assertEqual(decls[0]["name"], "delegar_tarefa")
        self.assertEqual(decls[0]["parameters"]["properties"]["abrir_palco"]["type"], "BOOLEAN")

    def test_sessao_live_envia_chave_no_header_recebe_audio_barge_in_e_executa_ferramenta_segura(self):
        import config
        import voz
        import voz_live

        antigo_modo = config.VOZ_MODO
        config.VOZ_MODO = "live"
        try:
            pcm_resposta = b"\x02\x00" * 160
            mensagens = [
                {"setupComplete": {}},
                {
                    "serverContent": {
                        "inputTranscription": {"text": "Qual o status do sistema?"},
                        "modelTurn": {
                            "parts": [{
                                "inlineData": {
                                    "mimeType": "audio/pcm;rate=24000",
                                    "data": base64.b64encode(pcm_resposta).decode("ascii"),
                                }
                            }]
                        },
                        "outputTranscription": {"text": "Verificando agora."},
                    }
                },
                {
                    "toolCall": {
                        "functionCalls": [
                            {"id": "call-1", "name": "listar_tarefas", "args": {}},
                            {"id": "call-2", "name": "desligar_pc", "args": {}},
                        ]
                    }
                },
                {"serverContent": {"interrupted": True}},
                {
                    "serverContent": {
                        "outputTranscription": {"text": "Tudo pronto."},
                        "turnComplete": True,
                    }
                },
            ]
            fake_ws = _FakeWebSocket(mensagens, pausa_final=0.15)
            headers_capturados = {}
            url_capturada = {}

            def ws_connect(url, headers):
                url_capturada["url"] = url
                headers_capturados.update(headers)
                return fake_ws

            streams = []
            reprodutor = voz.ReprodutorPcmStream(
                sample_rate=24000,
                stream_factory=lambda **kw: (streams.append(_FakeRawOutputStream(**kw)) or streams[-1]),
            )

            chamadas_ferramentas = []

            def exec_tool(nome, args, confirmar, origem):
                chamadas_ferramentas.append((nome, args, origem))
                if nome == "desligar_pc":
                    ok = confirmar("Confirma desligar?", {"risco": "CRITICO"})
                    return "Desligando" if ok else "Confirmação negada. Ação cancelada."
                return "Nenhuma tarefa ativa."

            conversas = []
            estados = []
            chave_teste = "AIzaSyTestSecretKey1234567890"

            sessao_live = voz_live.SessaoGeminiLive(
                confirmar=lambda _m, _p: False,  # nega ação crítica
                on_estado=lambda st, err: estados.append((st, err)),
                on_conversa=lambda papel, txt, orig: conversas.append((papel, txt, orig)),
                api_key=chave_teste,
                reprodutor=reprodutor,
                ws_connect=ws_connect,
                executar_ferramenta=exec_tool,
                tool_schemas=[],
                system_text="Teste",
            )
            sessao_live.alimentar_audio(b"\x01\x00" * 512)
            with mock.patch("memoria.salvar_msg") as mock_salvar:
                resultado = sessao_live.executar()

            self.assertIn(resultado, ("fallback", "parado"))
            self.assertGreaterEqual(mock_salvar.call_count, 2)
            # Chave NUNCA na URL, apenas no header
            self.assertNotIn(chave_teste, url_capturada["url"])
            self.assertEqual(headers_capturados.get("x-goog-api-key"), chave_teste)
            # Setup + chunk de áudio + toolResponse enviados
            self.assertTrue(any("setup" in m for m in fake_ws.enviadas))
            self.assertTrue(any("realtimeInput" in m for m in fake_ws.enviadas))
            tool_resps = [m for m in fake_ws.enviadas if "toolResponse" in m]
            self.assertEqual(len(tool_resps), 1)
            fresps = {r["id"]: r["response"]["result"] for r in tool_resps[0]["toolResponse"]["functionResponses"]}
            self.assertIn("Nenhuma tarefa ativa", fresps["call-1"])
            self.assertIn("negada", fresps["call-2"].lower())
            # Origem auditada como voz_live
            self.assertEqual([c[2] for c in chamadas_ferramentas], ["voz_live", "voz_live"])
            # Interrupção registrada e transcrição limpa (não manteve "Verificando agora." pós-interrupted)
            self.assertGreaterEqual(sessao_live.interrupcoes, 1)
            self.assertIn(("user", "Qual o status do sistema?", "voz_live"), conversas)
            self.assertIn(("assistant", "Tudo pronto.", "voz_live"), conversas)
            self.assertFalse(any("Verificando agora" in c[1] for c in conversas))
        finally:
            config.VOZ_MODO = antigo_modo
            reprodutor.fechar()

    def test_sessao_live_retorna_fallback_sem_vazar_chave_quando_ws_falha(self):
        import voz
        import voz_live

        chave_teste = "AIzaSySecretLeakCheck999999"

        def ws_falha(_url, _headers):
            raise ConnectionError(f"falha com chave {chave_teste}")

        rep = voz.ReprodutorPcmStream(
            sample_rate=24000,
            stream_factory=lambda **kw: _FakeRawOutputStream(**kw),
        )
        try:
            sessao_live = voz_live.SessaoGeminiLive(
                confirmar=lambda _m, _p: False,
                api_key=chave_teste,
                reprodutor=rep,
                ws_connect=ws_falha,
                tool_schemas=[],
                system_text="Teste",
            )
            res = sessao_live.executar()
            self.assertEqual(res, "fallback")
            self.assertIsNotNone(sessao_live.ultimo_erro)
            self.assertNotIn(chave_teste, sessao_live.ultimo_erro)
        finally:
            rep.fechar()


if __name__ == "__main__":
    unittest.main()
