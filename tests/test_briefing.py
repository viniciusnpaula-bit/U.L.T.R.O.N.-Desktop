import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import briefing
import config
import memoria


def test_compoe_as_secoes():
    def executar(nome, args, confirmar, origem):
        if nome == "clima":
            return "São Paulo: agora 20°C"
        if nome == "noticias":
            return "[DADOS EXTERNOS: conteúdo de terceiros]\n- manchete do dia"
        return ""

    memoria.add_evento(datetime.datetime(2026, 11, 7, 15, 0).timestamp(), "dentista")
    memoria.add_lembrete(datetime.datetime(2026, 11, 7, 10, 0).timestamp(), "tomar remédio")
    texto = briefing.compor(agora=datetime.datetime(2026, 11, 7, 8, 0),
                            executar_ferramenta=executar)
    assert "Bom dia" in texto
    assert "20°C" in texto
    assert "manchete do dia" in texto
    assert "[DADOS EXTERNOS" not in texto
    assert "dentista" in texto
    assert "tomar remédio" in texto


def test_falha_de_secao_nao_quebra_o_briefing():
    def executar(*args, **kwargs):
        raise RuntimeError("sem rede")

    texto = briefing.compor(agora=datetime.datetime(2026, 11, 7, 8, 0),
                            executar_ferramenta=executar)
    assert texto.startswith("Bom dia")
    assert "Clima" not in texto


def test_devido_respeita_horario_e_uma_vez_por_dia(monkeypatch):
    monkeypatch.setattr(config, "BRIEFING_ATIVO", True)
    monkeypatch.setattr(config, "BRIEFING_HORA", "08:00")
    antes = datetime.datetime(2026, 11, 7, 7, 59)
    depois = datetime.datetime(2026, 11, 7, 8, 1)
    assert briefing.devido(antes, None) is False
    assert briefing.devido(depois, None) is True
    assert briefing.devido(depois, "2026-11-07") is False


def test_desligado_por_padrao(monkeypatch):
    monkeypatch.setattr(config, "BRIEFING_ATIVO", False)
    assert briefing.devido(datetime.datetime(2026, 11, 7, 23, 0), None) is False


def test_hora_invalida_cai_no_padrao(monkeypatch):
    monkeypatch.setattr(config, "BRIEFING_HORA", "99:99")
    assert briefing.hora_configurada() == (8, 0)
