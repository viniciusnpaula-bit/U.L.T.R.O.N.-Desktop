"""Aplica a versão deste projeto numa instalação do ULTRON Desktop.

Uso no seu PC:

    python tools/aplicar_nesta_pc.py                 # atualiza a pasta padrão
    python tools/aplicar_nesta_pc.py --simular       # só mostra o que mudaria
    python tools/aplicar_nesta_pc.py --pasta "C:/outra/ultron"

O que ele faz, em ordem:
  1. confere que a pasta de destino é mesmo uma instalação do ULTRON;
  2. faz backup do código atual (só o código, não dados) em
     ~/ULTRON-backup-manual/<data>;
  3. copia só código e assets — `venv`, `node_modules`, `dados/`, `logs/`, `.env`,
     `cofre.json` e bancos ficam intocados;
  4. recompila `ULTRON.exe` e `ULTRON-Setup.exe` na instalação, se o Python local
     permitir (o `.exe` antigo é um lançador que continua funcionando de qualquer
     forma, então a falta de PyInstaller não bloqueia a atualização);
  5. roda o diagnóstico da instalação e mostra a versão final.

Nada é enviado para a internet e nenhum dado do usuário é lido ou modificado.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PADRAO = Path(r"C:/U.L.T.R.O.N/U.L.T.R.O.N._Desktop_All_Versions")
PROTEGIDAS = {"venv", "node_modules", "dados", "logs", ".git", "build", "__pycache__",
              ".pytest_cache", "dist"}
SUFIXOS = {".py", ".js", ".mjs", ".cjs", ".json", ".html", ".css", ".svg", ".png", ".ico",
           ".md", ".txt", ".bat", ".ps1", ".exe", ".toml", ".cfg", ".yml", ".yaml"}
NUNCA = {".env", "cofre.json", ".cofre.chave", ".ultron-state.json"}


def versao(pasta: Path) -> str:
    try:
        return json.loads((pasta / "electron" / "package.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return "desconhecida"


def arquivos_para_copiar(origem: Path):
    for arquivo in sorted(origem.rglob("*")):
        relativo = arquivo.relative_to(origem)
        if any(parte in PROTEGIDAS for parte in relativo.parts):
            continue
        if relativo.parts and relativo.parts[0] == "ULTRON-Mobile":
            continue
        # pastas de build antigas do electron (instaladores velhos) não fazem parte do app
        if any(parte.startswith("dist") for parte in relativo.parts[:2]):
            continue
        if not arquivo.is_file() or arquivo.suffix.lower() not in SUFIXOS:
            continue
        if arquivo.name in NUNCA:
            continue
        if arquivo.name in {"preview-mock.js", "preview.html"}:
            continue
        yield relativo, arquivo


def mesmos_bytes(a: Path, b: Path) -> bool:
    try:
        return hashlib.md5(a.read_bytes()).hexdigest() == hashlib.md5(b.read_bytes()).hexdigest()
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pasta", default=str(PADRAO), help="pasta da instalação do ULTRON")
    ap.add_argument("--simular", action="store_true", help="só mostra o que mudaria")
    ap.add_argument("--sem-exe", action="store_true", help="não tenta recompilar os .exe")
    args = ap.parse_args()

    destino = Path(args.pasta)
    if not (destino / "electron" / "package.json").is_file() or not (destino / "desktop.py").is_file():
        print(f"Esta pasta não parece uma instalação do ULTRON: {destino}")
        return 1

    print(f"origem : {RAIZ}  (versão {versao(RAIZ)})")
    print(f"destino: {destino}  (versão {versao(destino)})")

    copiar, iguais = [], 0
    for relativo, arquivo in arquivos_para_copiar(RAIZ):
        alvo = destino / relativo
        if alvo.is_file() and mesmos_bytes(arquivo, alvo):
            iguais += 1
            continue
        copiar.append((relativo, arquivo))

    print(f"{len(copiar)} arquivo(s) a atualizar · {iguais} já iguais")
    for relativo, _ in copiar[:15]:
        print("   ", relativo)
    if len(copiar) > 15:
        print(f"    … e mais {len(copiar) - 15}")
    if args.simular:
        print("\n(simulação: nada foi alterado)")
        return 0
    if not copiar:
        print("Nada a fazer: a instalação já está nesta versão.")
    else:
        backup = Path.home() / "ULTRON-backup-manual" / time.strftime("%Y%m%d-%H%M%S")
        print(f"\nbackup do código atual em {backup}")
        for relativo, arquivo in copiar:
            alvo = destino / relativo
            if alvo.is_file():
                copia = backup / relativo
                copia.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(alvo, copia)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo, alvo)
        print(f"{len(copiar)} arquivo(s) copiados.")

    if not args.sem_exe:
        python_local = destino / "venv" / "Scripts" / "python.exe"
        if python_local.is_file() and (destino / "tools" / "build_setup.py").is_file():
            print("\nrecompilando ULTRON.exe e ULTRON-Setup.exe…")
            subprocess.call([str(python_local), str(destino / "tools" / "build_setup.py")], cwd=str(destino))
        else:
            print("\n(trocar os .exe não é necessário: o lançador atual já executa a versão nova)"
                  "\n para recompilar: rode ULTRON-Setup.exe nesta pasta.")
    print(f"\nversão final: {versao(destino)}")
    launcher = destino / "ULTRON.exe"
    if launcher.is_file():
        print("diagnóstico:")
        subprocess.call([str(launcher), "--diagnostico"], cwd=str(destino))
    print("\nPronto. Abra o ULTRON pelo atalho — as chaves de API entram em Ajustes › Chaves de API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
