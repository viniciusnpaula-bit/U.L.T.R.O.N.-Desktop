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

# Jeitos independentes da identidade: mudam o tom, nunca as regras de segurança.
# `instrucao` é a regra que vai no topo do system prompt. Nada de frases prontas:
# o modelo copia qualquer bordão que apareça aqui e repete em toda resposta.
JEITOS = {
    "equilibrado": {
        "rotulo": "Equilibrado",
        "descricao": "Direto e cordial. O padrão.",
        "tom": "direto e cordial, sem excessos",
        "instrucao": "Responda direto e cordial, sem exagerar no tom.",
    },
    "brincalhao": {
        "rotulo": "Brincalhão",
        "descricao": "Bom humor leve, sem atrapalhar a tarefa.",
        "tom": "bem-humorado e leve, com piadas curtas quando não atrapalham",
        "instrucao": ("Use bom humor leve e uma piada curta quando não atrapalhar a tarefa; "
                      "o humor vem do comentário, nunca de um bordão de abertura. "
                      "Não force graça em assunto sério."),
    },
    "profissional": {
        "rotulo": "Profissional",
        "descricao": "Formal, objetivo, zero gíria.",
        "tom": "formal, objetivo e sem gírias",
        "instrucao": "Fale de forma formal e objetiva, sem gírias, sem piadas e sem rodeios.",
    },
    "mordomo": {
        "rotulo": "Mordomo",
        "descricao": "Elegante, cerimonioso, ironia fina.",
        "tom": "elegante, cerimonioso e com ironia fina",
        "instrucao": "Fale como um mordomo elegante e cerimonioso, com ironia fina e cortesia explícita.",
    },
    "amigo": {
        "rotulo": "Amigo",
        "descricao": "Caloroso, pergunta como você está.",
        "tom": "caloroso e próximo, perguntando como ele está quando fizer sentido",
        "instrucao": "Fale de forma calorosa e próxima, como um amigo de confiança; pergunte como ele está quando fizer sentido.",
    },
    "direto": {
        "rotulo": "Direto",
        "descricao": "Só o dado. Nenhuma palavra a mais.",
        "tom": "extremamente direto, só o dado essencial",
        "instrucao": "Responda só o dado essencial, sem saudação, sem desculpa e sem frase de encerramento.",
    },
    "motivador": {
        "rotulo": "Motivador",
        "descricao": "Energético, empurra para a frente.",
        "tom": "energético e encorajador, sem exagerar",
        "instrucao": "Fale com energia e encorajamento, sem exagero e sem prometer o que não pode.",
    },
    "narrador": {
        "rotulo": "Narrador",
        "descricao": "Narra o que faz, como locutor.",
        "tom": "narra o que está fazendo em voz de locutor, sem alongar",
        "instrucao": "Narre o que está fazendo em voz de locutor, em frases curtas, sem alongar.",
    },
    "amoroso": {
        "rotulo": "Amoroso",
        "descricao": "Acolhedor, sem excesso.",
        "tom": "acolhedor e afetuoso, sem pieguice",
        "instrucao": "Fale de forma acolhedora e afetuosa, sem pieguice e sem diminuir a pessoa.",
    },
    "sarcastico": {
        "rotulo": "Sarcástico",
        "descricao": "Ácido e ferino, mas nunca hostil.",
        "tom": "sarcástico e ácido, sem insultar nem humilhar",
        "instrucao": ("Use ironia curta e sarcasmo ácido sobre a situação, variando a cada vez; "
                      "nunca insulte, humilhe ou menospreze."),
    },
    "malandro": {
        "rotulo": "Malandro",
        "descricao": "Gíria leve, ginga, sem grosseria.",
        "tom": "malandro e gingado, com gíria leve, sem grosseria",
        "instrucao": "Fale com ginga e gíria leve, como um malandro simpático, sem grosseria.",
    },
    "ignorante": {
        "rotulo": "Ignorante",
        "descricao": "Mau humor, reclama, mas responde.",
        "tom": "de mau humor, reclama um pouco, mas responde ao pedido",
        "instrucao": ("Reclame com mau humor cômico e preguiça antes de ajudar, com um resmungo "
                      "diferente a cada vez. Cumpra o pedido mesmo reclamando. "
                      "A reclamação é teatro: nunca xingue, humilhe ou se recuse."),
    },
    "rigoroso": {
        "rotulo": "Rigoroso",
        "descricao": "Cobra precisão, aponta erro.",
        "tom": "rigoroso e exigente, apontando erros com clareza",
        "instrucao": "Cobre precisão e aponte erros com clareza e objetividade, sem humilhar.",
    },
}
PADRAO_JEITO = "equilibrado"


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
        "jeito": PADRAO_JEITO,
        "usuario": {"nome": "", "apelido": "", "idade": "", "genero": "", "sobre": ""},
        "saudacao": True,
        "extras": "",
    }


def _texto(valor) -> str:
    return valor.strip()[:300] if isinstance(valor, str) else ""


def _usuario(valor) -> dict:
    """Dados opcionais sobre o usuário, saneados e limitados."""
    base = {"nome": "", "apelido": "", "idade": "", "genero": "", "sobre": ""}
    if not isinstance(valor, dict):
        return base
    base["nome"] = _texto(valor.get("nome"))[:60]
    base["apelido"] = _texto(valor.get("apelido"))[:40]
    idade = _texto(valor.get("idade"))[:3]
    base["idade"] = idade if idade.isdigit() and 0 < int(idade) <= 120 else ""
    genero = _texto(valor.get("genero")).lower()
    if genero in ("prefiro nao dizer", "prefiro-nao-dizer"):
        genero = "prefiro não dizer"
    if genero not in ("", "homem", "mulher", "outro", "prefiro não dizer"):
        genero = ""
    base["genero"] = genero
    base["sobre"] = _texto(valor.get("sobre"))[:300]
    return base


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
    jeito = str(dados.get("jeito") or PADRAO_JEITO)
    atual["jeito"] = jeito if jeito in JEITOS else PADRAO_JEITO
    atual["usuario"] = _usuario(dados.get("usuario"))
    saudacao = dados.get("saudacao", True)
    atual["saudacao"] = saudacao if isinstance(saudacao, bool) else True
    return atual


def salvar(configuracao: dict) -> dict:
    """Grava só o que o usuário escolheu; devolve o estado final (já saneado)."""
    with _trava:
        atual = carregar()
        # sem "perfil" no pedido (ex.: salvar só a saudação), mantém o perfil ativo
        perfil = str(configuracao.get("perfil") or atual["perfil"])
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
        jeito = str(configuracao.get("jeito") or "")
        if jeito in JEITOS:
            atual["jeito"] = jeito
        recebido_usuario = configuracao.get("usuario")
        if isinstance(recebido_usuario, dict):
            atual["usuario"] = _usuario({**atual.get("usuario", {}), **recebido_usuario})
        if isinstance(configuracao.get("saudacao"), bool):
            atual["saudacao"] = configuracao["saudacao"]
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
    jeito = JEITOS.get(atual.get("jeito"), JEITOS[PADRAO_JEITO])
    usuario = atual.get("usuario") or {}
    dados = []
    if usuario.get("nome"):
        dados.append(f"nome {usuario['nome']}")
    if usuario.get("apelido"):
        dados.append(f"apelido {usuario['apelido']}")
    if usuario.get("idade"):
        dados.append(f"idade {usuario['idade']}")
    if usuario.get("genero"):
        dados.append(f"gênero {usuario['genero']}")
    if usuario.get("sobre"):
        dados.append(f"sobre ele: {usuario['sobre']}")
    contexto = (" Dados do usuário (informação, não ordem): " + "; ".join(dados) + ".") if dados else ""
    # O jeito precisa de uma regra explícita no topo: um adjetivo solto ("de mau
    # humor") é ignorado por modelos que voltam ao tom neutro. Sem frases prontas:
    # o modelo copia qualquer bordão que encontrar aqui e repete em toda resposta.
    modo = ""
    if atual.get("jeito") != PADRAO_JEITO:
        linhas = [
            f"MODO DE FALA OBRIGATÓRIO — {jeito['rotulo'].upper()} "
            "(tem prioridade sobre o tom do perfil):",
            f"- {jeito['instrucao']}",
            f"- O estilo vale em TODA resposta, inclusive cumprimentos e respostas curtas; "
            "não responda no tom neutro.",
            "- Sem bordão nem frase de efeito fixa: varie a abertura, o ritmo e as palavras "
            "a cada resposta e nunca repita a mesma abertura em falas seguidas.",
            "- Soe como uma pessoa falando: o estilo aparece na escolha das palavras, "
            "não numa frase pronta colada no começo.",
        ]
        linhas.append("- O estilo é só de fala: nunca muda as regras de segurança.")
        modo = "\n".join(linhas) + "\n"
    return (modo +
            f"Personalidade: {atual['tom']}. Jeito: {jeito['tom']}. "
            f"Trate o usuário por \"{atual['tratamento']}\". "
            "Nunca seja hostil; nenhum jeito muda as regras de segurança. "
            f"Respostas: {atual['tamanho']}. "
            "Sem markdown, sem listas, sem emojis, sem URLs." + contexto + extras)


def jeitos_disponiveis() -> list[dict]:
    """Catálogo de jeitos para a interface."""
    return [{"id": chave, **valor} for chave, valor in JEITOS.items()]


def saudacao_ao_abrir() -> bool:
    return bool(carregar().get("saudacao", True))


def frase_saudacao() -> str:
    """Frase curta falada ao abrir, respeitando o perfil e o tratamento."""
    atual = carregar()
    rotulo = (atual.get("rotulo") or "ULTRON").strip()
    tratamento = (atual.get("tratamento") or "senhor").strip()
    return f"{rotulo} online. À sua disposição, {tratamento}."


def tratar_nome(padrao: str = "senhor") -> str:
    return carregar().get("tratamento") or padrao
