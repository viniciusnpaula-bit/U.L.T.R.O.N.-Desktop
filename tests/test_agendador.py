import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agendador
import config
import fluxos
import memoria
import sessao


def _agendador(avisos, executar=None):
    return agendador.Agendador(notificar=avisos.append,
                               executar_ferramenta=executar or (lambda *a: "ok"))


def test_tick_dispara_lembrete_e_marca_feito():
    memoria.add_lembrete(time.time() - 1, "beber água")
    avisos = []
    _agendador(avisos).tick()
    assert any("beber água" in aviso for aviso in avisos)
    assert memoria.lembretes_numerados() == []


def test_tick_reagenda_lembrete_repetido():
    memoria.add_lembrete(time.time() - 1, "alongar", repetir_minutos=60)
    _agendador([]).tick()
    pendentes = memoria.lembretes_numerados()
    assert len(pendentes) == 1
    assert pendentes[0]["quando"] > time.time() + 50 * 60


def test_evento_simples_avisa_e_marca_feito():
    memoria.add_evento(time.time() - 1, "reunião")
    avisos = []
    _agendador(avisos).tick()
    assert any("reunião" in aviso for aviso in avisos)
    assert memoria.eventos_numerados() == []


def test_fluxo_agendado_roda_pelo_portao_e_nega_confirmacao(tmp_path, monkeypatch):
    monkeypatch.setattr(fluxos, "ARQUIVO_USUARIO", tmp_path / "fluxos.json")
    fluxos.criar("estudo", "Estudo", "", [
        {"ferramenta": "minimizar_janelas", "rotulo": "minimizar"}])
    monkeypatch.setattr(sessao, "estado", lambda: {"desbloqueada": True})
    chamadas = []

    def executar(nome, args, confirmar, origem):
        chamadas.append((nome, confirmar(None)))
        return "ok"

    memoria.add_evento(time.time() - 1, "Estudo", fluxo_id="estudo")
    avisos = []
    _agendador(avisos, executar).tick()
    assert chamadas == [("minimizar_janelas", False)]
    assert any("concluído" in aviso for aviso in avisos)


def test_fluxo_agendado_nao_roda_com_sessao_bloqueada(tmp_path, monkeypatch):
    monkeypatch.setattr(fluxos, "ARQUIVO_USUARIO", tmp_path / "fluxos.json")
    fluxos.criar("estudo", "Estudo", "", [
        {"ferramenta": "minimizar_janelas", "rotulo": "minimizar"}])
    monkeypatch.setattr(sessao, "estado", lambda: {"desbloqueada": False})
    chamadas = []
    memoria.add_evento(time.time() - 1, "Estudo", fluxo_id="estudo")
    avisos = []
    _agendador(avisos, lambda *a: chamadas.append(a)).tick()
    assert chamadas == []
    assert any("bloqueada" in aviso for aviso in avisos)


def test_briefing_dispara_uma_vez_por_dia(monkeypatch):
    monkeypatch.setattr(config, "BRIEFING_ATIVO", True)
    monkeypatch.setattr(config, "BRIEFING_HORA", "08:00")
    avisos = []
    ag = _agendador(avisos)
    momento = datetime.datetime(2026, 11, 7, 9, 0).timestamp()
    ag.tick(momento)
    ag.tick(momento + 60)
    assert sum("Bom dia" in aviso for aviso in avisos) == 1
