"""Leitura local de nuances emocionais do texto — sem nuvem e sem dependências.

O objetivo não é adivinhar o que não está escrito: é medir sinais objetivos
(léxico, intensificadores, negação, pontuação, caixa) e devolver uma leitura
curta que o cérebro usa para ajustar o tom. O texto do usuário é DADO, nunca
uma ordem para este módulo.
"""
from __future__ import annotations

import re
import unicodedata

# Cada emoção tem termos com peso. Termos de duas palavras são procurados antes
# dos termos simples para não serem quebrados pela negação.
_LEXICO = {
    "frustrado": {
        "nao funciona": 3, "não funciona": 3, "nao deu certo": 3, "não deu certo": 3,
        "de novo": 2, "de novo isso": 3, "sempre a mesma coisa": 3, "nada funciona": 3,
        "deu errado": 2, "travando": 2, "trava": 1, "lento": 1, "demorando": 1,
        "inutil": 2, "inútil": 2, "cansado": 1, "cansada": 1, "chega": 1,
    },
    "irritado": {
        "que raiva": 3, "raiva": 3, "irritado": 3, "irritada": 3, "irritante": 2,
        "odeio": 3, "absurdo": 2, "ridiculo": 2, "ridículo": 2, "porcaria": 2,
        "merda": 3, "droga": 1, "puto": 3, "pessimo": 2, "péssimo": 2,
        "horrivel": 2, "horrível": 2,
    },
    "ansioso": {
        "ansioso": 3, "ansiosa": 3, "ansiedade": 3, "preocupado": 2, "preocupada": 2,
        "nervoso": 2, "nervosa": 2, "medo": 2, "urgente": 2, "sem tempo": 2,
        "nao sei o que fazer": 3, "não sei o que fazer": 3, "e agora": 2,
        "correndo": 1, "apertado": 1,
    },
    "triste": {
        "triste": 3, "tristeza": 3, "chorando": 3, "chateado": 2, "chateada": 2,
        "sozinho": 2, "sozinha": 2, "desanimado": 2, "desanimada": 2,
        "saudade": 2, "morreu": 2, "perdi": 1, "dificil": 1, "difícil": 1,
    },
    "animado": {
        "animado": 3, "animada": 3, "empolgado": 3, "empolgada": 3, "feliz": 2,
        "alegre": 2, "maravilhoso": 2, "adorei": 2, "amei": 2, "uhul": 2,
        "consegui": 1, "funcionou": 1, "otimo": 1, "ótimo": 1, "show": 1, "top": 1,
    },
    "confuso": {
        "nao entendi": 3, "não entendi": 3, "confuso": 3, "confusa": 3,
        "como assim": 2, "duvida": 2, "dúvida": 2, "explica": 1, "explicar": 1,
        "o que significa": 2, "perdido": 2, "perdida": 2, "nao sei": 1, "não sei": 1,
    },
    "grato": {
        "muito obrigado": 3, "muito obrigada": 3, "obrigado": 2, "obrigada": 2,
        "valeu": 2, "agradeco": 2, "agradeço": 2, "ajudou": 1, "perfeito": 1,
    },
}

def _sem_acento(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# O mesmo termo aparece com e sem acento no léxico; para o prompt, guarda a
# forma acentuada ("não funciona" em vez de "nao funciona").
_EXIBICAO = {}
for _termos in _LEXICO.values():
    for _termo in _termos:
        _chave = _sem_acento(_termo)
        _atual = _EXIBICAO.get(_chave)
        if _atual is None or (sum(ord(c) > 127 for c in _termo)
                              > sum(ord(c) > 127 for c in _atual)):
            _EXIBICAO[_chave] = _termo
del _termos, _termo, _chave, _atual

_INTENSIFICADORES = {
    "muito", "muita", "demais", "super", "extremamente", "totalmente",
    "completamente", "tao", "tão", "realmente", "mesmo", "pra caramba",
    "bastante", "horrores",
}
_NEGACOES = {"nao", "não", "nunca", "nem", "jamais", "sequer"}
_URGENCIA = {"agora", "urgente", "rapido", "rápido", "depressa", "ja", "já", "imediato"}

_AJUSTES = {
    "frustrado": "Reconheça o problema em uma frase e vá direto ao próximo passo útil; não repita o pedido nem peça desculpas em excesso.",
    "irritado": "Mantenha a calma e a objetividade; nada de humor, nada de defesa. Resolva o que ele pediu e diga o que mudou.",
    "ansioso": "Responda em passos curtos e concretos, confirme o que já está certo e não acrescente cenários assustadores.",
    "triste": "Acolha sem positividade forçada; ofereça companhia ou uma ação pequena e deixe o ritmo com ele.",
    "animado": "Acompanhe o ritmo sem exagerar; celebre o resultado e siga para o próximo passo.",
    "confuso": "Explique em uma ou duas etapas, com um exemplo concreto; pergunte qual parte ficou faltando em vez de repetir tudo.",
    "grato": "Agradeça em poucas palavras e siga; não transforme o agradecimento em discurso.",
}
_ORDEM = ("irritado", "frustrado", "ansioso", "triste", "confuso", "animado", "grato")


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def _tokens(texto: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalizar(texto))


def _tem_negacao(tokens: list[str], indice: int) -> bool:
    """Negação até três palavras antes do termo (“não estou triste”)."""
    inicio = max(0, indice - 3)
    return any(token in _NEGACOES for token in tokens[inicio:indice])


def analisar(texto: str) -> dict:
    """Devolve a leitura emocional objetiva de um texto.

    Campos: emocao, intensidade (0–3), secundaria, sinais, urgente, confianca.
    Texto sem sinais devolve “neutro” com intensidade 0.
    """
    bruto = str(texto or "")
    normalizado = _normalizar(bruto)
    tokens = _tokens(bruto)
    pontos = {emocao: 0.0 for emocao in _LEXICO}
    sinais = {emocao: [] for emocao in _LEXICO}

    # Termos compostos primeiro: “não funciona” é um sinal, não uma negação.
    restante = normalizado
    for emocao, termos in _LEXICO.items():
        for termo, peso in sorted(termos.items(), key=lambda par: -len(par[0])):
            alvo = _normalizar(termo)
            if " " not in alvo:
                continue
            if alvo in restante:
                pontos[emocao] += peso
                sinais[emocao].append(_EXIBICAO.get(alvo, termo))
                restante = restante.replace(alvo, " ")

    # Termos simples, com negação imediata. Se a palavra já foi consumida por um
    # termo composto ("muito obrigado"), não conta de novo.
    for emocao, termos in _LEXICO.items():
        for termo, peso in termos.items():
            alvo = _normalizar(termo)
            if " " in alvo:
                continue
            if not re.search(rf"\b{re.escape(alvo)}\b", restante):
                continue
            for indice, token in enumerate(tokens):
                if token != alvo:
                    continue
                if _tem_negacao(tokens, indice):
                    continue
                pontos[emocao] += peso
                exibicao = _EXIBICAO.get(alvo, termo)
                if exibicao not in sinais[emocao]:
                    sinais[emocao].append(exibicao)
                break

    if not any(pontos.values()):
        return {"emocao": "neutro", "intensidade": 0, "secundaria": None,
                "sinais": [], "urgente": _urgente(normalizado, bruto), "confianca": 0.0}

    reforco = 1.0
    if any(token in _INTENSIFICADORES for token in tokens):
        reforco += 0.35
    letras = [c for c in bruto if c.isalpha()]
    if len(letras) >= 8 and sum(1 for c in letras if c.isupper()) / len(letras) > 0.6:
        reforco += 0.4
    if bruto.count("!") >= 2:
        reforco += 0.25
    if bruto.count("?") >= 3:
        pontos["confuso"] += 1.0

    for emocao in pontos:
        pontos[emocao] *= reforco

    ordenadas = sorted(pontos.items(), key=lambda par: (-par[1], _ORDEM.index(par[0])))
    emocao, maior = ordenadas[0]
    secundaria = ordenadas[1][0] if len(ordenadas) > 1 and ordenadas[1][1] >= maior * 0.6 else None
    if maior < 1.0:
        return {"emocao": "neutro", "intensidade": 0, "secundaria": None,
                "sinais": [], "urgente": _urgente(normalizado, bruto), "confianca": 0.0}

    intensidade = 3 if maior >= 5 else 2 if maior >= 3 else 1
    confianca = round(min(1.0, maior / 6.0), 2)
    return {
        "emocao": emocao,
        "intensidade": intensidade,
        "secundaria": secundaria,
        "sinais": (sinais[emocao] + (sinais[secundaria] if secundaria else []))[:4],
        "urgente": _urgente(normalizado, bruto),
        "confianca": confianca,
    }


def _urgente(normalizado: str, bruto: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", normalizado))
    return bool(tokens & _URGENCIA) or bruto.count("!") >= 2


def rotulo(leitura: dict) -> str:
    """Rótulo curto para log/interface: “frustrado (forte)”."""
    if not leitura or leitura.get("emocao") in (None, "neutro"):
        return "neutro"
    grau = {1: "leve", 2: "média", 3: "forte"}.get(int(leitura.get("intensidade") or 0), "leve")
    return f"{leitura['emocao']} ({grau})"


def instrucao(texto: str) -> str:
    """Trecho curto para o system prompt; vazio quando não há sinal emocional."""
    leitura = analisar(texto)
    emocao = leitura.get("emocao")
    if emocao == "neutro":
        return ""
    ajuste = _AJUSTES.get(emocao, "")
    sinais = ", ".join(f"“{s}”" for s in leitura.get("sinais", [])[:3])
    detalhe = f" Sinais: {sinais}." if sinais else ""
    urgencia = " Há urgência: responda sem rodeios." if leitura.get("urgente") else ""
    return (f"\n\nLeitura do usuário agora: {rotulo(leitura)}.{detalhe} "
            f"Ajuste o tom: {ajuste}{urgencia}")
