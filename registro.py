"""Registro emocional: a marca que o modelo põe na resposta vira prosódia na mesma voz.

Sem chamada extra de IA: o próprio modelo escreve `[[registro:lamento]]` no começo
da resposta (instrução no system prompt) e este módulo só lê a string, tira a marca
do texto e traduz o nome em um delta pequeno de tom/velocidade. O parser é local,
determinístico e nunca quebra: na dúvida, "neutro".

O JSON (`registros_emocionais.json`) é configuração do usuário; qualquer valor
absurdo é limitado a LIMITE para a fala não virar caricatura.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARQUIVO = RAIZ / "registros_emocionais.json"

NEUTRO = "neutro"
REGISTROS = ("neutro", "lamento", "encorajador", "alerta", "comemorando", "serio", "duvida")
LIMITE = 15  # unidades: pontos percentuais no rate e Hz no pitch

# Padrão embutido: o JSON é opcional. O neutro é sempre zero.
PADRAO = {
    "neutro": {"rate": 0, "pitch": 0},
    "lamento": {"rate": -8, "pitch": -8},
    "encorajador": {"rate": 5, "pitch": 4},
    "alerta": {"rate": 10, "pitch": 3},
    "comemorando": {"rate": 8, "pitch": 6},
    "serio": {"rate": -5, "pitch": -5},
    "duvida": {"rate": -3, "pitch": 0},
}

# `[[registro:nome]]` no começo, com folga para espaços e maiúsculas.
_MARCA = re.compile(r"^\s*\[\[\s*registro\s*:\s*([a-zà-ú]+)\s*\]\]\s*", re.IGNORECASE)
# Marca quebrada (sem o `]]` final): some do texto, mas o registro cai em neutro.
_MARCA_QUEBRADA = re.compile(r"^\s*\[\[\s*registro\s*:\s*[a-zà-ú]*\s*\]?\]?\s*", re.IGNORECASE)

INSTRUCAO_SISTEMA = (
    "Registro emocional: comece TODA resposta com uma única marca no formato "
    "[[registro:NOME]], usando só um destes nomes: " + ", ".join(REGISTROS) + ". "
    "Escolha pelo sentimento da situação para o usuário, não pelo seu. Logo depois "
    "da marca, antes de resolver o problema, reconheça o sentimento em UMA frase "
    "curta e sincera; nunca force otimismo numa notícia ruim nem frieza numa notícia "
    "boa. Só então siga para a ação ou a solução. A marca é invisível para o usuário: "
    "nunca a explique, nunca a repita no meio do texto. Exemplo: usuário \"acabei de "
    "perder uma venda\" → [[registro:lamento]] Lamento, senhor. Vamos melhorar a ideia "
    "para vender mais. Se a resposta for apenas uma chamada de ferramenta, não escreva "
    "a marca ainda: ela vai só na resposta final em texto. "
)


def extrair(texto) -> tuple[str, str]:
    """Devolve (registro, texto sem a marca). Ausente, desconhecida ou malformada → neutro."""
    texto = str(texto or "")
    achado = _MARCA.match(texto)
    if achado:
        nome = achado.group(1).lower()
        return (nome if nome in REGISTROS else NEUTRO), texto[achado.end():].lstrip()
    if texto.lstrip().lower().startswith("[[registro:"):
        return NEUTRO, _MARCA_QUEBRADA.sub("", texto, count=1).lstrip()
    return NEUTRO, texto


def _numero(valor):
    """Número do JSON saneado: bool e texto não contam; fora do limite é cortado."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return max(-LIMITE, min(LIMITE, int(round(valor))))


def ajustes() -> dict[str, dict[str, int]]:
    """Mapa registro -> {rate, pitch} com os valores do JSON já limitados."""
    base = {nome: dict(valores) for nome, valores in PADRAO.items()}
    try:
        lido = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return base
    if not isinstance(lido, dict):
        return base
    for nome in REGISTROS:
        item = lido.get(nome)
        if not isinstance(item, dict):
            continue
        for chave in ("rate", "pitch"):
            valor = _numero(item.get(chave))
            if valor is not None:
                base[nome][chave] = valor
    return base


def _deslocar(valor, delta, sufixo) -> str:
    """Soma o delta ao ajuste que a voz já usa (ex.: "+0%" -> "-8%", "-12Hz" -> "-20Hz")."""
    achado = re.match(r"\s*([+-]?\d+)\s*" + re.escape(sufixo), str(valor or ""), re.IGNORECASE)
    base = int(achado.group(1)) if achado else 0
    return f"{base + delta:+d}{sufixo}"


def aplicar_voz(nome, rate, pitch) -> tuple[str, str]:
    """Delta do registro em cima da voz escolhida no painel; o neutro não muda nada."""
    delta = ajustes().get(nome if nome in REGISTROS else NEUTRO)
    return _deslocar(rate, delta["rate"], "%"), _deslocar(pitch, delta["pitch"], "Hz")


def registrar(nome) -> None:
    """Loga só o nome do registro — nunca o texto da conversa."""
    try:
        import seguranca
        seguranca.log.info(f"[registro] {nome if nome in REGISTROS else NEUTRO}")
    except Exception:
        pass
