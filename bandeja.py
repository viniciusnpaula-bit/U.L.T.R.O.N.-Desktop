"""Ícone na bandeja do sistema (perto do relógio): pausar/retomar escuta, abrir logs, sair."""
import os
from pathlib import Path

import pystray
from PIL import Image

import config


def _caminho_icone():
    candidatos = (
        Path(config.BASE) / "U.L.T.R.O.N.-Logo.png",
        Path(config.BASE) / "electron" / "site" / "icons" / "ULTRON-Logo.png",
        Path(config.BASE) / "electron" / "assets" / "ULTRON.ico",
        Path(config.BASE) / "ULTRON-Logo-icon.png",
    )
    for p in candidatos:
        if p.is_file():
            return p
    return None


def _icone(_ativo=True):
    caminho = _caminho_icone()
    if caminho and caminho.is_file():
        try:
            with Image.open(caminho) as logo:
                return logo.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            pass
    # fallback em memória caso nenhum arquivo de imagem esteja acessível
    return Image.new("RGBA", (64, 64), (180, 20, 40, 255) if _ativo else (80, 80, 80, 255))


def executar(pausado):
    """Mostra o ícone e bloqueia até o usuário escolher 'Sair'."""
    def alternar(icon, item):
        pausado.clear() if pausado.is_set() else pausado.set()
        icon.icon = _icone(not pausado.is_set())
        icon.title = "Ultron: pausado" if pausado.is_set() else "Ultron: ouvindo"

    def texto_pausa(item):
        return "Retomar escuta" if pausado.is_set() else "Pausar escuta"

    def _abrir_logs(icon, item):
        pasta_logs = getattr(config, "DIR_LOGS", Path(config.BASE) / "logs")
        pasta_logs.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(pasta_logs))

    menu = pystray.Menu(
        pystray.MenuItem(texto_pausa, alternar, default=True),
        pystray.MenuItem("Abrir pasta de logs", _abrir_logs),
        pystray.MenuItem("Sair do Ultron", lambda icon, item: icon.stop()),
    )
    pystray.Icon("ultron", _icone(True), "Ultron: ouvindo", menu).run()
