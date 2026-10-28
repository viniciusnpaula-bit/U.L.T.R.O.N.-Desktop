import importlib
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop_runtime import DesktopRuntime

import config
import sessao
import desktop_runtime


class FakeMain:
    def __init__(self):
        self.pausado = threading.Event()
        self.ouvido = None

    def modo_voz(self, bandeja, entrada_teclado, stop_event, ouvido_pronto, microphone_device_index=None,
                 microphone_device_id=None):
        class FakeOuvido:
            def __init__(self):
                self.capturando = threading.Event()
                self.device_index = microphone_device_index
                self.device_id = microphone_device_id

            def set_device(self, device_index, device_id=None):
                self.device_index = device_index
                self.device_id = device_id

        self.ouvido = FakeOuvido()
        ouvido_pronto(self.ouvido)
        while not stop_event.is_set():
            if self.pausado.is_set():
                self.ouvido.capturando.clear()
            else:
                self.ouvido.capturando.set()
            stop_event.wait(0.005)
        self.ouvido.capturando.clear()


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.main = FakeMain()
        self.security = types.SimpleNamespace(
            pin_valido=lambda value: value == "2468",
            timeout=lambda name: 0.06,
            log_seg=lambda *args, **kwargs: None,
            redigir=lambda text: text,
            parada=threading.Event(),
            parar_tudo=lambda: None,
            IRREVERSIVEIS=frozenset({"executar_comando", "apagar_arquivo"}),
        )
        self.ocupado = type("Ocupado", (Exception,), {})
        self.biometria = types.SimpleNamespace(
            Ocupado=self.ocupado,
            disponivel=lambda: {"disponivel": False, "motivo": "Nenhum sensor de Windows Hello neste PC"},
            verificar=lambda: False,
        )
        self.memoria = types.SimpleNamespace(
            status_criptografia=lambda: {"cifrado": True, "algoritmo": "AES-256-GCM",
                                         "chave": "DPAPI", "migrado": True})
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

        def processar(text, confirmar, origem):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            self.calls.append((text, origem))
            try:
                if text == "confirm":
                    return confirmar("Confirma?", {
                        "acao": "arquivo.apagar", "risco": "CRITICO", "origem": "desktop",
                        "exige_pin": True,
                    })
                if text == "critical-pin-unconfigured":
                    return confirmar("Confirma?", {
                        "acao": "arquivo.apagar", "risco": "CRITICO", "origem": "desktop",
                        "exige_pin": False,
                    })
                if text == "high":
                    return confirmar("Confirma?", {
                        "acao": "sistema.desligar", "risco": "ALTO", "origem": "desktop",
                        "exige_pin": False,
                    })
                time.sleep(0.04)
                return "resposta " + text
            finally:
                with self.lock:
                    self.active -= 1

        self.brain = types.SimpleNamespace(processar=processar, NOTIFICADORES=[])
        self.spoken = []
        self.spoken_event = threading.Event()

        def falar(texto, eco=0.5):
            self.spoken.append(texto)
            self.spoken_event.set()

        self.voz = types.SimpleNamespace(falar=falar)
        self.modules = patch.dict(sys.modules, {
            "main": self.main, "cerebro": self.brain, "seguranca": self.security,
            "voz": self.voz, "biometria": self.biometria, "memoria": self.memoria,
        })
        self.modules.start()
        self.runtime = DesktopRuntime()
        self.runtime.start()

    def tearDown(self):
        sessao.bloquear()
        self.runtime.shutdown()
        self.modules.stop()

    def events_until(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        collected = []
        while time.monotonic() < deadline:
            collected.extend(self.runtime.poll_events())
            if predicate(collected):
                return collected
            time.sleep(0.005)
        return collected

    def test_startup_is_idempotent_and_shutdown_releases_capture(self):
        self.runtime.start()
        deadline = time.monotonic() + 1
        while self.main.ouvido is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNotNone(self.main.ouvido)
        self.assertTrue(self.main.ouvido.capturando.wait(0.5))
        self.runtime.shutdown()
        self.assertTrue(self.main.pausado.is_set())
        self.assertFalse(self.main.ouvido.capturando.is_set())

    def test_commands_are_serialized_and_use_desktop_origin(self):
        self.runtime.submit_command("um")
        self.runtime.submit_command("dois")
        events = self.events_until(lambda items: sum(e.get("type") == "command_result" for e in items) == 2)
        results = [e for e in events if e.get("type") == "command_result"]
        self.assertEqual(self.max_active, 1)
        self.assertEqual({text for text, origin in self.calls}, {"um", "dois"})
        self.assertTrue(all(origin == "desktop" for text, origin in self.calls))
        self.assertEqual({e["response"] for e in results}, {"resposta um", "resposta dois"})

    def test_typed_command_is_kept_in_conversation_without_duplicate_event(self):
        self.runtime.submit_command("hora")
        events = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items))
        self.assertFalse([e for e in events if e.get("type") == "conversation_turn"])
        turns = self.runtime.conversation_turns()
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])
        self.assertEqual(turns[0]["text"], "hora")
        self.assertEqual(turns[0]["source"], "texto")
        self.assertEqual(turns[1]["text"], "resposta hora")
        self.assertEqual(turns[1]["source"], "texto")

    def test_typed_response_is_spoken_without_blocking_command_result(self):
        release = threading.Event()
        started = threading.Event()

        def falar(texto, eco=0.5):
            self.spoken.append(texto)
            started.set()
            release.wait(1)

        self.voz.falar = falar
        self.addCleanup(release.set)
        self.runtime.submit_command("hora")
        events = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items))
        self.assertTrue(any(e.get("type") == "command_result" for e in events))
        self.assertTrue(started.wait(0.5))
        self.assertEqual(self.spoken, ["resposta hora"])
        self.assertFalse(release.is_set())

    def test_confirmation_result_that_is_not_text_is_not_spoken(self):
        self.runtime.submit_command("high")
        events = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items))
        result = next(e for e in events if e.get("type") == "command_result")
        self.assertIsNone(result["response"])
        self.assertEqual(self.spoken, [])

    def test_pause_waits_for_active_capture_to_release_and_can_resume(self):
        self.assertTrue(self.main.ouvido.capturando.wait(0.5))
        self.assertTrue(self.runtime.set_microphone_paused(True))
        self.assertTrue(self.main.pausado.is_set())
        self.assertFalse(self.main.ouvido.capturando.is_set())
        self.assertTrue(self.runtime.set_microphone_paused(False))
        self.assertFalse(self.main.pausado.is_set())

    def test_device_change_pauses_and_reuses_the_existing_capture_instance(self):
        audio = types.SimpleNamespace(
            query_devices=lambda: [
                {"name": "Output", "max_input_channels": 0, "hostapi": 0},
                {"name": "Webcam Mic", "max_input_channels": 1, "hostapi": 0},
            ],
            query_hostapis=lambda: [{"name": "WASAPI"}],
            default=types.SimpleNamespace(device=(1, 0)),
        )
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}), \
                patch.dict(sys.modules, {"sounddevice": audio}):
            self.assertTrue(self.main.ouvido.capturando.wait(0.5))
            existing_capture = self.main.ouvido
            self.runtime.select_microphone('["WASAPI","Webcam Mic",0]')
            self.assertIs(self.main.ouvido, existing_capture)
            self.assertEqual(existing_capture.device_index, 1)
            self.assertFalse(self.main.pausado.is_set())

    def test_core_notifications_are_forwarded_to_desktop_events(self):
        import palco
        palco.eventos()  # a fila do palco é global e não pertence a este teste
        self.brain.NOTIFICADORES[0]("Lembrete para o usuário")
        events = self.runtime.poll_events()
        self.assertEqual(events, [{"type": "notification", "message": "Lembrete para o usuário"}])

    def test_shutdown_request_is_reported_in_runtime_snapshot(self):
        self.runtime.request_shutdown()
        self.assertTrue(self.runtime.get_snapshot()["shutdown_requested"])

    def test_startup_status_uses_the_desktop_entry_not_core_tray_entry(self):
        autostart = types.SimpleNamespace(is_installed=lambda: True)
        with patch.dict(sys.modules, {"desktop_autostart": autostart}):
            self.assertTrue(self.runtime.get_snapshot()["autostart_installed"])

    def test_confirmation_timeout_cancels_high_risk_action(self):
        self.runtime.submit_command("high")
        events = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items), timeout=1)
        result = next(e for e in events if e.get("type") == "command_result")
        self.assertIsNone(result["response"])

    def test_critical_action_requires_valid_keyboard_pin(self):
        self.runtime.submit_command("confirm")
        events = self.events_until(lambda items: any(e.get("type") == "confirmation_request" for e in items))
        request = next(e for e in events if e.get("type") == "confirmation_request")
        self.assertTrue(request["requires_pin"])
        self.assertTrue(self.runtime.answer_confirmation(request["request_id"], True, "2468"))
        results = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items))
        result = next(e for e in results if e.get("type") == "command_result")
        self.assertIs(result["response"], True)

    def test_invalid_pin_cancels_critical_action(self):
        self.runtime.submit_command("confirm")
        events = self.events_until(lambda items: any(e.get("type") == "confirmation_request" for e in items))
        request = next(e for e in events if e.get("type") == "confirmation_request")
        self.assertTrue(self.runtime.answer_confirmation(request["request_id"], True, "0000"))
        results = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items))
        result = next(e for e in results if e.get("type") == "command_result")
        self.assertFalse(result["response"])

    def test_critical_action_always_requires_pin_even_if_core_config_marks_optional(self):
        self.runtime.submit_command("critical-pin-unconfigured")
        events = self.events_until(lambda items: any(e.get("type") == "confirmation_request" for e in items))
        request = next(e for e in events if e.get("type") == "confirmation_request")
        self.assertTrue(request["requires_pin"])
        self.assertTrue(self.runtime.answer_confirmation(request["request_id"], True))
        results = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items))
        result = next(e for e in results if e.get("type") == "command_result")
        self.assertFalse(result["response"])

    def test_snapshot_reports_locked_session(self):
        self.assertFalse(self.runtime.get_snapshot()["session_desbloqueada"])
        sessao.desbloquear("pin")
        self.assertTrue(self.runtime.get_snapshot()["session_desbloqueada"])

    def test_unlock_info_reports_real_state_without_raising(self):
        # o PIN do .env não pode decidir o resultado: aqui testamos os dois estados
        with patch.object(config, "PIN", ""):
            info = self.runtime.unlock_info()
        self.assertFalse(info["session"]["desbloqueada"])
        self.assertFalse(info["hello"]["disponivel"])
        self.assertFalse(info["pin_configurado"])
        self.assertEqual(info["irreversiveis"], ["apagar_arquivo", "executar_comando"])
        self.assertEqual(info["historico"]["algoritmo"], "AES-256-GCM")
        self.assertIn("versao", info)
        with patch.object(config, "PIN", "2468"):
            self.assertTrue(self.runtime.unlock_info()["pin_configurado"])

    def test_unlock_info_omits_history_when_memoria_is_unavailable(self):
        self.memoria.status_criptografia = lambda: (_ for _ in ()).throw(RuntimeError("sem chave"))
        self.assertNotIn("historico", self.runtime.unlock_info())

    def test_undo_list_returns_only_safe_diary_fields(self):
        diario = types.SimpleNamespace(listar=lambda limite: [{
            "id": "a" * 12,
            "operacao": "arquivo.apagar",
            "resumo": "apagar C:\\tmp\\a.txt",
            "desfeito": False,
            "criado": 1.0,
        }])
        with patch.dict(sys.modules, {"desfazer": diario}):
            resultado = self.runtime.undo_list()
        self.assertEqual(resultado["limite"], 10)
        self.assertEqual(resultado["itens"][0]["resumo"], "apagar C:\\tmp\\a.txt")
        self.assertNotIn("inversa", resultado["itens"][0])

    def test_undo_list_degrades_when_diary_is_unavailable(self):
        def explodir(_limite):
            raise RuntimeError("diário corrompido")

        with patch.dict(sys.modules, {"desfazer": types.SimpleNamespace(listar=explodir)}):
            resultado = self.runtime.undo_list()
        self.assertEqual(resultado, {"itens": [], "limite": 10, "indisponivel": True})

    def test_hello_unavailable_does_not_open_prompt(self):
        resultado = self.runtime.unlock_hello()
        self.assertEqual(resultado, {"unlocked": False, "error": "hello_unavailable"})
        self.assertFalse(sessao.estado()["desbloqueada"])

    def test_hello_verified_unlocks_session(self):
        self.biometria.disponivel = lambda: {"disponivel": True, "motivo": "Windows Hello pronto"}
        self.biometria.verificar = lambda: True
        resultado = self.runtime.unlock_hello()
        self.assertTrue(resultado["unlocked"])
        self.assertEqual(resultado["method"], "hello")
        self.assertEqual(sessao.estado()["metodo"], "hello")

    def test_hello_not_verified_and_busy_are_reported(self):
        self.biometria.disponivel = lambda: {"disponivel": True, "motivo": "pronto"}
        self.assertEqual(self.runtime.unlock_hello()["error"], "not_verified")

        def ocupado():
            raise self.ocupado("em andamento")

        self.biometria.verificar = ocupado
        self.assertEqual(self.runtime.unlock_hello()["error"], "busy")

    def test_pin_unlock_requires_configured_pin(self):
        # sem PIN no ambiente, o desbloqueio por PIN não está configurado
        with patch.object(config, "PIN", ""):
            self.assertEqual(self.runtime.unlock_pin("2468")["error"], "no_method_configured")
        with patch.object(config, "PIN", "2468"):
            self.assertEqual(self.runtime.unlock_pin("0000")["error"], "pin_invalid")
            resultado = self.runtime.unlock_pin("2468")
        self.assertTrue(resultado["unlocked"])
        self.assertEqual(resultado["method"], "pin")
        self.assertTrue(sessao.estado()["desbloqueada"])

    def test_five_wrong_pins_lock_for_the_wait_window(self):
        with patch.object(config, "PIN", "2468"), \
                patch.object(desktop_runtime, "UNLOCK_ESPERA_S", 0.05):
            for _ in range(4):
                self.assertEqual(self.runtime.unlock_pin("0000")["error"], "pin_invalid")
            self.assertEqual(self.runtime.unlock_pin("0000")["error"], "too_many_attempts")
            # durante a espera, nem o PIN certo passa
            self.assertEqual(self.runtime.unlock_pin("2468")["error"], "too_many_attempts")
            time.sleep(0.06)
            self.assertTrue(self.runtime.unlock_pin("2468")["unlocked"])

    def test_lock_ends_the_session(self):
        sessao.desbloquear("pin")
        self.assertEqual(self.runtime.lock(), {"locked": True})
        self.assertFalse(sessao.estado()["desbloqueada"])

    def test_unlocked_critical_action_does_not_ask_for_pin(self):
        sessao.desbloquear("pin")
        self.runtime.submit_command("confirm")
        events = self.events_until(lambda items: any(e.get("type") == "confirmation_request" for e in items))
        request = next(e for e in events if e.get("type") == "confirmation_request")
        self.assertFalse(request["requires_pin"])
        self.assertTrue(self.runtime.answer_confirmation(request["request_id"], True))
        results = self.events_until(lambda items: any(e.get("type") == "command_result" for e in items))
        self.assertIs(next(e for e in results if e.get("type") == "command_result")["response"], True)


class VoiceCaptureTests(unittest.TestCase):
    def test_capture_event_covers_inputstream_and_clears_when_pause_closes_it(self):
        class Frame:
            def copy(self):
                return self

            def astype(self, _type):
                return self

        class Stream:
            def __init__(self, callback, **kwargs):
                self.callback = callback
                self.kwargs = kwargs
                streams.append(kwargs)
                self.stop = threading.Event()

            def __enter__(self):
                def feed():
                    while not self.stop.is_set():
                        self.callback(Frame(), 1, None, None)
                        time.sleep(0.005)
                self.thread = threading.Thread(target=feed, daemon=True)
                self.thread.start()
                return self

            def __exit__(self, *_args):
                self.stop.set()
                self.thread.join(timeout=0.5)

        class BrokenStream(Stream):
            def __exit__(self, *args):
                super().__exit__(*args)
                raise RuntimeError("input stream failed while closing")

        np = types.SimpleNamespace(float32=float, mean=lambda data: 0, sqrt=lambda value: 0,
                                   concatenate=lambda frames: b"")
        sd = types.SimpleNamespace(InputStream=Stream)
        streams = []
        class Recognizer:
            pass
        sr = types.SimpleNamespace(Recognizer=Recognizer, AudioData=object)
        config = types.SimpleNamespace(LIMIAR_VOZ=400.0)
        security = types.SimpleNamespace(log=types.SimpleNamespace(warning=lambda *a: None))
        with patch.dict(sys.modules, {"numpy": np, "sounddevice": sd,
                                     "speech_recognition": sr, "config": config,
                                     "seguranca": security}):
            sys.modules.pop("voz", None)
            voice = importlib.import_module("voz")
            ouvido = voice.Ouvido(device_index=7)
            ouvido.pausado = threading.Event()
            result = []
            thread = threading.Thread(target=lambda: result.append(ouvido._gravar(30)))
            thread.start()
            self.assertTrue(ouvido.capturando.wait(0.5))
            self.assertEqual(streams[0]["device"], 7)
            ouvido.pausado.set()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertIsNone(result[0])
            self.assertFalse(ouvido.capturando.is_set())

            sd.InputStream = BrokenStream
            outro = voice.Ouvido()
            error = []
            def capture_with_error():
                try:
                    outro._gravar(0)
                except RuntimeError as exc:
                    error.append(str(exc))
            thread = threading.Thread(target=capture_with_error)
            thread.start()
            thread.join(timeout=1)
            self.assertEqual(error, ["input stream failed while closing"])
            self.assertFalse(outro.capturando.is_set())
            sys.modules.pop("voz", None)


class MicrophoneDeviceTests(unittest.TestCase):
    def test_device_list_only_contains_audio_inputs_and_uses_stable_identifiers(self):
        audio = types.SimpleNamespace(
            query_devices=lambda: [
                {"name": "Saída HDMI", "max_input_channels": 0, "hostapi": 0},
                {"name": "Webcam Mic", "max_input_channels": 1, "hostapi": 0},
            ],
            query_hostapis=lambda: [{"name": "WASAPI"}],
            default=types.SimpleNamespace(device=(1, 0)),
        )
        # O teste precisa de um estado limpo: sem isso, uma preferência de microfone
        # salva na máquina de quem roda os testes altera o resultado.
        with patch.dict(sys.modules, {"sounddevice": audio}), \
                patch.object(DesktopRuntime, "_microphone_settings_path",
                             classmethod(lambda cls: Path(tempfile.gettempdir())
                                        / f"ultron-teste-{os.getpid()}-{id(audio)}" / "microphone.json")):
            runtime = DesktopRuntime(start_voice=False)
            result = runtime.list_microphones()
        self.assertEqual([device["name"] for device in result["devices"]], ["Padrão do sistema", "Webcam Mic"])
        self.assertIsInstance(result["devices"][1]["id"], str)
        self.assertTrue(result["selected_available"])

    def test_selected_input_is_persisted_and_missing_input_is_not_substituted(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            devices = [{"name": "Webcam Mic", "max_input_channels": 1, "hostapi": 0}]
            audio = types.SimpleNamespace(
                query_devices=lambda: devices,
                query_hostapis=lambda: [{"name": "WASAPI"}],
                default=types.SimpleNamespace(device=(0, -1)),
            )
            with patch.dict(os.environ, {"LOCALAPPDATA": temp}), patch.dict(sys.modules, {"sounddevice": audio}):
                runtime = DesktopRuntime(start_voice=False)
                selected = runtime.select_microphone(runtime.list_microphones()["devices"][1]["id"])
                self.assertEqual(selected["selected_name"], "Webcam Mic")
                config_path = Path(temp) / "ULTRON" / "microphone.json"
                self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["name"], "Webcam Mic")
                devices.clear()
                missing = runtime.list_microphones()
            self.assertFalse(missing["selected_available"])
            self.assertEqual(missing["selected_name"], "Webcam Mic")
            self.assertEqual(runtime._microphone_device_index, -1)


if __name__ == "__main__":
    unittest.main()
