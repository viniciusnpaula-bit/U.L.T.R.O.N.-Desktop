"""Backup guiado do histórico local do ULTRON.

    python tools/backup_dados.py                  # cria backups/ultron-dados-<data>.zip
    python tools/backup_dados.py --saida D:\\x.zip

O ZIP leva `dados/ultron.db` e `dados/.cofre.chave` JUNTOS: sem a chave o
histórico fica ilegível. Guarde o arquivo em local seguro — quem tiver os dois
consegue ler as mensagens na mesma conta Windows do mesmo PC.
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = ROOT / "dados"
ARQUIVOS = ("ultron.db", ".cofre.chave")


def criar_backup(destino: Path, dados: Path = DADOS) -> Path:
    """Grava um ZIP com o banco e a chave; devolve o caminho do arquivo."""
    presentes = [dados / nome for nome in ARQUIVOS if (dados / nome).is_file()]
    if not any(arquivo.name == "ultron.db" for arquivo in presentes):
        raise FileNotFoundError("dados/ultron.db não existe: nada para salvar.")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    with zipfile.ZipFile(temporario, "w", zipfile.ZIP_DEFLATED) as pacote:
        for arquivo in presentes:
            pacote.write(arquivo, arcname=f"dados/{arquivo.name}")
        raiz_skills = dados / "skills"
        if raiz_skills.is_dir():
            for caminho in raiz_skills.rglob("*"):
                if caminho.is_file():
                    pacote.write(caminho, arcname=f"dados/skills/{caminho.relative_to(raiz_skills).as_posix()}")
    temporario.replace(destino)
    return destino


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=None,
                        help="arquivo .zip de destino (padrão: backups/ultron-dados-<data>.zip)")
    args = parser.parse_args()
    destino = args.saida or ROOT / "backups" / f"ultron-dados-{datetime.now():%Y%m%d-%H%M%S}.zip"
    try:
        caminho = criar_backup(destino)
    except (OSError, FileNotFoundError) as erro:
        print(f"Backup não criado: {erro}")
        return 1
    print(f"Backup criado: {caminho}")
    if not (DADOS / ".cofre.chave").is_file():
        print("aviso: dados/.cofre.chave ausente — o ZIP só tem o banco.")
    print("Contém dados/ultron.db e dados/.cofre.chave — guarde em local seguro.")
    print("Restaurar: feche o ULTRON, copie os dois arquivos de volta para dados/ e abra o app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
