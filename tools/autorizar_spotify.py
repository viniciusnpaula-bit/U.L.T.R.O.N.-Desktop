"""Gera o refresh token do Spotify (fluxo authorization code + PKCE).

Uso único, fora do ULTRON e fora das ferramentas:

    python tools/autorizar_spotify.py

Antes: crie o app em https://developer.spotify.com/dashboard e cadastre
`http://127.0.0.1:8888/callback` em Redirect URIs. O client id e o secret vão
para o cofre da interface; o refresh token impresso aqui também.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config

REDIRECT = "http://127.0.0.1:8888/callback"
ESCOPOS = "user-modify-playback-state user-read-playback-state"
_codigo = {}


class _Callback(BaseHTTPRequestHandler):
    def do_GET(self):
        consulta = urllib.parse.urlparse(self.path).query
        _codigo.update(urllib.parse.parse_qs(consulta))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h1>Autorizado.</h1><p>Pode fechar esta aba e voltar ao terminal.</p>".encode())

    def log_message(self, *_args):
        return


def main() -> int:
    cliente = config.SPOTIFY_CLIENT_ID or input("Client ID do app Spotify: ").strip()
    if not cliente:
        print("Faltou o client id (ou preencha SPOTIFY_CLIENT_ID no .env).")
        return 1
    verificador = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(
        hashlib.sha256(verificador.encode()).digest()).decode().rstrip("=")
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": cliente, "response_type": "code", "redirect_uri": REDIRECT,
        "scope": ESCOPOS, "code_challenge_method": "S256", "code_challenge": desafio,
    })
    print(f"Abrindo o navegador. Se não abrir, acesse:\n{url}\n")
    webbrowser.open(url)
    HTTPServer(("127.0.0.1", 8888), _Callback).handle_request()
    codigo = (_codigo.get("code") or [""])[0]
    if not codigo:
        print(f"O Spotify não devolveu o código: {_codigo}")
        return 1
    pedido = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": codigo,
            "redirect_uri": REDIRECT, "client_id": cliente,
            "code_verifier": verificador,
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(pedido, timeout=15) as resposta:
        dados = json.loads(resposta.read().decode())
    if "refresh_token" not in dados:
        print(f"Resposta sem refresh token: {dados}")
        return 1
    print("\nGuarde no cofre (Configurações → Spotify):")
    print(f"  SPOTIFY_CLIENT_ID={cliente}")
    print(f"  SPOTIFY_REFRESH={dados['refresh_token']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
