"""Correções pessoais de reconhecimento de voz.

Guarda, em `dados/correcoes_voz.json`, pares do tipo "o que o ULTRON ouviu"
-> "o que o usuário realmente disse". Na próxima transcrição parecida, o ULTRON
aplica a troca automaticamente antes de interpretar o comando.

É só para a voz de quem está usando: uma tabela local de "troque isto por
aquilo" que cresce com o uso, sem custo e sem depender da nuvem. Nunca é um
modelo de IA e nunca envia áudio para fora.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "dados" / "correcoes_voz.json"

_PALAVRA = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def _normalizar(texto: str) -> str:
    """Minúsculas e sem acento — só para comparar, nunca para devolver."""
    import unicodedata

    decomposto = unicodedata.normalize("NFD", str(texto))
    sem_acento = "".join(c for c in decomposto if unicodedata.category(c) != "Mn")
    return sem_acento.lower().strip()


def carregar() -> dict[str, str]:
    """Devolve o dicionário {ouvido: dito} salvo (vazio se não houver arquivo)."""
    try:
        salvo = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        if isinstance(salvo, dict):
            return {str(k).strip(): str(v).strip() for k, v in salvo.items() if str(k).strip()}
    except (OSError, ValueError):
        pass
    return {}


def salvar(tabela: dict[str, str]) -> None:
    """Persiste o dicionário completo (troca atômica: nunca deixa arquivo pela metade)."""
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO.with_suffix(".tmp")
    temporario.write_text(json.dumps(tabela, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(ARQUIVO)


def registrar(ouvido: str, dito: str) -> None:
    """Registra uma correção: da próxima vez que ouvir `ouvido`, entende `dito`."""
    ouvido = ouvido.strip()
    dito = dito.strip()
    if not ouvido or not dito:
        return
    tabela = carregar()
    tabela[_normalizar(ouvido)] = dito
    salvar(tabela)


def _palavras(texto: str) -> list[str]:
    return [p.group() for p in _PALAVRA.finditer(str(texto or ""))]


def registrar_correcao(ouvido: str, dito: str) -> None:
    """Guarda a correção no pedaço mais útil possível.

    Exemplos:
      * "abri o chrome" -> "abra o chrome": mesma frase, guarda só a palavra que
        mudou ("abri" -> "abra"), então a correção vale em qualquer comando;
      * "abre o roquet league" -> "rocket league": a frase corrigida é o fim (ou
        o começo) do que foi ouvido, então guarda só esse trecho;
      * quando nada alinha, guarda a frase inteira (o par exato ouvido -> dito).
    """
    a, b = _palavras(ouvido), _palavras(dito)
    if not a or not b or [w.lower() for w in a] == [w.lower() for w in b]:
        return
    if len(a) == len(b):
        diferentes = [(x, y) for x, y in zip(a, b) if _normalizar(x) != _normalizar(y)]
        # Palavra muito curta ("o" -> "a") viraria uma regra perigosa, que troca
        # artigo em toda frase. Nesse caso, guarda a frase inteira mais abaixo.
        if diferentes and all(len(x) >= 3 for x, _ in diferentes):
            tabela = carregar()
            for x, y in diferentes:
                tabela[_normalizar(x)] = y
            salvar(tabela)
            return
    if len(b) <= len(a):
        candidatos = []
        for inicio in (len(a) - len(b), 0):
            trecho = a[inicio:inicio + len(b)]
            nota = difflib.SequenceMatcher(
                None, " ".join(_normalizar(w) for w in trecho),
                " ".join(_normalizar(w) for w in b)).ratio()
            candidatos.append((nota, trecho))
        nota, trecho = max(candidatos, key=lambda par: par[0])
        # Só aceita o recorte quando ele realmente parece a frase corrigida;
        # senão o par inteiro é mais honesto do que um trecho inventado.
        if nota >= 0.6 and [_normalizar(w) for w in trecho] != [_normalizar(w) for w in b]:
            tabela = carregar()
            tabela[" ".join(_normalizar(w) for w in trecho)] = dito.strip()
            salvar(tabela)
            return
    registrar(ouvido, dito)


def aplicar(texto: str) -> tuple[str, list[tuple[str, str]]]:
    """Aplica as correções salvas ao `texto`.

    Devolve (texto corrigido, [(ouvido, dito), ...]). Corresponde sequências
    consecutivas de palavras (ignorando acento/maiúsculas) com as entradas salvas,
    então frases como "rocket leage" -> "Rocket League" funcionam. Nunca corrige
    o que não foi ensinado.
    """
    original = str(texto or "").strip()
    if not original:
        return original, []
    tabela = carregar()
    if not tabela:
        return original, []
    palavras = list(_PALAVRA.finditer(original))
    if not palavras:
        return original, []
    grupos = [(i, _normalizar(p.group())) for i, p in enumerate(palavras)]

    # Ordena entradas por tamanho decrescente (frases longas antes de curtas)
    # para evitar que uma entrada curta consuma palavras de uma longa.
    entradas = sorted(tabela.items(), key=lambda kv: -len(kv[0].split()))

    trocas: dict[int, tuple[str, int]] = {}
    consumido = set()
    for indice_inicial in range(len(grupos)):
        if indice_inicial in consumido:
            continue
        for chave, dito in entradas:
            chave_palavras = chave.split()
            tamanho = len(chave_palavras)
            if tamanho == 0 or indice_inicial + tamanho > len(grupos):
                continue
            if any((indice_inicial + k) in consumido for k in range(tamanho)):
                continue
            if [g[1] for g in grupos[indice_inicial:indice_inicial + tamanho]] == chave_palavras:
                for k in range(tamanho):
                    consumido.add(indice_inicial + k)
                trocas[indice_inicial] = (dito, tamanho)
                break
    if not trocas:
        return original, []
    partes, cursor, correcoes = [], 0, []
    indice = 0
    while indice < len(palavras):
        palavra = palavras[indice]
        partes.append(original[cursor:palavra.start()])
        troca = trocas.get(indice)
        if troca is None:
            partes.append(palavra.group())
            cursor = palavra.end()
            indice += 1
            continue
        nova, tamanho = troca
        partes.append(nova)
        trecho_original = original[palavra.start():palavras[indice + tamanho - 1].end()]
        correcoes.append((trecho_original, nova))
        cursor = palavras[indice + tamanho - 1].end()
        indice += tamanho
    partes.append(original[cursor:])
    return "".join(partes), correcoes
