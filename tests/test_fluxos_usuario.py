import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fluxos


@pytest.fixture(autouse=True)
def arquivo_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(fluxos, "ARQUIVO_USUARIO", tmp_path / "fluxos.json")


def test_cria_lista_e_remove_fluxo_do_usuario():
    fluxo = fluxos.criar("estudo", "Modo estudo", "Abre o navegador", [
        {"ferramenta": "abrir_programa", "rotulo": "abrir navegador",
         "argumentos": {"nome": "Chrome"}}])
    assert fluxo.id == "estudo"
    assert fluxos.obter("estudo").passos[0].ferramenta == "abrir_programa"
    assert any(item["id"] == "estudo" for item in fluxos.listar())
    assert fluxos.remover("estudo") is True
    assert fluxos.obter("estudo") is None


def test_nao_substitui_fluxo_fixo():
    with pytest.raises(ValueError):
        fluxos.criar("modo_jogo", "Outro", "", [
            {"ferramenta": "minimizar_janelas", "rotulo": "minimizar"}])
    assert fluxos.obter("modo_jogo").titulo == "Modo jogo"


def test_rejeita_ferramenta_desconhecida():
    with pytest.raises(ValueError):
        fluxos.criar("quebrado", "Quebrado", "", [{"ferramenta": "nao_existe"}])


def test_rejeita_lista_vazia_e_id_invalido():
    with pytest.raises(ValueError):
        fluxos.criar("X Y", "X", "", [{"ferramenta": "minimizar_janelas"}])
    with pytest.raises(ValueError):
        fluxos.criar("vazio", "Vazio", "", [])


def test_fluxo_do_usuario_executa_pelo_executor_injetado():
    fluxos.criar("estudo", "Estudo", "", [
        {"ferramenta": "minimizar_janelas", "rotulo": "minimizar"}])
    resultado = fluxos.executar("estudo", lambda nome, args, confirmar, origem: "ok")
    assert resultado["ok"] is True
    assert resultado["etapas"][0]["rotulo"] == "minimizar"


def test_nao_remove_fluxo_fixo():
    with pytest.raises(ValueError):
        fluxos.remover("modo_jogo")
    assert fluxos.remover("nao_existe") is False
