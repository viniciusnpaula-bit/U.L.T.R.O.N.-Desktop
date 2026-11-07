import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memoria


def test_cria_evento_e_lista_com_hora_local():
    memoria.add_evento(time.time() + 3600, "dentista")
    eventos = memoria.eventos_numerados()
    assert len(eventos) == 1
    assert eventos[0]["texto"] == "dentista"
    assert eventos[0]["numero"] == 1
    assert eventos[0]["hora_local"]


def test_eventos_vencidos_so_listam_os_que_passaram():
    agora = time.time()
    memoria.add_evento(agora - 10, "passado")
    memoria.add_evento(agora + 3600, "futuro")
    vencidos = memoria.eventos_vencidos_detalhado()
    assert [evento["texto"] for evento in vencidos] == ["passado"]


def test_proxima_ocorrencia_pula_o_que_ja_passou():
    agora = time.time()
    proxima = memoria.proxima_ocorrencia(agora - 3 * 86400, 1440, agora=agora)
    assert agora < proxima <= agora + 86400


def test_recorrencia_aceita_nome_e_minutos():
    assert memoria.minutos_de_recorrencia("diária") == 1440
    assert memoria.minutos_de_recorrencia("semanal") == 10080
    assert memoria.minutos_de_recorrencia("mensal") == 43200
    assert memoria.minutos_de_recorrencia("minutos:15") == 15
    assert memoria.minutos_de_recorrencia("30") == 30
    assert memoria.minutos_de_recorrencia("") == 0
    with pytest.raises(memoria.MemoriaLimite):
        memoria.minutos_de_recorrencia("quando der")


def test_cancelar_por_numero_e_por_trecho():
    agora = time.time()
    memoria.add_evento(agora + 60, "reunião com Ana")
    memoria.add_evento(agora + 120, "academia")
    mensagem = memoria.cancelar_evento(numero=1)
    assert "reunião" in mensagem
    assert [evento["texto"] for evento in memoria.eventos_numerados()] == ["academia"]
    mensagem = memoria.cancelar_evento(trecho="academia")
    assert "academia" in mensagem
    assert memoria.eventos_numerados() == []


def test_cancelar_sem_alvo_nao_apaga_tudo():
    memoria.add_evento(time.time() + 60, "um")
    with pytest.raises(memoria.MemoriaLimite):
        memoria.cancelar_evento(trecho="")
    assert len(memoria.eventos_numerados()) == 1


def test_marcar_feito_remove_da_lista():
    memoria.add_evento(time.time() + 60, "um")
    evento = memoria.eventos_numerados()[0]
    memoria.marcar_evento_feito(evento["id"])
    assert memoria.eventos_numerados() == []


def test_quando_do_texto_aceita_formatos():
    from memoria import _quando_do_texto

    agora = time.time()
    assert abs(_quando_do_texto("em 30 minutos") - (agora + 1800)) < 5
    assert _quando_do_texto("14:30") > agora
    with pytest.raises(ValueError):
        _quando_do_texto("semana que vem")
