"""Testes do ciclo completo de Function Calling nos comandos de voz (voz -> cérebro -> ferramentas -> segurança -> fala)."""
import json
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cerebro
import config
import confirmacao
import ferramentas
import main
import memoria
import registro
import seguranca
import sessao
import teclado
import voz


def _chunk(content=None, tool_calls=None):
    return types.SimpleNamespace(
        choices=[
            types.SimpleNamespace(
                delta=types.SimpleNamespace(content=content, tool_calls=tool_calls)
            )
        ]
    )


def _tc_delta(index=0, tc_id=None, name=None, arguments=None):
    return types.SimpleNamespace(
        index=index,
        id=tc_id,
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )


def _msg_final(content="", tool_calls=None):
    return types.SimpleNamespace(
        choices=[
            types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content=content, tool_calls=tool_calls or []
                )
            )
        ]
    )


class _FakeOuvido:
    device_index = 0
    device_generation = 1
    capturando = threading.Event()
    ultimo_erro = None
    limiar = 400
    nivel_atual = 0

    def __init__(self, falas, falas_confirmacao=None, manual=None):
        self.pausado = threading.Event()
        self.pedido_manual = threading.Event()
        self._falas = list(falas)
        self._conf = list(falas_confirmacao or [])
        self._manual = list(manual or [])

    def calibrar(self):
        return None

    def recalibrar_se_necessario(self):
        return None

    def notificar_comando_reconhecido(self):
        return None

    def escutar_detalhado(self):
        texto = self._falas.pop(0) if self._falas else None
        return {"texto": texto, "alternativas": [texto] if texto else [], "erro": None}

    def escutar(self, espera=8, curto=False):
        if curto and self._conf:
            return self._conf.pop(0)
        return self._falas.pop(0) if self._falas else None

    def escutar_manual(self):
        return self._manual.pop(0) if self._manual else None


class _FakeVoz:
    def __init__(self):
        self.falas_streaming = []
        self.falas_diretas = []
        self.todas_falas = []
        self.falando = threading.Event()

    def parar_fala(self):
        voz.parar_fala()

    def falar_partes(self, partes, eco=0.3):
        with voz._lock_fala:
            coletadas = []
            for frase in partes:
                txt = str(frase or "").strip()
                if txt:
                    coletadas.append(txt)
                    self.falas_streaming.append(txt)
                    self.todas_falas.append(txt)
            return " ".join(coletadas)

    def falar(self, texto, eco=0.5, emocao=registro.NEUTRO):
        with voz._lock_fala:
            txt = str(texto or "").strip()
            if txt:
                self.falas_diretas.append((txt, emocao))
                self.todas_falas.append(txt)


class _ClienteSequencial:
    """Simula chamadas openAI-compatíveis (stream=True ou stream=False) e registra os kwargs."""

    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.requisicoes = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        # Copia rasa das mensagens para inspeção posterior do histórico exato enviado
        req = dict(kwargs)
        req["messages"] = [dict(m) for m in (kwargs.get("messages") or [])]
        self.requisicoes.append(req)
        item = self._respostas.pop(0)
        if callable(item) and not isinstance(item, type):
            item = item(req)
        if isinstance(item, Exception):
            raise item
        return item


class VozFunctionCallingTests(unittest.TestCase):
    def setUp(self):
        cerebro.esquecer_clientes()
        seguranca.parada.clear()
        voz._parar.clear()
        sessao.desbloquear("pin")
        self._notificadores_orig = list(cerebro.NOTIFICADORES)
        self._ganchos_orig = list(seguranca.ganchos_parada)
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        cerebro.esquecer_clientes()
        seguranca.parada.clear()
        voz._parar.clear()
        sessao.bloquear()
        cerebro.NOTIFICADORES[:] = self._notificadores_orig
        seguranca.ganchos_parada[:] = self._ganchos_orig

    def _executar_modo_voz(self, cliente, ouvido, voz_mock, max_falas=1):
        publicados = []
        parar = threading.Event()
        assistente_count = {"n": 0}

        def conversa(papel, texto, origem):
            publicados.append((papel, texto, origem))
            if papel == "assistant":
                assistente_count["n"] += 1
                if assistente_count["n"] >= max_falas:
                    parar.set()

        def estado(nome, erro=None):
            if nome == "encerrado":
                parar.set()

        with patch.dict(sys.modules, {"voz": types.SimpleNamespace(
            Ouvido=lambda **_k: ouvido,
            falar=voz_mock.falar,
            falar_partes=voz_mock.falar_partes,
            parar_fala=voz_mock.parar_fala,
            falando=voz_mock.falando,
        )}), \
             patch.object(cerebro, "_cliente", lambda _p: cliente), \
             patch.object(cerebro.config, "PROVEDORES", ["gemini"]), \
             patch.object(cerebro.config, "CHAVES", {"gemini": "chave-teste"}), \
             patch.object(cerebro.config, "MODELOS", {"gemini": "gemini-2.5-flash"}), \
             patch.object(cerebro.config, "REASONING", ""), \
             patch.object(cerebro, "_system", lambda: "sys"), \
             patch.object(cerebro, "_contexto", lambda _t, _r=None: ""), \
             patch.object(cerebro, "_rastrear"), \
             patch.object(main, "atalho_falar", lambda _e: None), \
             patch.object(main.personalidade, "saudacao_ao_abrir", lambda: False):
            main.modo_voz(
                bandeja=False,
                entrada_teclado=False,
                stop_event=parar,
                estado_voz=estado,
                conversa=conversa,
            )
        return publicados

    # 1. Pergunta comum por voz sem ferramenta
    def test_1_pergunta_comum_sem_ferramenta_passa_tools_e_faz_streaming(self):
        cliente = _ClienteSequencial([
            iter([
                _chunk(content="[[registro:neutro]] A capital "),
                _chunk(content="da França é Paris. "),
                _chunk(content="Posso ajudar em algo mais?"),
            ])
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, qual a capital da França?"])
        voz_mock = _FakeVoz()

        with patch.object(ferramentas, "executar", side_effect=AssertionError("Não deveria executar ferramenta")):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(len(cliente.requisicoes), 1)
        req = cliente.requisicoes[0]
        self.assertTrue(req["stream"])
        self.assertEqual(req["tool_choice"], "auto")
        self.assertEqual(req["tools"], ferramentas.schemas())

        self.assertEqual(
            voz_mock.falas_streaming,
            ["A capital da França é Paris.", "Posso ajudar em algo mais?"],
        )
        # Não fala uma segunda vez fora do streaming
        self.assertEqual(voz_mock.falas_diretas, [])
        self.assertIn(
            ("assistant", "A capital da França é Paris. Posso ajudar em algo mais?", "voz"),
            publicados,
        )
        msgs_salvas = memoria.historico(10)
        self.assertEqual(msgs_salvas[-1]["content"], "A capital da França é Paris. Posso ajudar em algo mais?")

    # 2. Comando de voz que exige ferramenta (tool_calls em chunks) + 3. Retorno do resultado
    def test_2_e_3_comando_voz_exige_ferramenta_executa_uma_vez_e_retorna_resultado(self):
        chamadas_clima = []

        class RespHTTP:
            def __init__(self, dados):
                self._dados = dados

            def json(self):
                return self._dados

        def fake_get(url, params=None, timeout=10):
            chamadas_clima.append((url, params))
            if "geocoding-api" in url:
                return RespHTTP({"results": [{"name": "Curitiba", "latitude": -25.42, "longitude": -49.27}]})
            return RespHTTP({
                "current": {
                    "temperature_2m": 18,
                    "apparent_temperature": 17,
                    "relative_humidity_2m": 72,
                    "weather_code": 3,
                    "wind_speed_10m": 11,
                },
                "daily": {
                    "temperature_2m_min": [12, 13, 14],
                    "temperature_2m_max": [22, 23, 24],
                    "precipitation_probability_max": [20, 10, 5],
                },
            })

        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_clima_1", name="clima", arguments="")]),
                _chunk(tool_calls=[_tc_delta(index=0, arguments='{"cidad')]),
                _chunk(tool_calls=[_tc_delta(index=0, arguments='e": "Curitiba"}')]),
            ]),
            _msg_final(content="Em Curitiba faz 18 graus agora, com céu nublado."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, qual o clima em Curitiba agora?"])
        voz_mock = _FakeVoz()

        with patch.object(ferramentas.requests, "get", side_effect=fake_get):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        # Stream (turno 1) + Follow-up após ferramenta (turno 2): zero chamada duplicada!
        self.assertEqual(len(cliente.requisicoes), 2)
        self.assertEqual(len(chamadas_clima), 2)  # 1 geocode + 1 forecast => clima executou 1x
        # Confere que o resultado real da ferramenta foi entregue ao modelo na 2ª chamada
        mensagens_turno2 = cliente.requisicoes[1]["messages"]
        tool_msgs = [m for m in mensagens_turno2 if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "call_clima_1")
        self.assertIn("Curitiba: agora 18", tool_msgs[0]["content"])

        self.assertEqual(
            [t for t, _ in voz_mock.falas_diretas],
            ["Em Curitiba faz 18 graus agora, com céu nublado."],
        )
        self.assertIn(
            ("assistant", "Em Curitiba faz 18 graus agora, com céu nublado.", "voz"),
            publicados,
        )

    def test_3b_preambulo_antes_de_tool_calls_nao_descarta_ferramenta_nem_resultado(self):
        execucoes = []

        def fake_info():
            execucoes.append(1)
            return "CPU 25%, RAM 8 GB"

        cliente = _ClienteSequencial([
            iter([
                _chunk(content="Vou verificar o sistema. "),
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_sys", name="info_sistema", arguments="{}")]),
            ]),
            _msg_final(content="O sistema está com CPU em 25% e 8 GB de RAM."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, como está o sistema?"])
        voz_mock = _FakeVoz()

        fake_psutil = types.SimpleNamespace(
            cpu_percent=lambda interval=0.5: 25,
            virtual_memory=lambda: types.SimpleNamespace(percent=50, used=8 * 1024**3, total=16 * 1024**3),
            disk_usage=lambda _p: types.SimpleNamespace(percent=40, free=100 * 1024**3),
            sensors_battery=lambda: None,
        )
        with patch.dict(sys.modules, {"psutil": fake_psutil}), \
             patch.object(ferramentas, "executar", wraps=ferramentas.executar) as spy_exec:
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(spy_exec.call_count, 1)
        self.assertEqual(spy_exec.call_args.args[0], "info_sistema")
        self.assertEqual(
            [t for t, _ in voz_mock.falas_diretas],
            ["O sistema está com CPU em 25% e 8 GB de RAM."],
        )
        self.assertIn(
            ("assistant", "O sistema está com CPU em 25% e 8 GB de RAM.", "voz"),
            publicados,
        )

    def test_3c_falha_no_meio_do_stream_fala_e_publica_resposta_completa_do_fallback(self):
        def fluxo_que_cai(_req):
            yield _chunk(content="Primeira parte. ")
            raise TimeoutError("caiu no meio")

        cliente = _ClienteSequencial([
            fluxo_que_cai,
            _msg_final(content="Resposta completa recuperada do fallback."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, explique isso"])
        voz_mock = _FakeVoz()

        publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(voz_mock.falas_streaming, ["Primeira parte."])
        self.assertEqual(
            [t for t, _ in voz_mock.falas_diretas],
            ["Resposta completa recuperada do fallback."],
        )
        self.assertIn(
            ("assistant", "Resposta completa recuperada do fallback.", "voz"),
            publicados,
        )

    # 4. Comando de voz que exige confirmação (CONFIRM aprovado, negado, e crítico com PIN)
    def test_4a_confirmacao_por_voz_aprovada_executa_sem_deadlock(self):
        executou_shutdown = []

        def fake_run(cmd, **_kwargs):
            executou_shutdown.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_desl", name="desligar_pc", arguments="{}")]),
            ]),
            _msg_final(content="Desligamento agendado para daqui a 30 segundos."),
        ])
        ouvido = _FakeOuvido(
            ["Ei, Ultron, desliga o computador"],
            falas_confirmacao=[["sim"]],
        )
        voz_mock = _FakeVoz()

        # Usa voz.falar_partes REAL (adquire voz._lock_fala!) para provar ausência de deadlock com confirmar_voz
        voz_mock.falar_partes = voz.falar_partes
        with patch.object(ferramentas.subprocess, "run", side_effect=fake_run), \
             patch.object(voz.time, "sleep", lambda *_a: None), \
             patch.object(teclado, "disponivel", return_value=False):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(len(executou_shutdown), 1)
        self.assertEqual(executou_shutdown[0][:2], ["shutdown", "/s"])
        # Confirmador falou a pergunta E depois a resposta final foi falada
        self.assertTrue(any("Confirma?" in t for t, _ in voz_mock.falas_diretas))
        self.assertIn("Desligamento agendado para daqui a 30 segundos.", [t for t, _ in voz_mock.falas_diretas])
        self.assertIn(("assistant", "Desligamento agendado para daqui a 30 segundos.", "voz"), publicados)

    def test_4b_confirmacao_negada_cancela_e_nao_repergunta_em_loop(self):
        executou_shutdown = []
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_desl1", name="desligar_pc", arguments="{}")]),
            ]),
            # Modelo insiste na mesma chamada no passo seguinte -> cache bloqueia sem pedir confirmação de novo!
            _msg_final(tool_calls=[
                types.SimpleNamespace(id="call_desl2", function=types.SimpleNamespace(
                    name="desligar_pc", arguments="{}"))
            ]),
            _msg_final(content="Certo, desligamento cancelado."),
        ])
        ouvido = _FakeOuvido(
            ["Ei, Ultron, desliga o PC"],
            falas_confirmacao=[["não"], ["sim"]],
        )
        voz_mock = _FakeVoz()
        chamadas_confirm = {"n": 0}
        orig_pedir = seguranca.pedir_confirmacao

        def spy_pedir(conf, ped):
            chamadas_confirm["n"] += 1
            return orig_pedir(conf, ped)

        with patch.object(ferramentas.subprocess, "run", side_effect=lambda *a, **k: executou_shutdown.append(a)), \
             patch.object(seguranca, "pedir_confirmacao", side_effect=spy_pedir), \
             patch.object(teclado, "disponivel", return_value=False):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(executou_shutdown, [])
        self.assertEqual(len(cliente.requisicoes), 3)
        self.assertEqual(chamadas_confirm["n"], 1)
        self.assertIn("Certo, desligamento cancelado.", [t for t, _ in voz_mock.falas_diretas])
        self.assertIn(("assistant", "Certo, desligamento cancelado.", "voz"), publicados)

    def test_4c_acao_critica_sessao_bloqueada_exige_pin_e_bloqueia_sem_teclado(self):
        executou_cmd = []
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_cmd", name="executar_comando", arguments='{"comando": "ipconfig"}')]),
            ]),
            _msg_final(content="Bloqueado por falta de teclado para o código."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, rode ipconfig"], falas_confirmacao=[["sim"]])
        voz_mock = _FakeVoz()

        chamadas_estado = {"n": 0}

        def estado_misto():
            chamadas_estado["n"] += 1
            if chamadas_estado["n"] == 1:
                return {"desbloqueada": True, "metodo": "pin"}
            return {"desbloqueada": False, "metodo": None}

        with patch.object(config, "PIN_HASH", ""), \
             patch.object(config, "PIN", "1234"), \
             patch.object(sessao, "estado", side_effect=estado_misto), \
             patch.object(teclado, "disponivel", return_value=False), \
             patch.object(seguranca, "pedir_confirmacao", wraps=seguranca.pedir_confirmacao) as spy_conf, \
             patch.object(ferramentas.subprocess, "run", side_effect=lambda *a, **k: executou_cmd.append(a)):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(executou_cmd, [])
        self.assertEqual(spy_conf.call_count, 1)
        self.assertTrue(any("exige PIN" in t for t, _ in voz_mock.falas_diretas))
        self.assertIn(("assistant", "Bloqueado por falta de teclado para o código.", "voz"), publicados)

    def test_4d_acao_critica_com_pin_valido_executa_uma_vez(self):
        executou_cmd = []
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_cmd_ok", name="executar_comando", arguments='{"comando": "ipconfig"}')]),
            ]),
            _msg_final(content="Endereço IP verificado."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, rode ipconfig"], falas_confirmacao=[["sim"]])
        voz_mock = _FakeVoz()

        chamadas_estado = {"n": 0}

        def estado_misto():
            chamadas_estado["n"] += 1
            if chamadas_estado["n"] == 1:
                return {"desbloqueada": True, "metodo": "pin"}
            return {"desbloqueada": False, "metodo": None}

        with patch.object(config, "PIN_HASH", ""), \
             patch.object(config, "PIN", "1234"), \
             patch.object(sessao, "estado", side_effect=estado_misto), \
             patch.object(teclado, "disponivel", return_value=True), \
             patch.object(teclado, "ler_linha", return_value="1234"), \
             patch.object(ferramentas.subprocess, "run", side_effect=lambda *a, **k: (
                 executou_cmd.append(a),
                 types.SimpleNamespace(returncode=0, stdout="IPv4: 192.168.0.10", stderr=""),
             )[1]):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(len(executou_cmd), 1)
        self.assertTrue(any("Digite o PIN" in t for t, _ in voz_mock.falas_diretas))
        self.assertIn(("assistant", "Endereço IP verificado.", "voz"), publicados)

    # 5. Comando negado pelo sistema de segurança (DENY)
    def test_5_comando_negado_pela_seguranca_nao_executa_e_informa_usuario(self):
        executou_cmd = []
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_ps", name="executar_comando", arguments='{"comando": "powershell Get-Process"}')]),
            ]),
            _msg_final(content="Ação negada pela política de segurança: shell arbitrário não é permitido."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, execute powershell get process"])
        voz_mock = _FakeVoz()

        with patch.object(ferramentas.subprocess, "run", side_effect=lambda *a, **k: executou_cmd.append(a)), \
             patch.object(seguranca, "pedir_confirmacao", side_effect=AssertionError("DENY não deve pedir confirmação")):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(executou_cmd, [])
        mensagens_turno2 = cliente.requisicoes[1]["messages"]
        tool_msgs = [m for m in mensagens_turno2 if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn("AÇÃO NEGADA", tool_msgs[0]["content"])
        self.assertIn(
            ("assistant", "Ação negada pela política de segurança: shell arbitrário não é permitido.", "voz"),
            publicados,
        )

    # 6. Falha / timeout / argumentos inválidos / falha pós-ferramenta
    def test_6a_falha_ou_timeout_na_ferramenta_informa_erro_claramente(self):
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_timeout", name="clima", arguments='{"cidade": "Curitiba"}')]),
            ]),
            _msg_final(content="Não consegui consultar o clima agora porque a conexão expirou."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, clima em Curitiba"])
        voz_mock = _FakeVoz()

        with patch.object(ferramentas.requests, "get", side_effect=TimeoutError()):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        mensagens_turno2 = cliente.requisicoes[1]["messages"]
        tool_msgs = [m for m in mensagens_turno2 if m.get("role") == "tool"]
        self.assertEqual(tool_msgs[0]["content"], "Erro ao executar clima: TimeoutError")
        self.assertEqual(
            [t for t, _ in voz_mock.falas_diretas],
            ["Não consegui consultar o clima agora porque a conexão expirou."],
        )
        self.assertIn(
            ("assistant", "Não consegui consultar o clima agora porque a conexão expirou.", "voz"),
            publicados,
        )

    def test_6b_json_invalido_em_tool_call_nao_executa_com_padroes(self):
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_badjson", name="clima", arguments='{"cidade": "Curitiba')]),
            ]),
            _msg_final(content="Desculpe, houve um erro nos parâmetros do comando."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, clima em Curitiba"])
        voz_mock = _FakeVoz()

        with patch.object(ferramentas, "executar", side_effect=AssertionError("Não deveria executar com JSON truncado")):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        # Histórico enviado para turno 2 precisa conter JSON válido em arguments ("{}")
        assistant_msgs = [m for m in cliente.requisicoes[1]["messages"] if m.get("role") == "assistant"]
        self.assertEqual(assistant_msgs[0]["tool_calls"][0]["function"]["arguments"], "{}")
        tool_msgs = [m for m in cliente.requisicoes[1]["messages"] if m.get("role") == "tool"]
        self.assertIn("Argumentos inválidos", tool_msgs[0]["content"])
        self.assertIn(("assistant", "Desculpe, houve um erro nos parâmetros do comando.", "voz"), publicados)

    def test_6c_falha_no_llm_apos_ferramenta_devolve_resumo_do_resultado(self):
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_clima", name="clima", arguments='{"cidade": "Recife"}')]),
            ]),
            RuntimeError("Provedor caiu no passo final"),
            RuntimeError("Provedor caiu no passo final"),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, clima em Recife"])
        voz_mock = _FakeVoz()

        with patch.object(ferramentas.requests, "get", side_effect=TimeoutError()):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        # Em vez de esconder a falha atrás de "Sem resposta", informa o erro da ferramenta!
        resposta = publicados[-1][1]
        self.assertIn("Erro ao executar clima: TimeoutError", resposta)
        self.assertEqual(voz_mock.falas_diretas[-1][0], resposta)

    def test_6d_finalizar_idempotente_nao_executa_ferramenta_duas_vezes(self):
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="call_clima", name="clima", arguments='{"cidade": "Manaus"}')]),
            ]),
            _msg_final(content="Manaus está com 30 graus."),
        ])
        with patch.object(cerebro, "_cliente", lambda _p: cliente), \
             patch.object(cerebro.config, "PROVEDORES", ["gemini"]), \
             patch.object(cerebro.config, "CHAVES", {"gemini": "chave-teste"}), \
             patch.object(cerebro.config, "MODELOS", {"gemini": "gemini-2.5-flash"}), \
             patch.object(cerebro.config, "REASONING", ""), \
             patch.object(cerebro, "_system", lambda: "sys"), \
             patch.object(cerebro, "_contexto", lambda _t, _r=None: ""), \
             patch.object(cerebro, "_rastrear"), \
             patch.object(ferramentas, "executar", return_value="Manaus: 30°C") as exec_spy:
            partes, finalizar = cerebro.processar_stream("clima em Manaus", None, "voz")
            self.assertEqual(list(partes), [])
            r1 = finalizar()
            r2 = finalizar()

        self.assertEqual(r1, "Manaus está com 30 graus.")
        self.assertEqual(r2, r1)
        self.assertEqual(exec_spy.call_count, 1)
        # Apenas 1 par (user, assistant) salvo no histórico
        self.assertEqual(len(memoria.historico(10)), 2)

    # 7. Preservação do streaming conversacional e comandos rápidos
    def test_7a_primeira_frase_toca_antes_da_segunda_terminar_mesmo_com_tools(self):
        frase1_tocou = threading.Event()

        def fluxo_lento(_req):
            yield _chunk(content="Primeira frase pronta. ")
            if not frase1_tocou.wait(timeout=2.0):
                raise AssertionError("falar_partes não tocou a 1ª frase antes da 2ª chegar!")
            yield _chunk(content="Segunda frase depois.")

        cliente = _ClienteSequencial([fluxo_lento])
        ouvido = _FakeOuvido(["Ei, Ultron, me conte uma novidade"])
        tocadas = []

        async def fake_sint(texto, arq, *_a):
            Path(arq).write_bytes(b"mp3")

        def fake_tocar(arq):
            tocadas.append(Path(arq).name)
            if len(tocadas) == 1:
                frase1_tocou.set()

        class VozStreamingReal(_FakeVoz):
            def falar_partes(self, partes, eco=0.3):
                with patch.object(voz, "_sintetizar", fake_sint), \
                     patch.object(voz, "_tocar", fake_tocar), \
                     patch.object(voz.time, "sleep", lambda *_a: None):
                    return voz.falar_partes(partes, eco=0)

        voz_mock = VozStreamingReal()
        publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(len(tocadas), 2)
        self.assertTrue(frase1_tocou.is_set())
        self.assertIn(("assistant", "Primeira frase pronta. Segunda frase depois.", "voz"), publicados)

    def test_7b_comandos_rapidos_continuam_sem_chamar_llm(self):
        ouvido = _FakeOuvido(["Ei, Ultron, que horas são?"])
        voz_mock = _FakeVoz()
        cliente = _ClienteSequencial([])  # explode se qualquer chamada LLM acontecer

        publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(cliente.requisicoes, [])
        self.assertTrue(any("São " in f for f in voz_mock.todas_falas))
        self.assertTrue(any(p == "assistant" and "São " in t for p, t, _ in publicados))

    def test_7c_push_to_talk_erro_na_resposta_nao_reinicia_microfone(self):
        ouvido = _FakeOuvido([], manual=["qual o clima"])
        voz_mock = _FakeVoz()
        parar = threading.Event()
        estados = []

        def broken_falar(_texto, eco=0.5, emocao=registro.NEUTRO):
            raise RuntimeError("falha de saída de áudio")

        voz_mock.falar = broken_falar
        cliente = _ClienteSequencial([
            iter([_chunk(tool_calls=[_tc_delta(index=0, tc_id="c1", name="info_sistema", arguments="{}")])]),
            _msg_final(content="CPU em 10%."),
        ])

        def registrar_atalho(evento):
            evento.set()

        def estado(nome, erro=None):
            estados.append((nome, erro))
            if nome == "ouvindo" and len([e for e in estados if e[0] == "processando"]) >= 1:
                parar.set()

        fake_psutil = types.SimpleNamespace(
            cpu_percent=lambda interval=0.5: 10,
            virtual_memory=lambda: types.SimpleNamespace(percent=30),
            sensors_battery=lambda: None,
        )
        with patch.dict(sys.modules, {"voz": types.SimpleNamespace(
            Ouvido=lambda **_k: ouvido,
            falar=voz_mock.falar,
            falar_partes=voz_mock.falar_partes,
            parar_fala=voz_mock.parar_fala,
            falando=voz_mock.falando,
        ), "psutil": fake_psutil}), \
             patch.object(cerebro, "_cliente", lambda _p: cliente), \
             patch.object(cerebro.config, "PROVEDORES", ["gemini"]), \
             patch.object(cerebro.config, "CHAVES", {"gemini": "chave-teste"}), \
             patch.object(cerebro.config, "MODELOS", {"gemini": "gemini-2.5-flash"}), \
             patch.object(cerebro.config, "REASONING", ""), \
             patch.object(cerebro, "_system", lambda: "sys"), \
             patch.object(cerebro, "_contexto", lambda _t, _r=None: ""), \
             patch.object(cerebro, "_rastrear"), \
             patch.object(main, "atalho_falar", registrar_atalho), \
             patch.object(main.personalidade, "saudacao_ao_abrir", lambda: False), \
             patch.object(main, "_reiniciar_audio") as reiniciar:
            # Garante término após primeira passagem pelo bloco push-to-talk
            orig_escutar = ouvido.escutar_manual

            def manual_uma_vez():
                ouvido.pedido_manual.clear()
                return orig_escutar()

            ouvido.escutar_manual = manual_uma_vez
            # Para no ciclo seguinte via stop_event após _limpar/processar
            orig_conversa = lambda *_a: None
            with patch.object(main.time, "sleep", lambda _s: None):
                def parar_no_segundo(*_a):
                    parar.set()
                    return {"texto": None, "alternativas": [], "erro": None}
                ouvido.escutar_detalhado = parar_no_segundo
                main.modo_voz(
                    bandeja=False,
                    entrada_teclado=False,
                    stop_event=parar,
                    estado_voz=estado,
                    conversa=orig_conversa,
                )

        reiniciar.assert_not_called()

    def test_8a_tool_calls_paralelas_e_mesmo_indice_acumulam_sem_misturar(self):
        cliente = _ClienteSequencial([
            iter([
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="", name="info_sistema", arguments="{}")]),
                _chunk(tool_calls=[_tc_delta(index=0, tc_id="", name="clima", arguments='{"cidade": "Rio"}')]),
            ]),
            _msg_final(content="[[registro:alerta]] Tudo verificado."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, veja o sistema e o clima no Rio"])
        voz_mock = _FakeVoz()

        executadas = []

        def fake_exec(nome, args, confirmar, origem):
            executadas.append((nome, args, origem))
            return "ok"

        with patch.object(ferramentas, "executar", side_effect=fake_exec):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(
            [(n, a) for n, a, _ in executadas],
            [("info_sistema", {}), ("clima", {"cidade": "Rio"})],
        )
        self.assertEqual(voz_mock.falas_diretas, [("Tudo verificado.", "alerta")])
        self.assertIn(("assistant", "Tudo verificado.", "voz"), publicados)

    def test_8b_erro_no_meio_de_tool_call_em_stream_descarta_fragmento_e_usa_loop(self):
        def fluxo_quebrado(_req):
            yield _chunk(tool_calls=[_tc_delta(index=0, tc_id="c_quebrada", name="clima", arguments='{"cidade": "Cu')])
            raise TimeoutError("queda no meio do JSON")

        cliente = _ClienteSequencial([
            fluxo_quebrado,
            _msg_final(tool_calls=[
                types.SimpleNamespace(id="c_limpa", function=types.SimpleNamespace(
                    name="clima", arguments='{"cidade": "Curitiba"}'))
            ]),
            _msg_final(content="Em Curitiba está 20 graus."),
        ])
        ouvido = _FakeOuvido(["Ei, Ultron, clima em Curitiba"])
        voz_mock = _FakeVoz()

        executadas = []

        def fake_exec(nome, args, confirmar, origem):
            executadas.append((nome, args))
            return "Curitiba: agora 20°C"

        with patch.object(ferramentas, "executar", side_effect=fake_exec):
            publicados = self._executar_modo_voz(cliente, ouvido, voz_mock)

        self.assertEqual(executadas, [("clima", {"cidade": "Curitiba"})])
        self.assertEqual(voz_mock.falas_diretas, [("Em Curitiba está 20 graus.", "neutro")])
        self.assertIn(("assistant", "Em Curitiba está 20 graus.", "voz"), publicados)


if __name__ == "__main__":
    unittest.main()
