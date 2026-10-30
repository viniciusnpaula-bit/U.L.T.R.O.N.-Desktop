"""Spotify Web API: buscar, tocar e consultar o que está tocando.

Sem SDK novo: `requests` já é dependência. O token de acesso é renovado pelo
refresh token e fica em cache de processo; nada de rede no import. As credenciais
vêm do `config` (o cofre as preenche na inicialização) — este módulo não lê o cofre.
"""
from __future__ import annotations

import threading
import time

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


def tocar(consulta: str) -> str:
    resultado = buscar(consulta)
    if not resultado["faixas"]:
        return f"Não encontrei nenhuma faixa para {consulta!r}."
    faixa = resultado["faixas"][0]
    status, _ = _pedir("PUT", "/me/player/play", json={"uris": [faixa["uri"]]})
    if status == 404:
        _, dispositivos = _pedir("GET", "/me/player/devices")
        ids = [d.get("id") for d in dispositivos.get("devices", []) if d.get("id")]
        if ids:
            status, _ = _pedir("PUT", "/me/player/play", json={"uris": [faixa["uri"]]},
                               params={"device_id": ids[0]})
        if status not in (200, 204):
            return "Abra o Spotify e toque algo para ativar um dispositivo; aí eu troco a faixa."
    if status == 403:
        return "A conta não permite controlar a reprodução; o Spotify Premium é necessário."
    if status not in (200, 204):
        return f"Não consegui tocar no Spotify (HTTP {status})."
    return f"Tocando {faixa['nome']} — {faixa['artista']}."


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
