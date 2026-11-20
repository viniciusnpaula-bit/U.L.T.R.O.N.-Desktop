"""Testes de integração entre agendador, voz e encerramento gracioso no Desktop."""
import datetime
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agendador
import cerebro
import config
import desktop
import desktop_runtime
import main
import memoria
import seguranca
import sessao
import voz
from desktop_runtime import DesktopRuntime


class _FakeOuvido:
    device_index = 0
    device_id = None
    device_generation = 1
    capturando = threading.Event()
    ultimo_erro = None
    limiar = 400
    nivel_atual = 0

    def __init__(self, device_index=0, device_id=None, **_kwargs):
        self.device_index = device_index
        self.device_id = device_id
        self.pausado = threading.Event()
        self.pedido_manual = threading.Event()

    def set_device(self, device_index, device_id=None):
        self.device_index = device_index
        self.device_id = device_id
        self.device_generation += 1

    def calibrar(self):
        return None

    def recalibrar_se_necessario(self):
        return None

    def escutar_detalhado(self):
        time.sleep(0.01)
        return {"texto": None, "alternativas": [], "erro": None}


class _FakeMain:
    def __init__(self):
        self.pausado = threading.Event()
        self.ouvido = None

    def modo_voz(self, bandeja=False, entrada_teclado=False, stop_event=None,
                 ouvido_pronto=None, microphone_device_index=None,
                 microphone_device_id=None, notificar_voz=True, **_kwargs):
        self.notificar_voz_recebido = notificar_voz
        self.ouvido = _FakeOuvido(microphone_device_index, microphone_device_id)
        if ouvido_pronto is not None:
            ouvido_pronto(self.ouvido)
        while stop_event is None or not stop_event.is_set():
            if self.pausado.is_set():
                self.ouvido.capturando.clear()
            else:
                self.ouvido.capturando.set()
            if stop_event is not None:
                stop_event.wait(0.005)
            else:
                time.sleep(0.005)
        self.ouvido.capturando.clear()


class AgendadorVozDesktopTests(unittest.TestCase):
    def setUp(self):
        self._notificadores_orig = list(cerebro.NOTIFICADORES)
        self._ganchos_orig = list(seguranca.ganchos_parada)
        self._pausado_orig = main.pausado.is_set()
        self._parada_orig = seguranca.parada.is_set()
        self._voz_ativo_orig = getattr(config, "VOZ_ATIVO", True)
        self._voz_notif_orig = getattr(config, "VOZ_NOTIFICACOES", True)
        self._briefing_ativo_orig = getattr(config, "BRIEFING_ATIVO", False)
        self._briefing_hora_orig = getattr(config, "BRIEFING_HORA", "08:00")
        self._sessao_orig = sessao.estado().get("desbloqueada")

        cerebro.NOTIFICADORES.clear()
        seguranca.ganchos_parada.clear()
        main.pausado.clear()
        seguranca.parada.clear()
        voz._parar.clear()
        config.VOZ_ATIVO = True
        config.VOZ_NOTIFICACOES = True

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup)
        self._sessao_patch = patch.object(
            desktop_runtime, "ARQUIVO_SESSAO", Path(self._tmp.name) / "sessao.json"
        )
        self._sessao_patch.start()
        self._runtimes = []

    def _cleanup(self):
        for rt in self._runtimes:
            try:
                rt.shutdown()
            except Exception:
                pass
        self._sessao_patch.stop()
        self._tmp.cleanup()
        cerebro.NOTIFICADORES[:] = self._notificadores_orig
        seguranca.ganchos_parada[:] = self._ganchos_orig
        if self._pausado_orig:
            main.pausado.set()
        else:
            main.pausado.clear()
        if self._parada_orig:
            seguranca.parada.set()
        else:
            seguranca.parada.clear()
        voz._parar.clear()
        config.VOZ_ATIVO = self._voz_ativo_orig
        config.VOZ_NOTIFICACOES = self._voz_notif_orig
        config.BRIEFING_ATIVO = self._briefing_ativo_orig
        config.BRIEFING_HORA = self._briefing_hora_orig
        if self._sessao_orig:
            sessao.desbloquear("pin")
        else:
            sessao.bloquear()

    def _criar_runtime(self, *, start_voice=True, fake_main=None, fake_voz=None, stop_event=None):
        fm = fake_main or _FakeMain()
        mods = {"main": fm, "cerebro": cerebro, "seguranca": seguranca}
        if fake_voz is not None:
            mods["voz"] = fake_voz
        stack = ExitStack()
        stack.enter_context(patch.dict(sys.modules, mods))
        rt = DesktopRuntime(start_voice=start_voice, stop_event=stop_event)
        rt.start()
        self._runtimes.append(rt)
        self.addCleanup(stack.close)
        return rt, fm

    @staticmethod
    def _esperar(predicado, timeout=2.0):
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if predicado():
                return True
            time.sleep(0.01)
        return predicado()

    def test_1_lembrete_e_briefing_anunciados_por_voz_preservando_toast(self):
        falas = []
        pronto = threading.Event()

        def falar_fake(texto, eco=0.5, emocao="neutro"):
            falas.append(texto)
            if len(falas) >= 2:
                pronto.set()

        fake_voz = types.SimpleNamespace(falar=falar_fake, parar_fala=lambda: None, falando=threading.Event())
        rt, fm = self._criar_runtime(fake_voz=fake_voz)
        self.assertFalse(fm.notificar_voz_recebido if hasattr(fm, "notificar_voz_recebido") else False)

        memoria.add_lembrete(time.time() - 5, "tomar vitamina")
        config.BRIEFING_ATIVO = True
        config.BRIEFING_HORA = "08:00"

        ag = agendador.Agendador(
            executar_ferramenta=lambda nome, *_a: "São Paulo: 22°C" if nome == "clima" else ""
        )
        momento = datetime.datetime(2026, 11, 8, 9, 0).timestamp()
        ag.tick(momento)

        self.assertTrue(pronto.wait(2.0), f"Falas recebidas: {falas}")
        eventos = [e for e in rt.poll_events() if e.get("type") == "notification"]
        self.assertEqual(len(eventos), 2)
        self.assertIn("tomar vitamina", eventos[0]["message"])
        self.assertIn("Bom dia", eventos[1]["message"])
        self.assertIn("tomar vitamina", falas[0])
        self.assertIn("Bom dia", falas[1])

    def test_2_nao_bloqueia_agendador_nem_poll_enquanto_fala(self):
        iniciou = threading.Event()
        liberar = threading.Event()
        self.addCleanup(liberar.set)
        falas = []

        def falar_lento(texto):
            falas.append(texto)
            iniciou.set()
            liberar.wait(2.0)

        fake_voz = types.SimpleNamespace(falar=falar_lento, parar_fala=liberar.set, falando=threading.Event())
        rt, _ = self._criar_runtime(fake_voz=fake_voz)

        memoria.add_lembrete(time.time() - 1, "ligar para o médico")
        t0 = time.monotonic()
        agendador.Agendador().tick()
        duracao_tick = time.monotonic() - t0

        self.assertLess(duracao_tick, 0.3)
        self.assertTrue(iniciou.wait(1.0))
        self.assertFalse(liberar.is_set())
        eventos = rt.poll_events()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["type"], "notification")
        self.assertIn("ligar para o médico", eventos[0]["message"])
        self.assertIn("ligar para o médico", falas[0])

    def test_3_ausencia_de_voz_quando_desabilitada_ou_pausada_com_toast_preservado(self):
        falas = []
        fake_voz = types.SimpleNamespace(falar=falas.append, parar_fala=lambda: None, falando=threading.Event())

        # a) VOZ_ATIVO = False
        rt, _ = self._criar_runtime(fake_voz=fake_voz)
        with patch.object(config, "VOZ_ATIVO", False):
            cerebro.notificar("Aviso com voz global desligada")
            time.sleep(0.05)
        self.assertEqual(falas, [])
        self.assertEqual(
            [e["message"] for e in rt.poll_events()],
            ["Aviso com voz global desligada"],
        )

        # b) VOZ_NOTIFICACOES = False (silencia agendador, mantém comando digitado)
        with patch.object(config, "VOZ_NOTIFICACOES", False):
            cerebro.notificar("Lembrete silencioso")
            time.sleep(0.05)
            self.assertEqual(falas, [])
            self.assertEqual(
                [e["message"] for e in rt.poll_events()],
                ["Lembrete silencioso"],
            )
            rt._agendar_fala("Resposta explícita")
            self.assertTrue(self._esperar(lambda: falas == ["Resposta explícita"]))
        falas.clear()

        # c) Usuário pausou voz ("EM SILÊNCIO") -> sem fala automática; ao retomar, volta a falar
        self.assertTrue(rt.set_microphone_paused(True))
        cerebro.notificar("Aviso durante pausa")
        time.sleep(0.05)
        self.assertEqual(falas, [])
        self.assertEqual([e["message"] for e in rt.poll_events()], ["Aviso durante pausa"])
        self.assertTrue(rt.set_microphone_paused(False))
        cerebro.notificar("Aviso após retomar")
        self.assertTrue(self._esperar(lambda: falas == ["Aviso após retomar"]))
        self.assertEqual([e["message"] for e in rt.poll_events()], ["Aviso após retomar"])
        falas.clear()

        # d) Preferências de voz com notificações ou voz desativadas
        fake_voz.preferencias = lambda: {"voz": "pt-BR-AntonioNeural", "pitch": "-12Hz", "rate": "+0%", "notificacoes": False}
        cerebro.notificar("Aviso bloqueado por preferencia")
        time.sleep(0.05)
        self.assertEqual(falas, [])
        self.assertEqual([e["message"] for e in rt.poll_events()], ["Aviso bloqueado por preferencia"])
        delattr(fake_voz, "preferencias")

        # e) start_voice = False
        rt_sem_voz, _ = self._criar_runtime(start_voice=False, fake_voz=fake_voz)
        rt_sem_voz._notify("Aviso no modo sem voz")
        time.sleep(0.05)
        self.assertEqual(falas, [])
        self.assertEqual([e["message"] for e in rt_sem_voz.poll_events()], ["Aviso no modo sem voz"])

    def test_3b_falha_no_microfone_nao_impede_fala_de_lembretes(self):
        falas = []
        pronto = threading.Event()

        class MicQuebradoMain:
            def __init__(self):
                self.pausado = threading.Event()

            def modo_voz(self, **_kwargs):
                raise RuntimeError("sem microfone conectado")

        fake_voz = types.SimpleNamespace(
            falar=lambda t: (falas.append(t), pronto.set()),
            parar_fala=lambda: None,
            falando=threading.Event(),
        )
        rt, _ = self._criar_runtime(fake_main=MicQuebradoMain(), fake_voz=fake_voz)
        self.assertTrue(self._esperar(lambda: rt.get_snapshot()["microphone_state"] == "erro", timeout=1.5))

        memoria.add_lembrete(time.time() - 1, "reunião diária")
        agendador.Agendador().tick()

        self.assertTrue(pronto.wait(1.5))
        self.assertEqual(len(falas), 1)
        self.assertIn("reunião diária", falas[0])
        eventos = [e for e in rt.poll_events() if e.get("type") == "notification"]
        self.assertEqual(len(eventos), 1)

    def test_4_parada_de_emergencia_cala_fila_e_respeita_redacao(self):
        falas = []
        parou = threading.Event()
        iniciou = threading.Event()
        liberar = threading.Event()
        self.addCleanup(liberar.set)

        def falar_com_bloqueio(texto):
            falas.append(texto)
            iniciou.set()
            liberar.wait(1.0)

        def parar_fala():
            parou.set()
            liberar.set()

        fake_voz = types.SimpleNamespace(falar=falar_com_bloqueio, parar_fala=parar_fala, falando=threading.Event())
        with patch.object(seguranca, "redigir", side_effect=lambda s: str(s).replace("sk-secreta", "[OCULTO]")):
            rt, _ = self._criar_runtime(fake_voz=fake_voz)
            cerebro.notificar("Primeiro aviso com sk-secreta")
            self.assertTrue(iniciou.wait(1.0))
            cerebro.notificar("Segundo aviso que será cancelado")
            seguranca.parar_tudo()
            self.assertTrue(parou.wait(1.0))
            time.sleep(0.06)

            # Novo aviso enquanto parada está ativa não deve falar
            cerebro.notificar("Terceiro aviso bloqueado")
            time.sleep(0.06)

        self.assertEqual(falas, ["Primeiro aviso com [OCULTO]"])
        msgs = [e["message"] for e in rt.poll_events() if e.get("type") == "notification"]
        self.assertEqual(len(msgs), 3)
        self.assertIn("[OCULTO]", msgs[0])
        self.assertNotIn("sk-secreta", msgs[0])

    def test_5_falha_no_tts_preserva_notificacao_visual_e_nao_derruba_fila(self):
        tentativas = []
        falas_ok = []
        recuperou = threading.Event()

        def falar_instavel(texto):
            tentativas.append(texto)
            if len(tentativas) == 1:
                raise RuntimeError("falha simulada no TTS")
            falas_ok.append(texto)
            recuperou.set()

        fake_voz = types.SimpleNamespace(falar=falar_instavel, parar_fala=lambda: None, falando=threading.Event())
        rt, _ = self._criar_runtime(fake_voz=fake_voz)

        with patch.object(seguranca.log, "warning") as warn:
            cerebro.notificar("Lembrete com falha no áudio")
            cerebro.notificar("Lembrete seguinte recuperado")
            self.assertTrue(recuperou.wait(2.0))

        self.assertGreaterEqual(warn.call_count, 1)
        self.assertEqual(falas_ok, ["Lembrete seguinte recuperado"])
        eventos = [e["message"] for e in rt.poll_events() if e.get("type") == "notification"]
        self.assertEqual(eventos, ["Lembrete com falha no áudio", "Lembrete seguinte recuperado"])

    def test_6_evita_duplicacao_com_modo_voz_real_e_serializa_concorrencia(self):
        falas = []
        lock = threading.Lock()
        ativo = {"n": 0, "max": 0}
        concluido = threading.Event()

        def falar_seguro(texto, eco=0.5, emocao="neutro"):
            with lock:
                ativo["n"] += 1
                ativo["max"] = max(ativo["max"], ativo["n"])
                falas.append(texto)
            time.sleep(0.03)
            with lock:
                ativo["n"] -= 1
                if len(falas) >= 3:
                    concluido.set()

        fake_voz = types.SimpleNamespace(
            Ouvido=_FakeOuvido,
            falar=falar_seguro,
            falar_partes=lambda *_a, **_k: "",
            parar_fala=lambda: None,
            falando=threading.Event(),
        )
        with patch.dict(sys.modules, {"voz": fake_voz, "cerebro": cerebro, "seguranca": seguranca, "main": main}), \
                patch.object(main, "atalho_falar", lambda _e: None), \
                patch.object(main.personalidade, "saudacao_ao_abrir", lambda: False):
            rt = DesktopRuntime(start_voice=True)
            self._runtimes.append(rt)
            rt.start()
            self.assertTrue(self._esperar(lambda: rt._ouvido is not None, timeout=1.5))

            # Mesmo com main.modo_voz real rodando no Desktop, NÃO há dois notificadores de voz!
            self.assertEqual(len(cerebro.NOTIFICADORES), 1)
            self.assertEqual(cerebro.NOTIFICADORES, [rt._notify])

            # Disparo duplicado idêntico em rajada não fala duas vezes
            cerebro.notificar("Lembrete um")
            cerebro.notificar("Lembrete um")
            # Avisos distintos em rajada são serializados sem concorrência simultânea
            cerebro.notificar("Lembrete dois")
            cerebro.notificar("Lembrete três")

            self.assertTrue(concluido.wait(2.5), f"Falas observadas: {falas}")
            rt.shutdown()

        self.assertEqual(falas, ["Lembrete um", "Lembrete dois", "Lembrete três"])
        self.assertEqual(ativo["max"], 1)
        self.assertEqual(cerebro.NOTIFICADORES, [])
        self.assertNotIn(rt._on_emergency_stop, seguranca.ganchos_parada)

    def test_7_modo_voz_isolado_remove_callbacks_ao_sair(self):
        falas = []
        fake_voz = types.SimpleNamespace(
            Ouvido=_FakeOuvido,
            falar=lambda t, *_a, **_k: falas.append(t),
            falar_partes=lambda *_a, **_k: "",
            parar_fala=lambda: None,
            falando=threading.Event(),
        )
        parar = threading.Event()
        pronto = threading.Event()

        def ouv(_o):
            pronto.set()

        with patch.dict(sys.modules, {"voz": fake_voz}), \
                patch.object(main, "atalho_falar", lambda _e: None), \
                patch.object(main.personalidade, "saudacao_ao_abrir", lambda: False):
            t = threading.Thread(
                target=main.modo_voz,
                kwargs={"bandeja": False, "entrada_teclado": False, "stop_event": parar, "ouvido_pronto": ouv},
                daemon=True,
            )
            t.start()
            self.assertTrue(pronto.wait(1.5))
            self.assertTrue(self._esperar(lambda: fake_voz.parar_fala in seguranca.ganchos_parada and len(cerebro.NOTIFICADORES) == 1))
            cerebro.notificar("Aviso CLI")
            self.assertEqual(falas, ["Aviso CLI"])
            parar.set()
            t.join(timeout=2.0)

        self.assertFalse(t.is_alive())
        self.assertEqual(cerebro.NOTIFICADORES, [])
        self.assertNotIn(fake_voz.parar_fala, seguranca.ganchos_parada)

    def test_8_compatibilidade_real_voz_falar_sem_regressao(self):
        chamadas_fala = []
        with patch.object(voz, "_sintetizar", side_effect=RuntimeError("offline")), \
                patch.object(voz, "_falar_offline", side_effect=chamadas_fala.append):
            rt, _ = self._criar_runtime(fake_voz=voz)
            cerebro.notificar("Lembrete **importante**: https://exemplo.invalid revisar relatório")
            self.assertTrue(self._esperar(lambda: len(chamadas_fala) == 1, timeout=2.5))
            rt.shutdown()
            self.assertFalse(rt._speech_thread and rt._speech_thread.is_alive())

        self.assertEqual(chamadas_fala, ["Lembrete importante: revisar relatório"])
        self.assertFalse(voz.falando.is_set())

    def test_9_encerramento_gracioso_agendador_e_desktop_cleanup(self):
        stop_recebido = []
        ag_threads = []
        ag_iniciado = threading.Event()
        ag_finalizado = threading.Event()

        def loop_lembretes_fake(stop_event=None):
            stop_recebido.append(stop_event)
            ag_threads.append(threading.current_thread())
            ag_iniciado.set()
            if stop_event is not None:
                stop_event.wait(5.0)
            ag_finalizado.set()

        fake_config = types.SimpleNamespace(PROVEDORES=["gemini"], CHAVES={"gemini": "k"}, BASE=Path.cwd())
        fake_core = types.SimpleNamespace(
            instancia_unica=lambda: True,
            preparar_windows=lambda: None,
            loop_lembretes=loop_lembretes_fake,
            atalho_parada=lambda: None,
        )
        fake_security = types.SimpleNamespace(log=types.SimpleNamespace(error=lambda *_a: None))
        fake_telegram = types.SimpleNamespace(iniciar=lambda: False)
        fake_tk = types.ModuleType("tkinter")
        fake_tk.messagebox = types.SimpleNamespace(showerror=lambda *_a, **_k: None, showinfo=lambda *_a, **_k: None)

        rt_capturado = []

        class FakeRuntimeDesktop:
            def __init__(self, start_voice=True, stop_event=None):
                self.stop_event = stop_event
                self.started = False
                self.stopped = False
                rt_capturado.append(self)

            def start(self):
                self.started = True

            def set_api_running(self, _value):
                pass

            def shutdown(self):
                self.stopped = True
                if self.stop_event is not None:
                    self.stop_event.set()

        class FakeServer:
            def __init__(self):
                self._stop = threading.Event()

            def serve_forever(self):
                self._stop.wait(1.0)

            def shutdown(self):
                self._stop.set()

            def server_close(self):
                pass

        with patch.dict(sys.modules, {
            "config": fake_config,
            "main": fake_core,
            "seguranca": fake_security,
            "telegram_bot": fake_telegram,
            "desktop_runtime": types.SimpleNamespace(DesktopRuntime=FakeRuntimeDesktop),
            "desktop_api": types.SimpleNamespace(create_server=lambda _rt, _tok: (FakeServer(), "http://127.0.0.1:3900")),
            "tkinter": fake_tk,
        }), patch.object(desktop, "_electron_paths", return_value=(Path("electron.exe"), Path("app"))), \
                patch.object(desktop, "_launch_electron", side_effect=lambda *_a: (ag_iniciado.wait(1.0), 0)[1]):
            codigo = desktop.main()

        self.assertEqual(codigo, 0)
        self.assertTrue(ag_iniciado.is_set())
        self.assertEqual(len(stop_recebido), 1)
        self.assertIsNotNone(stop_recebido[0])
        self.assertTrue(stop_recebido[0].is_set())
        self.assertTrue(ag_finalizado.is_set())
        self.assertFalse(ag_threads[0].is_alive())
        self.assertIs(rt_capturado[0].stop_event, stop_recebido[0])
        self.assertTrue(rt_capturado[0].stopped)

    def test_9b_cleanup_encerra_agendador_mesmo_quando_api_falha_no_startup(self):
        stop_recebido = []
        ag_threads = []
        ag_iniciado = threading.Event()
        ag_finalizado = threading.Event()

        def loop_lembretes_fake(stop_event=None):
            stop_recebido.append(stop_event)
            ag_threads.append(threading.current_thread())
            ag_iniciado.set()
            if stop_event is not None:
                stop_event.wait(5.0)
            ag_finalizado.set()

        fake_config = types.SimpleNamespace(PROVEDORES=["gemini"], CHAVES={"gemini": "k"}, BASE=Path.cwd())
        fake_core = types.SimpleNamespace(
            instancia_unica=lambda: True,
            preparar_windows=lambda: None,
            loop_lembretes=loop_lembretes_fake,
            atalho_parada=lambda: None,
        )
        fake_security = types.SimpleNamespace(log=types.SimpleNamespace(error=lambda *_a: None))
        fake_telegram = types.SimpleNamespace(iniciar=lambda: False)
        fake_tk = types.ModuleType("tkinter")
        fake_tk.messagebox = types.SimpleNamespace(showerror=lambda *_a, **_k: None, showinfo=lambda *_a, **_k: None)

        class FakeRuntimeDesktop:
            def __init__(self, start_voice=True, stop_event=None):
                self.stop_event = stop_event

            def start(self):
                pass

            def set_api_running(self, _value):
                pass

            def shutdown(self):
                pass

        def falhar_server(_rt, _tok):
            ag_iniciado.wait(1.0)
            raise OSError("porta indisponível")

        with patch.dict(sys.modules, {
            "config": fake_config,
            "main": fake_core,
            "seguranca": fake_security,
            "telegram_bot": fake_telegram,
            "desktop_runtime": types.SimpleNamespace(DesktopRuntime=FakeRuntimeDesktop),
            "desktop_api": types.SimpleNamespace(create_server=falhar_server),
            "tkinter": fake_tk,
        }):
            codigo = desktop.main()

        self.assertEqual(codigo, 1)
        self.assertTrue(stop_recebido[0].is_set())
        self.assertTrue(ag_finalizado.is_set())
        self.assertFalse(ag_threads[0].is_alive())

    def test_10_agendador_tick_para_antes_quando_stop_event_esta_ativo(self):
        avisos = []
        stop = threading.Event()
        stop.set()
        memoria.add_lembrete(time.time() - 1, "não deve disparar encerrado")
        ag = agendador.Agendador(notificar=avisos.append, stop_event=stop)
        ag.tick()
        self.assertEqual(avisos, [])
        self.assertEqual(len(memoria.lembretes_numerados()), 1)

        # main.loop_lembretes(stop_event) aceita o evento e sai de imediato quando sinalizado
        feito = threading.Event()
        def _rodar():
            main.loop_lembretes(stop)
            feito.set()
        th = threading.Thread(target=_rodar, daemon=True)
        th.start()
        self.assertTrue(feito.wait(1.0))
        th.join(timeout=1.0)
        self.assertFalse(th.is_alive())


if __name__ == "__main__":
    unittest.main()
