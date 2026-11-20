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
        return {"tocando": False}
    faixa = corpo.get("item") or {}
    return {
        "tocando": bool(corpo.get("is_playing")),
        "faixa": faixa.get("name", ""),
        "artista": ", ".join(a.get("name", "") for a in faixa.get("artists", [])),
        "dispositivo": (corpo.get("device") or {}).get("name", ""),
    }
