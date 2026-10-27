"""Correção de fala: conserta palavras que o reconhecimento ouviu errado.

Regras para não piorar o que já estava certo:
  * verbo só é corrigido quando é a PRIMEIRA palavra do comando (é ali que o
    reconhecimento erra "abra" -> "abri"); no meio da frase, "abri" é passado;
  * nome de aplicativo só é corrigido quando existe um verbo de comando na frase;
  * a troca precisa ser parecida o bastante (difflib) ou estar na lista explícita
    de erros conhecidos; na dúvida, não mexe — o cérebro pergunta.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Verbos de comando que autorizam corrigir nomes de aplicativo.
VERBOS_COMANDO = {
    "abre", "abra", "abrir", "fecha", "feche", "fechar", "toca", "toque", "tocar",
    "inicia", "inicie", "iniciar", "coloca", "coloque", "colocar", "poe", "ponha",
    "minimiza", "minimize", "minimizar", "aumenta", "aumente", "aumentar",
    "diminui", "diminua", "diminuir", "ajusta", "ajuste", "ajustar", "ativa",
    "ative", "ativar", "desativa", "desative", "desativar",
}

# Erros que já foram ouvidos na prática: troca direta, sem cálculo.
VERBOS_ERRADOS = {
    "abri": "abra", "abrir": "abrir", "fexa": "fecha", "feixa": "fecha",
    "fexar": "fechar", "feichar": "fechar",
    "toke": "toca", "tokei": "toque", "inicia": "inicia", "inice": "inicie",
    "coloke": "coloque", "ponh": "ponha",
}

APPS_ERRADOS = {
    "spotifai": "Spotify", "spotifay": "Spotify", "spotifi": "Spotify",
    "spotfy": "Spotify", "crome": "Chrome", "cromi": "Chrome", "crom": "Chrome",
    "netiflis": "Netflix", "netflis": "Netflix", "netiflix": "Netflix",
    "discordi": "Discord", "discorde": "Discord", "roquet": "Rocket",
    "edgi": "Edge", "edge": "Edge", "you tube": "YouTube", "youtubi": "YouTube",
    "whatsap": "WhatsApp", "telegran": "Telegram",
}

# Nomes canônicos usados na comparação aproximada (e a grafia devolvida).
APPS = {
    "spotify": "Spotify", "chrome": "Chrome", "edge": "Edge", "netflix": "Netflix",
    "discord": "Discord", "steam": "Steam", "rocket": "Rocket", "league": "League",
    "calculadora": "calculadora", "paint": "Paint", "word": "Word", "excel": "Excel",
    "explorador": "explorador", "configuracoes": "configurações",
    "youtube": "YouTube", "navegador": "navegador", "notas": "notas",
    "musica": "música", "volume": "volume", "brilho": "brilho", "tela": "tela",
    "arquivo": "arquivo", "pasta": "pasta", "lembrete": "lembrete",
    "clima": "clima", "noticias": "notícias",
}

_PARADAS = {
    "o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "no", "na",
    "nos", "nas", "em", "para", "pra", "por", "com", "que", "e", "meu", "minha",
    "favor", "ai", "aqui", "agora", "ja", "so", "mais", "menos", "muito", "pouco",
}
_PALAVRA = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")

# Vocabulário de comandos conhecidos: usado pelo fuzzy matching generalizado
# (não só para nomes de aplicativo). Se o reconhecimento distorcer uma palavra
# de um comando, ela é corrigida para a palavra canônica antes de interpretar.
COMANDOS_CONHECIDOS = (
    "abrir aplicativo", "fechar aplicativo", "abrir programa", "fechar programa",
    "organizar arquivos", "organizar pasta", "desfazer",
    "tirar print", "capturar tela", "aumentar volume", "diminuir volume", "mutar",
    "tocar musica", "pausar musica", "proxima musica", "musica anterior",
    "pesquisar", "abrir site", "criar pasta", "criar arquivo",
    "mover arquivo", "compactar", "descompactar",
    "desligar", "reiniciar", "bloquear", "que horas sao",
    "previsao do tempo", "criar lembrete",
)


def _vocabulario_comandos(comandos=None) -> set[str]:
    """Conjunto de palavras canônicas dos comandos conhecidos."""
    frases = comandos if comandos is not None else COMANDOS_CONHECIDOS
    palavras: set[str] = set()
    for frase in frases:
        palavras.update(normalizar(frase).split())
    return palavras


def resolver_comando(texto: str, comandos=None, corte: float = 0.80) -> tuple[str, list[tuple[str, str]]]:
    """Corrige palavras distorcidas comparando com o vocabulário de comandos.

    Devolve (texto corrigido, [(original, corrigido), ...]). Só troca palavras
    com pelo menos 4 letras que não estão no vocabulário e que são muito
    parecidas com uma palavra canônica; na dúvida, não mexe. Verbos de comando
    legítimos (abre, toca, fecha...) nunca são trocados.
    """
    original = str(texto or "").strip()
    if not original:
        return original, []
    vocabulario = _vocabulario_comandos(comandos)
    if not vocabulario:
        return original, []
    protegidas = set(VERBOS_COMANDO) | set(APPS) | _PARADAS
    palavras = list(_PALAVRA.finditer(original))
    trocas: dict[int, str] = {}
    for indice, palavra in enumerate(palavras):
        normal = normalizar(palavra.group())
        if len(normal) < 4 or normal in vocabulario or normal in protegidas:
            continue
        # Erros já conhecidos: troca direta, sem cálculo.
        if normal in VERBOS_ERRADOS:
            trocas[indice] = VERBOS_ERRADOS[normal]
            continue
        if normal in APPS_ERRADOS:
            trocas[indice] = APPS_ERRADOS[normal]
            continue
        alvo = difflib.get_close_matches(normal, list(vocabulario), n=1, cutoff=corte)
        if alvo and _parecido(normal, alvo[0], corte):
            # Nunca troca uma forma que só é "pedaço" da canônica: "desliga" não
            # vira "desligar", "toca" não vira "tocar", "musicas" não vira
            # "musica". Isso preserva conjugações e plurais legítimos; só a
            # distorção real (letra trocada) é corrigida.
            if normal.startswith(alvo[0]) or alvo[0].startswith(normal):
                continue
            # Também não troca conjugação por infinitivo: "bloqueia", "tira",
            # "pesquisa", "organizam" são a forma certa na frase; "bloquear" só
            # é o nome canônico do comando.
            if alvo[0].endswith("r") and normal[-1] in "aeiom":
                continue
            trocas[indice] = alvo[0]
    if not trocas:
        return original, []
    partes, cursor, correcoes = [], 0, []
    for indice, palavra in enumerate(palavras):
        partes.append(original[cursor:palavra.start()])
        nova = trocas.get(indice)
        if nova is None:
            partes.append(palavra.group())
        else:
            partes.append(nova)
            correcoes.append((palavra.group(), nova))
        cursor = palavra.end()
    partes.append(original[cursor:])
    return "".join(partes), correcoes


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento — só para comparar, nunca para devolver."""
    decomposto = unicodedata.normalize("NFD", str(texto))
    sem_acento = "".join(c for c in decomposto if unicodedata.category(c) != "Mn")
    return sem_acento.lower()


def _parecido(token: str, alvo: str, corte: float) -> bool:
    if abs(len(token) - len(alvo)) > 2:
        return False
    return difflib.SequenceMatcher(None, token, alvo).ratio() >= corte


def corrigir(texto: str) -> tuple[str, list[tuple[str, str]]]:
    """Devolve (texto corrigido, [(original, corrigido), ...])."""
    original = str(texto or "").strip()
    if not original:
        return original, []
    palavras = list(_PALAVRA.finditer(original))
    if not palavras:
        return original, []

    normais = [normalizar(p.group()) for p in palavras]
    trocas: dict[int, str] = {}

    # 1) verbo de comando só na primeira palavra
    if normais[0] in VERBOS_ERRADOS and VERBOS_ERRADOS[normais[0]] != normais[0]:
        trocas[0] = VERBOS_ERRADOS[normais[0]]
        normais[0] = normalizar(trocas[0])

    # 2) nomes de aplicativo, quando há verbo de comando na frase
    tem_verbo = any(n in VERBOS_COMANDO for n in normais[:4])
    if tem_verbo:
        for indice, normal in enumerate(normais):
            if indice in trocas or normal in _PARADAS or len(normal) < 5:
                continue
            if normal in APPS:
                continue
            if normal in APPS_ERRADOS:
                trocas[indice] = APPS_ERRADOS[normal]
                continue
            alvo = difflib.get_close_matches(normal, list(APPS), n=1, cutoff=0.86)
            if alvo and _parecido(normal, alvo[0], 0.86):
                trocas[indice] = APPS[alvo[0]]

    if not trocas:
        return original, []

    # 3) remonta o texto trocando só os trechos corrigidos
    partes, cursor, correcoes = [], 0, []
    for indice, palavra in enumerate(palavras):
        partes.append(original[cursor:palavra.start()])
        nova = trocas.get(indice)
        if nova is None:
            partes.append(palavra.group())
        else:
            partes.append(nova)
            correcoes.append((palavra.group(), nova))
        cursor = palavra.end()
    partes.append(original[cursor:])
    return "".join(partes), correcoes
