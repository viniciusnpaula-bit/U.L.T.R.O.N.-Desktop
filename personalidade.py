"""Personalidade do ULTRON: perfis prontos + ajustes do usuário, persistentes.

Guardado em `dados/personalidade.json` (nunca em `.env`, nunca versionado).
Tudo tem padrão: se o arquivo sumir ou ficar inválido, o ULTRON volta ao perfil
"ultron" sem quebrar. O `cerebro._system()` lê este módulo em cada resposta.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARQUIVO = RAIZ / "dados" / "personalidade.json"
_trava = threading.Lock()

# Perfis prontos. Nenhum muda as regras de segurança: elas são fixas no system prompt.
PERFIS = {
    "ultron": {
        "rotulo": "U.L.T.R.O.N.",
        "tom": "inteligente, direto, leal, humor seco e confiante",
        "tratamento": "senhor",
        "tamanho": "curtas (1 a 3 frases), pensadas para serem faladas",
    },
    "jarvis": {
        "rotulo": "JARVIS",
        "tom": "formal, elegante e prestativo, com uma ponta de ironia britânica",
        "tratamento": "senhor",
        "tamanho": "curtas (1 a 3 frases), com cortesia explícita",
    },
    "visao": {
        "rotulo": "VISÃO",
        "tom": "caloroso, paciente e curioso, sem pressa",
        "tratamento": "senhor",
        "tamanho": "médias (2 a 4 frases), explicando o porquê quando ajuda",
    },
    "edith": {
        "rotulo": "EDITH",
        "tom": "tático, objetivo e econômico, foco em resultado",
        "tratamento": "senhor",
        "tamanho": "bem curtas (1 a 2 frases), sem rodeios",
    },
}
PADRAO = "ultron"


def _caminho() -> Path:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    return ARQUIVO


def _padrao() -> dict:
    base = dict(PERFIS[PADRAO])
    tratamentos = {chave: perfil["tratamento"] for chave, perfil in PERFIS.items()}
    return {
        "perfil": PADRAO,
        **base,
        "tratamento": base["tratamento"],
        # cada perfil guarda o próprio tratamento: trocar de perfil não
        # sobrescreve o jeito de tratar que você escolheu para outro
        "tratamentos": tratamentos,
        "extras": "",
    }


def _texto(valor) -> str:
    return valor.strip()[:300] if isinstance(valor, str) else ""


def carregar() -> dict:
    """Configuração atual, com valores padrão para o que faltar ou estiver inválido."""
    try:
        dados = json.loads(_caminho().read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("formato inválido")
    except (OSError, ValueError):
        return _padrao()
    atual = _padrao()
    perfil = str(dados.get("perfil") or PADRAO)
    if perfil not in PERFIS:
        perfil = PADRAO
    atual.update(PERFIS[perfil])
    atual["perfil"] = perfil

    guardados = dados.get("tratamentos")
    if isinstance(guardados, dict):
        for chave, valor in guardados.items():
            if chave in PERFIS and _texto(valor):
                atual["tratamentos"][chave] = _texto(valor)
    # arquivo antigo tinha um único tratamento: ele pertence ao perfil ativo
    legado = _texto(dados.get("tratamento"))
    if legado and not (isinstance(guardados, dict) and _texto(guardados.get(perfil))):
        atual["tratamentos"][perfil] = legado
    atual["tratamento"] = atual["tratamentos"][perfil]

    for chave in ("ton", "tamanho", "extras"):
        valor = _texto(dados.get(chave))
        if valor:
            atual[chave] = valor
    return atual


def salvar(configuracao: dict) -> dict:
    """Grava só o que o usuário escolheu; devolve o estado final (já saneado)."""
    with _trava:
        atual = carregar()
        perfil = str(configuracao.get("perfil") or PADRAO)
        if perfil in PERFIS:
            atual.update(PERFIS[perfil])
            atual["perfil"] = perfil
        recebidos = configuracao.get("tratamentos")
        if isinstance(recebidos, dict):
            for chave, valor in recebidos.items():
                if chave in PERFIS and _texto(valor):
                    atual["tratamentos"][chave] = _texto(valor)
        tratamento = _texto(configuracao.get("tratamento"))
        if tratamento:
            atual["tratamentos"][atual["perfil"]] = tratamento
        atual["tratamento"] = atual["tratamentos"][atual["perfil"]]
        for chave in ("ton", "tamanho", "extras"):
            valor = _texto(configuracao.get(chave))
            if valor:
                atual[chave] = valor
        atual["atualizado_em"] = time.time()
        _caminho().write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
        return atual


def restaurar_padrao() -> dict:
    with _trava:
        try:
            _caminho().unlink()
        except FileNotFoundError:
            pass
    return carregar()


def perfis_disponiveis() -> list[dict]:
    """Cada perfil com o tratamento que ele guarda (não o do perfil ativo)."""
    atual = carregar()
    tratamentos = atual.get("tratamentos") or {}
    return [
        {"id": chave, **valor, "tratamento": tratamentos.get(chave, valor["tratamento"])}
        for chave, valor in PERFIS.items()
    ]


def frase_do_sistema() -> str:
    """Trecho do system prompt derivado da personalidade escolhida."""
    atual = carregar()
    extras = f" {atual['extras']}" if atual.get("extras") else ""
    return (f"Personalidade: {atual['tom']}. Trate o usuário por \"{atual['tratamento']}\". "
            f"Nunca seja hostil. Respostas: {atual['tamanho']}. "
            "Sem markdown, sem listas, sem emojis, sem URLs." + extras)


def tratar_nome(padrao: str = "senhor") -> str:
    return carregar().get("tratamento") or padrao
