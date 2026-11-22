"""Spotify Web API: buscar, tocar e consultar o que está tocando.

Sem SDK novo: `requests` já é dependência. O token de acesso é renovado pelo
refresh token e fica em cache de processo; nada de rede no import. As credenciais
vêm do `config` (o cofre as preenche na inicialização) — este módulo não lê o cofre.
"""
from __future__ import annotations

import os
import threading
import time
import unicodedata

import requests

import config

BASE = "https://api.spotify.com/v1"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_trava = threading.Lock()
_token = ""
_expira = 0.0


def configurado() -> bool:
    return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET
                and config.SPOTIFY_REFRESH)


def _token_valido() -> str:
    """Token de acesso em cache; renova 60 s antes de expirar."""
    global _token, _expira
    with _trava:
        if _token and time.time() < _expira - 60:
            return _token
        resposta = requests.post(
            _TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": config.SPOTIFY_REFRESH},
            auth=(config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET),
            timeout=15,
        )
        if not resposta.ok:
            raise RuntimeError("não consegui renovar o acesso ao Spotify; confira as credenciais")
        dados = resposta.json()
        _token = dados.get("access_token", "")
        _expira = time.time() + float(dados.get("expires_in", 3600))
        if not _token:
            raise RuntimeError("o Spotify não devolveu um token de acesso")
        return _token


def _pedir(metodo: str, caminho: str, **kwargs):
    """Chamada autenticada; devolve (status, json) sem vazar o token em erro."""
    resposta = requests.request(
        metodo, BASE + caminho,
        headers={"Authorization": f"Bearer {_token_valido()}"},
        timeout=15, **kwargs,
    )
    try:
        corpo = resposta.json()
    except ValueError:
        corpo = {}
    return resposta.status_code, corpo if isinstance(corpo, dict) else {}


def buscar(consulta: str) -> dict:
    status, corpo = _pedir("GET", "/search", params={
        "q": consulta, "type": "track,artist,playlist", "limit": 5, "market": "BR"})
    if status != 200:
        raise RuntimeError(f"a busca no Spotify falhou (HTTP {status})")
    faixas = (corpo.get("tracks") or {}).get("items") or []
    artistas = (corpo.get("artists") or {}).get("items") or []
    playlists = (corpo.get("playlists") or {}).get("items") or []
    return {
        "faixas": [{"nome": item.get("name", ""),
                    "artista": ", ".join(a.get("name", "") for a in item.get("artists") or []),
                    "uri": item.get("uri", "")}
                   for item in faixas if item],
        "artistas": [{"nome": item.get("name", ""), "uri": item.get("uri", "")}
                     for item in artistas if item],
        "playlists": [{"nome": item.get("name", ""), "uri": item.get("uri", "")}
                      for item in playlists if item],
    }


def _dispositivos_ordenados() -> list[dict]:
    """Lista dispositivos ordenados com prioridade para ativo e computador local."""
    _, dispositivos = _pedir("GET", "/me/player/devices")
    lista = [d for d in dispositivos.get("devices", []) if d.get("id")]
    lista.sort(key=lambda d: (not bool(d.get("is_active")), str(d.get("type") or "") != "Computer"))
    return lista


def _confirmado(uri: str) -> bool:
    """Confirma que a faixa pedida começou: o 204 do PUT sozinho não prova."""
    for tentativa in range(3):
        if tentativa:
            time.sleep(0.4)
        _, corpo = _pedir("GET", "/me/player")
        item = corpo.get("item") or {}
        if corpo.get("is_playing") and item.get("uri") == uri:
            return True
    return False


def tocar(consulta: str) -> str:
    resultado = buscar(consulta)
    if not resultado["faixas"]:
        return f"Não encontrei nenhuma faixa para {consulta!r}."
    faixa = resultado["faixas"][0]
    status, _ = _pedir("PUT", "/me/player/play", json={"uris": [faixa["uri"]]})
    if status == 404:
        ids = [d["id"] for d in _dispositivos_ordenados()]
        if ids:
            status, _ = _pedir("PUT", "/me/player/play", json={"uris": [faixa["uri"]]},
                               params={"device_id": ids[0]})
        if status not in (200, 204):
            return "Abra o Spotify e toque algo para ativar um dispositivo; aí eu troco a faixa."
    if status == 403:
        return "A conta não permite controlar a reprodução; o Spotify Premium é necessário."
    if status not in (200, 204):
        return f"Não consegui tocar no Spotify (HTTP {status})."
    if not _confirmado(faixa["uri"]):
        return ("O Spotify aceitou a faixa, mas não confirmei que começou. "
                "Abra o Spotify e toque algo para ativar o dispositivo; aí eu troco a faixa.")
    return f"Tocando {faixa['nome']} — {faixa['artista']}."


def _escolher_alvo_local(resultado: dict) -> tuple[str, str, str]:
    faixas = resultado.get("faixas") or []
    if faixas:
        faixa = faixas[0]
        nome = str(faixa.get("nome") or "").strip()
        artista = str(faixa.get("artista") or "").strip()
        rotulo = f"{nome} — {artista}" if artista else nome
        return str(faixa.get("uri") or ""), rotulo, "track"
    playlists = resultado.get("playlists") or []
    if playlists:
        pl = playlists[0]
        return str(pl.get("uri") or ""), str(pl.get("nome") or "").strip(), "playlist"
    artistas = resultado.get("artistas") or []
    if artistas:
        art = artistas[0]
        return str(art.get("uri") or ""), str(art.get("nome") or "").strip(), "artist"
    return "", "", ""


def ativar_e_tocar_local(consulta: str, resposta_api: str = "") -> str:
    """Acorda o app desktop do Spotify no Windows via URI e inicia a reprodução local."""
    if not configurado() or os.name != "nt" or not hasattr(os, "startfile"):
        return ""
    try:
        resultado = buscar(consulta)
    except Exception:
        return ""
    uri, rotulo, tipo = _escolher_alvo_local(resultado)
    if not uri:
        return ""
    try:
        os.startfile(uri)
    except OSError:
        return ""
    time.sleep(1.2)
    payload = {"uris": [uri]} if tipo == "track" else {"context_uri": uri}
    tocando = False
    try:
        ids = [d["id"] for d in _dispositivos_ordenados()]
        kwargs = {"json": payload}
        if ids:
            kwargs["params"] = {"device_id": ids[0]}
        status, _ = _pedir("PUT", "/me/player/play", **kwargs)
        if status in (200, 204):
            tocando = _confirmado(uri) if tipo == "track" else bool(estado().get("tocando"))
    except Exception:
        tocando = False
    if not tocando:
        try:
            import pyautogui
            pyautogui.press("playpause")
        except Exception:
            pass
    if tipo == "playlist":
        return f"Tocando playlist {rotulo} no Spotify."
    return f"Tocando {rotulo} no Spotify."


def _normalizar_acao(acao: str) -> str:
    texto = unicodedata.normalize("NFD", str(acao or "").lower().strip())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").replace(" ", "_")


_ACOES_PLAYER = {
    "continuar": "continuar", "continue": "continuar", "continua": "continuar",
    "retomar": "continuar", "retoma": "continuar", "retome": "continuar",
    "tocar": "continuar", "play": "continuar", "despausar": "continuar",
    "despausa": "continuar", "despause": "continuar",
    "pausar": "pausar", "pausa": "pausar", "pause": "pausar",
    "parar": "pausar", "para": "pausar", "pare": "pausar",
    "proxima": "proxima", "proximo": "proxima", "pular": "proxima",
    "pula": "proxima", "pule": "proxima", "passar": "proxima",
    "passa": "proxima", "avancar": "proxima", "avanca": "proxima",
    "anterior": "anterior", "voltar": "anterior", "volta": "anterior", "volte": "anterior",
}


def controlar_player(acao: str) -> str | None:
    """Controla a sessão ativa do Spotify via Web API; devolve None para fallback em tecla de mídia."""
    if not configurado():
        return None
    canonica = _ACOES_PLAYER.get(_normalizar_acao(acao))
    if not canonica:
        return None
    try:
        if canonica == "continuar":
            atual = estado()
            if atual.get("tocando"):
                faixa = str(atual.get("faixa") or "").strip()
                artista = str(atual.get("artista") or "").strip()
                detalhe = f"{faixa} — {artista}".strip(" —")
                return f"A música já está tocando no Spotify: {detalhe}." if detalhe else "A música já está tocando no Spotify."
            status, _ = _pedir("PUT", "/me/player/play")
            if status == 404:
                ids = [d["id"] for d in _dispositivos_ordenados()]
                if ids:
                    status, _ = _pedir("PUT", "/me/player/play", params={"device_id": ids[0]})
            return "Reprodução retomada no Spotify." if status in (200, 204) else None

        if canonica == "pausar":
            atual = estado()
            if atual.get("faixa") and not atual.get("tocando"):
                return "A reprodução já está pausada no Spotify."
            status, _ = _pedir("PUT", "/me/player/pause")
            if status == 404:
                ids = [d["id"] for d in _dispositivos_ordenados()]
                if ids:
                    status, _ = _pedir("PUT", "/me/player/pause", params={"device_id": ids[0]})
            return "Música pausada no Spotify." if status in (200, 204) else None

        caminho = "/me/player/next" if canonica == "proxima" else "/me/player/previous"
        status, _ = _pedir("POST", caminho)
        if status == 404:
            ids = [d["id"] for d in _dispositivos_ordenados()]
            if ids:
                status, _ = _pedir("POST", caminho, params={"device_id": ids[0]})
        if status in (200, 204):
            return "Próxima faixa no Spotify." if canonica == "proxima" else "Faixa anterior no Spotify."
    except Exception:
        return None
    return None


def estado() -> dict:
    status, corpo = _pedir("GET", "/me/player")
    if status == 204 or not corpo:
        status, corpo = _pedir("GET", "/me/player/currently-playing")
        if status == 204 or not corpo:
            return {"tocando": False}
    faixa = corpo.get("item") or {}
    if not faixa:
        return {"tocando": False}
    return {
        "tocando": bool(corpo.get("is_playing")),
        "id": faixa.get("id", ""),
        "uri": faixa.get("uri", ""),
        "faixa": faixa.get("name", ""),
        "artista": ", ".join(a.get("name", "") for a in (faixa.get("artists") or []) if a),
        "dispositivo": (corpo.get("device") or {}).get("name", ""),
    }


def _normalizar_busca(texto: str) -> str:
    bruto = unicodedata.normalize("NFD", str(texto or "").lower().strip())
    sem_acento = "".join(c for c in bruto if unicodedata.category(c) != "Mn")
    return " ".join(sem_acento.split())


def minhas_playlists(limite: int = 50) -> list[dict]:
    """Lista as playlists do usuário autenticado no Spotify."""
    n = max(1, min(50, int(limite or 50)))
    status, corpo = _pedir("GET", "/me/playlists", params={"limit": n})
    if status == 403:
        raise RuntimeError(
            "faltam permissões de playlist no Spotify; rode `python tools/autorizar_spotify.py` "
            "para atualizar o token com acesso às suas playlists"
        )
    if status != 200:
        raise RuntimeError(f"não consegui listar suas playlists do Spotify (HTTP {status})")
    itens = corpo.get("items") or []
    saida = []
    for item in itens:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        faixas_info = (
            item.get("items")
            if isinstance(item.get("items"), dict)
            else (item.get("tracks") if isinstance(item.get("tracks"), dict) else {})
        )
        dono_info = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        saida.append({
            "id": str(item.get("id") or ""),
            "nome": str(item.get("name") or "").strip(),
            "uri": str(item.get("uri") or ""),
            "dono": str(dono_info.get("display_name") or dono_info.get("id") or ""),
            "publica": bool(item.get("public")),
            "colaborativa": bool(item.get("collaborative")),
            "total_faixas": int(faixas_info.get("total") or 0),
        })
    return saida


def _escolher_playlist(playlists: list[dict], alvo: str) -> dict | None:
    """Encontra a playlist do usuário pelo nome, ID ou URI (exato -> prefixo -> substring -> tokens)."""
    bruto = str(alvo or "").strip().strip("\"'")
    if not bruto or not playlists:
        return None
    if bruto.startswith("spotify:playlist:"):
        pid = bruto.split(":")[-1].strip()
        for pl in playlists:
            if pl.get("id") == pid or pl.get("uri") == bruto:
                return pl
    for pl in playlists:
        if pl.get("id") == bruto:
            return pl
    alvo_norm = _normalizar_busca(bruto)
    if not alvo_norm:
        return None
    # 1. Igualdade exata (sem acento/caixa)
    for pl in playlists:
        if _normalizar_busca(pl.get("nome", "")) == alvo_norm:
            return pl
    # 2. Começa com o termo buscado
    for pl in playlists:
        nome_norm = _normalizar_busca(pl.get("nome", ""))
        if nome_norm.startswith(alvo_norm):
            return pl
    # 3. Contém o termo buscado (ou vice-versa)
    for pl in playlists:
        nome_norm = _normalizar_busca(pl.get("nome", ""))
        if alvo_norm in nome_norm or (nome_norm and nome_norm in alvo_norm):
            return pl
    # 4. Maior interseção de palavras significativas
    tokens_alvo = {t for t in alvo_norm.split() if len(t) >= 2}
    if tokens_alvo:
        melhor, melhor_pontos = None, 0
        for pl in playlists:
            tokens_pl = set(_normalizar_busca(pl.get("nome", "")).split())
            comuns = len(tokens_alvo & tokens_pl)
            if comuns > melhor_pontos:
                melhor, melhor_pontos = pl, comuns
        if melhor_pontos > 0:
            return melhor
    return None


def _resolver_faixa_para_playlist(musica: str = "") -> tuple[dict | None, str]:
    """Resolve a faixa alvo: se `musica` estiver vazio, usa a faixa atual do player."""
    consulta = str(musica or "").strip()
    if not consulta:
        atual = estado()
        uri = str(atual.get("uri") or "").strip()
        faixa_id = str(atual.get("id") or "").strip()
        if not faixa_id and uri.startswith("spotify:track:"):
            faixa_id = uri.split(":")[-1]
        if not uri and faixa_id:
            uri = f"spotify:track:{faixa_id}"
        if not uri:
            return None, "Nenhuma música está tocando ou selecionada no Spotify agora."
        return {
            "id": faixa_id,
            "uri": uri,
            "nome": str(atual.get("faixa") or "Faixa atual").strip(),
            "artista": str(atual.get("artista") or "").strip(),
        }, ""

    if consulta.startswith("spotify:track:"):
        fid = consulta.split(":")[-1].strip()
        return {"id": fid, "uri": consulta, "nome": consulta, "artista": ""}, ""

    resultado = buscar(consulta)
    faixas = resultado.get("faixas") or []
    if not faixas:
        return None, f"Não encontrei nenhuma música no Spotify para {consulta!r}."
    primeira = faixas[0]
    uri = str(primeira.get("uri") or "").strip()
    fid = uri.split(":")[-1] if uri.startswith("spotify:track:") else ""
    return {
        "id": fid,
        "uri": uri,
        "nome": str(primeira.get("nome") or consulta).strip(),
        "artista": str(primeira.get("artista") or "").strip(),
    }, ""


def _playlist_ja_contem_faixa(playlist_id: str, track_uri: str) -> bool:
    """Verifica nas primeiras 100 faixas da playlist se a música já está lá para evitar duplicata."""
    if not playlist_id or not track_uri:
        return False
    status, corpo = _pedir(
        "GET",
        f"/playlists/{playlist_id}/items",
        params={"limit": 100},
    )
    if status == 403 or status == 404:
        status, corpo = _pedir(
            "GET",
            f"/playlists/{playlist_id}/tracks",
            params={"fields": "items(track(uri))", "limit": 100},
        )
    if status != 200:
        return False
    for entry in corpo.get("items") or []:
        if not isinstance(entry, dict):
            continue
        track = entry.get("item") if isinstance(entry.get("item"), dict) else entry.get("track")
        if isinstance(track, dict) and track.get("uri") == track_uri:
            return True
    return False


_SINONIMOS_CURTIDAS = frozenset({
    "curtidas", "musicas curtidas", "minhas curtidas", "favoritas",
    "musicas favoritas", "minhas favoritas", "liked", "liked songs", "gostei",
})


def adicionar_a_playlist(playlist: str = "", musica: str = "") -> str:
    """Adiciona a música que está tocando (ou uma música buscada) a uma playlist do usuário no Spotify.

    Se `playlist` indicar músicas curtidas/favoritas, salva na biblioteca (`PUT /me/library` com fallback para `PUT /me/tracks`).
    """
    faixa, erro_faixa = _resolver_faixa_para_playlist(musica)
    if not faixa:
        return erro_faixa
    rotulo_faixa = f"{faixa['nome']} — {faixa['artista']}" if faixa.get("artista") else faixa["nome"]

    alvo_pl = str(playlist or "").strip()
    alvo_norm = _normalizar_busca(alvo_pl)

    try:
        playlists = minhas_playlists()
    except Exception:
        if alvo_norm not in _SINONIMOS_CURTIDAS:
            raise
        playlists = []

    if not alvo_pl:
        if not playlists:
            return "Não encontrei nenhuma playlist na sua conta do Spotify."
        nomes = ", ".join(p["nome"] for p in playlists[:8] if p.get("nome"))
        return f"Em qual playlist você quer adicionar {rotulo_faixa}? Suas playlists: {nomes}."

    escolhida = _escolher_playlist(playlists, alvo_pl)

    # Caso especial: Músicas Curtidas ("Liked Songs"), se não houver playlist real com esse nome exato
    if alvo_norm in _SINONIMOS_CURTIDAS and (
        escolhida is None or _normalizar_busca(escolhida.get("nome", "")) != alvo_norm
    ):
        fid = faixa.get("id") or (faixa["uri"].split(":")[-1] if faixa["uri"].startswith("spotify:track:") else "")
        uri_faixa = faixa["uri"] or (f"spotify:track:{fid}" if fid else "")
        if not uri_faixa:
            return f"Não consegui identificar o código da faixa {rotulo_faixa} para salvar nas Curtidas."
        status, _ = _pedir("PUT", "/me/library", params={"uris": uri_faixa})
        if status not in (200, 201, 204) and fid:
            status, _ = _pedir("PUT", "/me/tracks", json={"ids": [fid]})
        if status in (200, 201, 204):
            return f"Adicionei {rotulo_faixa} às suas Músicas Curtidas no Spotify."
        if status == 403:
            return (
                "Falta permissão para salvar nas Músicas Curtidas do Spotify. "
                "Rode `python tools/autorizar_spotify.py` para atualizar a autorização."
            )
        return f"Não consegui salvar nas Músicas Curtidas do Spotify (HTTP {status})."

    if not playlists:
        return "Não encontrei nenhuma playlist na sua conta do Spotify."

    if not escolhida:
        nomes = ", ".join(p["nome"] for p in playlists[:8] if p.get("nome"))
        return (
            f"Não encontrei a playlist {alvo_pl!r} na sua conta do Spotify. "
            f"Suas playlists disponíveis: {nomes}."
        )

    pid = escolhida["id"]
    nome_pl = escolhida["nome"]
    if _playlist_ja_contem_faixa(pid, faixa["uri"]):
        return f"A música {rotulo_faixa} já está na playlist {nome_pl}."

    status, _ = _pedir("POST", f"/playlists/{pid}/items", json={"uris": [faixa["uri"]]})
    if status not in (200, 201):
        status, _ = _pedir("POST", f"/playlists/{pid}/tracks", json={"uris": [faixa["uri"]]})
    if status in (200, 201):
        return f"Adicionei {rotulo_faixa} à playlist {nome_pl} no Spotify."
    if status == 403:
        return (
            f"O Spotify recusou a alteração na playlist {nome_pl} (sem permissão). "
            "Se a playlist for sua, rode `python tools/autorizar_spotify.py` para liberar a edição de playlists."
        )
    return f"Não consegui adicionar a música à playlist {nome_pl} (HTTP {status})."

