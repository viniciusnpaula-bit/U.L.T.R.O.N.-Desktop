"""Sincroniza a instalação local do ULTRON (pasta do usuário) sem tocar em dados.

Copia só código e assets (mesma lista do atualizador): venv, node_modules, dados,
logs, .env e build ficam intactos. Cada arquivo substituído é guardado em
~/ULTRON-backup-manual/<data> antes da troca.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ORIGEM = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
DESTINO = Path(sys.argv[2] if len(sys.argv) > 2 else r"C:/U.L.T.R.O.N/U.L.T.R.O.N._Desktop_All_Versions")

PROTEGIDOS = {"venv", "node_modules", "dados", "logs", ".git", "build", "__pycache__", ".pytest_cache"}
SUFIXOS = {".py", ".js", ".mjs", ".json", ".html", ".css", ".svg", ".png", ".ico", ".md", ".txt",
           ".bat", ".ps1", ".exe", ".toml", ".cfg", ".woff", ".woff2"}
NUNCA = {".env", ".ultron-state.json"}


def main() -> int:
    if not DESTINO.is_dir():
        print(f"destino não existe: {DESTINO}")
        return 1
    backup = Path.home() / "ULTRON-backup-manual" / time.strftime("%Y%m%d-%H%M%S")
    copiados = iguais = 0
    for arquivo in sorted(ORIGEM.rglob("*")):
        relativo = arquivo.relative_to(ORIGEM)
        if any(parte in PROTEGIDOS for parte in relativo.parts):
            continue
        if not arquivo.is_file() or arquivo.suffix.lower() not in SUFIXOS:
            continue
        if arquivo.name in NUNCA:
            continue
        destino = DESTINO / relativo
        if destino.is_file():
            try:
                if destino.read_bytes() == arquivo.read_bytes():
                    iguais += 1
                    continue
            except OSError:
                pass
            alvo = backup / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destino, alvo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(arquivo, destino)
        copiados += 1
    print(f"copiados {copiados} · já iguais {iguais} · backup em {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
