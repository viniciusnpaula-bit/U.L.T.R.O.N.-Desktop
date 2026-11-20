"""Descoberta e lançamento de programas e jogos instalados no Windows."""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import time
import unicodedata
from pathlib import Path

import seguranca

_cache_apps = {"t": 0.0, "dados": {}}
_IGNORAR_APPS = ("uninstall", "desinstal", "redistributable", "steamworks", "readme", "leia-me", "leiame")


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def _apps_menu_iniciar():
    """Apps do Menu Iniciar (inclui Microsoft Store) via PowerShell Get-StartApps."""
    cmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=25,
        creationflags=0x08000000,
    )
    dados = json.loads(r.stdout or "[]")
    if isinstance(dados, dict):
        dados = [dados]
    return {d["Name"]: ("appid", d["AppID"]) for d in dados if d.get("Name") and d.get("AppID")}


def _atalhos_arquivos():
    """Atalhos (.lnk/.url) do Menu Iniciar e da Área de Trabalho."""
    pastas = [
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%PUBLIC%\Desktop"),
        str(Path.home() / "Desktop"),
        str(Path.home() / "OneDrive" / "Desktop"),
    ]
    achados = {}
    for pasta in pastas:
        p = Path(pasta)
        if not p.is_dir():
            continue
        for ext in ("*.lnk", "*.url"):
            for f in p.rglob(ext):
                achados[f.stem] = ("arquivo", str(f))
    return achados


def _jogos_steam(base=None):
    jogos = {}
    if base is None:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                base = Path(winreg.QueryValueEx(k, "SteamPath")[0])
        except Exception:
            base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
    bibliotecas = {Path(base)}
    try:
        txt = (Path(base) / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
            bibliotecas.add(Path(m.group(1).replace("\\\\", "\\")))
    except Exception:
        pass
    for lib in bibliotecas:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                t = acf.read_text(encoding="utf-8", errors="replace")
                a = re.search(r'"appid"\s+"(\d+)"', t)
                n = re.search(r'"name"\s+"([^"]+)"', t)
                if a and n:
                    jogos[n.group(1)] = ("uri", f"steam://rungameid/{a.group(1)}")
            except Exception:
                continue
    return jogos


def _jogos_epic(pasta=None):
    jogos = {}
    pasta = Path(pasta or os.path.expandvars(r"%ProgramData%\Epic\EpicGamesLauncher\Data\Manifests"))
    for item in pasta.glob("*.item"):
        try:
            d = json.loads(item.read_text(encoding="utf-8", errors="replace"))
            nome = d.get("DisplayName")
            if nome and d.get("CatalogNamespace") and d.get("CatalogItemId") and d.get("AppName"):
                jogos[nome] = (
                    "uri",
                    f"com.epicgames.launcher://apps/{d['CatalogNamespace']}%3A"
                    f"{d['CatalogItemId']}%3A{d['AppName']}?action=launch&silent=true",
                )
        except Exception:
            continue
    return jogos


def _catalogo(forcar=False):
    """Lista de tudo que dá para abrir: {nome_normalizado: (nome, tipo, valor)}."""
    if not forcar and _cache_apps["dados"] and time.time() - _cache_apps["t"] < 600:
        return _cache_apps["dados"]
    cat = {}
    for fonte in (_apps_menu_iniciar, _atalhos_arquivos, _jogos_steam, _jogos_epic):
        try:
            for nome, (tipo, valor) in fonte().items():
                if any(x in nome.lower() for x in _IGNORAR_APPS):
                    continue
                cat[_norm(nome)] = (nome, tipo, valor)
        except Exception as e:
            seguranca.log.warning(f"Catálogo de apps ({fonte.__name__}): {e}")
    cat.pop("", None)
    _cache_apps.update(t=time.time(), dados=cat)
    seguranca.log.info(f"Catálogo de apps carregado: {len(cat)} itens")
    return cat


def _buscar(cat, nome):
    n = _norm(nome)
    if not n:
        return None, 0.0
    if n in cat:
        return cat[n], 1.0
    contem = [k for k in cat if n in k or (len(k) >= 4 and k in n)]
    if contem:
        return cat[min(contem, key=len)], 0.9
    prox = difflib.get_close_matches(n, list(cat), n=1, cutoff=0.7)
    return (cat[prox[0]], 0.75) if prox else (None, 0.0)


def _resolver_app(nome, catalog_fn=None):
    obter_cat = catalog_fn or _catalogo
    item, score = _buscar(obter_cat(), nome)
    if not item and time.time() - _cache_apps["t"] > 30:   # talvez tenha acabado de instalar
        item, score = _buscar(obter_cat(forcar=True), nome)
    return item, score


def _lancar(item):
    _, tipo, valor = item
    if tipo == "appid":
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{valor}"])
    else:
        os.startfile(valor)
