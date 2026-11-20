"""Testes para gestão de diálogos prolongados, agenda/lembretes naturais e aprendizado contínuo."""
import datetime
import time
from unittest import mock

import aprendizado
import autoconhecimento
import cerebro
import ferramentas
import memoria


def test_compactar_historico_preserva_recentes_e_truncada_antigas():
    msgs = [
        {"role": "user", "content": "Pergunta antiga 1 sobre Python"},
        {"role": "assistant", "content": "Resposta longa " + ("detalhe " * 80)},
        {"role": "user", "content": "Pergunta antiga 2 sobre agenda"},
        {"role": "assistant", "content": "Outra resposta muito extensa " + ("conteudo " * 80)},
    ] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Turno recente {i} " + ("ok " * 60)}
        for i in range(6)
    ]

    compactadas = memoria.compactar_historico(msgs, manter_integros=6, max_chars_antigo=120)

    assert len(compactadas) == len(msgs)
    assert compactadas[0]["content"] == "Pergunta antiga 1 sobre Python"
    assert len(compactadas[1]["content"]) <= 125
    assert compactadas[1]["content"].endswith("…")
    assert compactadas[3]["content"].endswith("…")
    # Últimas 6 preservadas integralmente
    assert compactadas[-6:] == msgs[-6:]

    fio = memoria.resumo_fio_conversa(msgs, manter_integros=6)
    assert "Fio do diálogo prolongado" in fio
    assert "Pergunta antiga 1 sobre Python" in fio
    assert "Pergunta antiga 2 sobre agenda" in fio


def test_bloco_contexto_amplia_continuacao_curta_com_turnos_recentes():
    chamadas = []

    def fake_recordar(consulta, **_kwargs):
        chamadas.append(consulta)
        return [{"ts": time.time() - 86400, "papel": "user", "texto": "reunião do projeto amanhã às 10h", "score": 4.0}]

    recentes = [
        {"role": "user", "content": "como ficou o cronograma da reunião do projeto?"},
        {"role": "assistant", "content": "Marcamos a revisão principal."},
    ]
    with mock.patch.object(memoria, "recordar", side_effect=fake_recordar):
        bloco = memoria.bloco_contexto("e amanhã?", recentes=recentes)

    assert len(chamadas) == 1
    assert "cronograma" in chamadas[0]
    assert "reunião do projeto" in bloco


def test_quando_do_texto_natural_ptbr_e_criar_lembrete():
    agora = time.time()
    assert abs(memoria._quando_do_texto("daqui a meia hora") - (agora + 1800)) < 5
    assert abs(memoria._quando_do_texto("em 1h30") - (agora + 5400)) < 5
    assert abs(memoria._quando_do_texto("daqui a 2 dias") - (agora + 2 * 86400)) < 5

    hoje_dt = datetime.datetime.now()
    amanha_ts = memoria._quando_do_texto("amanhã às 9h")
    amanha_dt = datetime.datetime.fromtimestamp(amanha_ts)
    esperado_amanha = (hoje_dt + datetime.timedelta(days=1)).date()
    assert amanha_dt.date() == esperado_amanha
    assert (amanha_dt.hour, amanha_dt.minute) == (9, 0)

    depois_dt = datetime.datetime.fromtimestamp(memoria._quando_do_texto("depois de amanhã às 14:30"))
    assert depois_dt.date() == (hoje_dt + datetime.timedelta(days=2)).date()
    assert (depois_dt.hour, depois_dt.minute) == (14, 30)

    sexta_ts = memoria._quando_do_texto("sexta-feira às 16h")
    sexta_dt = datetime.datetime.fromtimestamp(sexta_ts)
    assert sexta_dt.weekday() == 4
    assert sexta_dt.timestamp() > agora
    assert (sexta_dt.hour, sexta_dt.minute) == (16, 0)

    confirmar = lambda *_: True
    with mock.patch.object(memoria, "add_lembrete") as mk_add:
        r_min = ferramentas.executar("criar_lembrete", {"texto": "Água", "minutos": 15}, confirmar, "desktop")
        r_nat = ferramentas.executar(
            "criar_lembrete",
            {"texto": "Revisar PR", "quando": "amanhã às 10h", "repetir": "diaria"},
            confirmar,
            "desktop",
        )

    assert r_min == "Lembrete criado para daqui a 15 minutos."
    assert "Lembrete criado para " in r_nat and "repetindo a cada 1440 minutos" in r_nat
    assert mk_add.call_count == 2


def test_aprendizado_continuo_extrai_persiste_substitui_estilo_e_injeta_contexto():
    estado_fatos = []

    def fake_salvar(texto):
        if texto not in estado_fatos:
            estado_fatos.append(texto)

    def fake_apagar(trecho):
        antes = len(estado_fatos)
        alvo = trecho.casefold()
        estado_fatos[:] = [f for f in estado_fatos if alvo not in f.casefold()]
        return antes - len(estado_fatos)

    with mock.patch.object(memoria, "salvar_fato", side_effect=fake_salvar), \
            mock.patch.object(memoria, "apagar_fato", side_effect=fake_apagar), \
            mock.patch.object(memoria, "listar_fatos", side_effect=lambda: list(estado_fatos)):
        s1 = aprendizado.observar_interacao("Prefiro respostas curtas e diretas, sem enrolação.")
        assert any("curta, direta e objetiva" in x for x in s1)

        s2 = aprendizado.observar_interacao("Quando eu falar modo foco faça fechar jogos.")
        s3 = aprendizado.observar_interacao("Sempre uso o Spotify.")
        assert any("regra:" in x and "modo foco" in x for x in s2)
        assert any("hábito:" in x and "Spotify" in x for x in s3)

        # Novo estilo substitui o estilo anterior conflitante
        aprendizado.observar_interacao("Agora prefiro respostas detalhadas e passo a passo.")
        estilos = [f for f in estado_fatos if f.startswith("[aprendizado] estilo:")]
        assert len(estilos) == 1
        assert "detalhada" in estilos[0]

        bloco = aprendizado.bloco_adaptativo()
        assert "Aprendizado contínuo" in bloco
        assert "Spotify" in bloco
        assert "modo foco" in bloco

        with mock.patch.object(memoria, "bloco_contexto", return_value=""), \
                mock.patch.object(memoria, "bloco_compromissos_proximos", return_value=""), \
                mock.patch.object(cerebro.obsidian, "contexto", return_value=""):
            ctx = cerebro._contexto("olá")
        assert "Aprendizado contínuo" in ctx


def test_autoconhecimento_menciona_inteligencia_continua():
    autoconhecimento._CACHE.update(ts=0.0, texto="")
    texto = autoconhecimento.bloco(forcar=True)
    assert "Inteligência contínua:" in texto
