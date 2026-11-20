"""Aprendizado contínuo local: extrai preferências, hábitos e regras do usuário e adapta o contexto."""
from __future__ import annotations

import re
import unicodedata

import memoria

PREFIXO = "[aprendizado] "
_ESTILO_PREFIXO = "[aprendizado] estilo:"


def _normalizar_ascii(texto: str) -> str:
    bruto = unicodedata.normalize("NFD", str(texto or "").strip().lower())
    return "".join(c for c in bruto if unicodedata.category(c) != "Mn")


def _limpar_trecho(valor: str, limite: int = 80) -> str:
    return " ".join(str(valor or "").split()).strip(" .,:;!?\"'")[:limite]


def extrair_aprendizados(texto_usuario: str) -> list[str]:
    """Detecta sinais duradouros de adaptação (estilo, regras explícitas, hábitos e apps favoritos)."""
    bruto = " ".join(str(texto_usuario or "").split())
    if not bruto:
        return []
    eh_pergunta = bruto.endswith("?")
    norm = _normalizar_ascii(bruto)

    achados: list[str] = []

    # 1. Estilo de resposta (permite atualização mesmo em perguntas como "pode ser mais curto?")
    if re.search(
        r"\b(?:prefiro|quero|seja|responda|mantenha)\b.*\b(?:curt[oa]s?|diret[oa]s?|objetiv[oa]s?|breves?)\b"
        r"|\bsem enrola(?:cao|coes)\b",
        norm,
    ):
        achados.append(f"{PREFIXO}estilo: responder de forma curta, direta e objetiva")
    elif re.search(
        r"\b(?:prefiro|quero|seja|responda)\b.*\b(?:detalhad[oa]s?|complet[oa]s?|passo a passo|aprofundad[oa]s?)\b",
        norm,
    ):
        achados.append(f"{PREFIXO}estilo: responder de forma detalhada e passo a passo")

    # 2. Regras explícitas ("quando eu falar X significa/use/faça Y")
    for m in re.finditer(
        r"\bquando eu (?:falar|disser|pedir)\s+(.{2,60}?)\s+(?:significa|quero dizer|use|abra|fa[cç]a)\s+([^.?!;\n]{2,80})",
        bruto,
        flags=re.IGNORECASE,
    ):
        gatilho = _limpar_trecho(m.group(1), 50)
        acao = _limpar_trecho(m.group(2), 70)
        if gatilho and acao:
            achados.append(f"{PREFIXO}regra: quando pedir '{gatilho}', interpretar como '{acao}'")

    if not eh_pergunta:
        # 3. Hábitos duradouros ("sempre uso / costumo usar / ouvir / jogar ...")
        for m in re.finditer(
            r"\b(?:sempre|costumo)\s+(?:uso|usar|abrir|ouvir|jogar)\s+(?:o |a |os |as |no |na )?"
            r"([a-zA-Z0-9À-ÿ _-]{2,40})",
            bruto,
            flags=re.IGNORECASE,
        ):
            alvo = _limpar_trecho(m.group(1), 40)
            if alvo and not any(v in alvo.lower() for v in ("que ", "quando ", "como ")):
                achados.append(f"{PREFIXO}hábito: costuma usar {alvo}")

        # 4. Aplicativo padrão / favorito
        for m in re.finditer(
            r"\bmeu\s+(?:navegador|editor|player|aplicativo|app)\s+"
            r"(?:padrao|padrão|favorito|preferido)\s+(?:e|é)\s+(?:o |a )?([a-zA-Z0-9À-ÿ _-]{2,40})",
            bruto,
            flags=re.IGNORECASE,
        ):
            alvo = _limpar_trecho(m.group(1), 40)
            if alvo:
                achados.append(f"{PREFIXO}preferência: app padrão/favorito — {alvo}")

    # Deduplica mantendo a ordem e respeitando o limite de tamanho da memória.
    maximo = int(getattr(memoria, "_limites", lambda: (300, 50, 3))()[0])
    vistos: set[str] = set()
    saida: list[str] = []
    for item in achados:
        limpo = item[:maximo].strip()
        if limpo and limpo not in vistos:
            vistos.add(limpo)
            saida.append(limpo)
    return saida


def observar_interacao(texto_usuario: str, resposta_assistente: str = "") -> list[str]:
    """Extrai e persiste aprendizados duradouros desta interação sem nunca falhar o turno."""
    _ = resposta_assistente  # reservado para futuras heurísticas pós-resposta
    try:
        novos = extrair_aprendizados(texto_usuario)
        if not novos:
            return []
        salvos: list[str] = []
        for item in novos:
            if item.startswith(_ESTILO_PREFIXO):
                try:
                    memoria.apagar_fato(_ESTILO_PREFIXO)
                except Exception:
                    pass
            try:
                memoria.salvar_fato(item)
                salvos.append(item)
            except Exception:
                continue
        return salvos
    except Exception:
        return []


def listar_aprendizados() -> list[str]:
    """Devolve todos os padrões de aprendizado armazenados na memória cifrada."""
    try:
        return [f for f in memoria.listar_fatos() if isinstance(f, str) and f.startswith(PREFIXO)]
    except Exception:
        return []


def bloco_adaptativo() -> str:
    """Bloco curto para o prompt de sistema com os padrões aprendidos com o usuário."""
    itens = listar_aprendizados()
    if not itens:
        return ""
    linhas = [f"- {item[len(PREFIXO):]}" for item in itens[-8:]]
    return (
        "\n\nAprendizado contínuo (adapte suas respostas a estes padrões aprendidos com o usuário):"
        "\n" + "\n".join(linhas)
    )
