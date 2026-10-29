"""Define o PIN do ULTRON como hash PBKDF2 no .env (sem gravar o PIN em texto).

    python tools/definir_pin.py            # pede o PIN duas vezes e grava o hash
    python tools/definir_pin.py --remover  # apaga ULTRON_PIN e ULTRON_PIN_HASH

O PIN nunca é impresso nem ecoado: a entrada usa getpass. O .env guarda apenas
`ULTRON_PIN_HASH=pbkdf2_sha256$iteracoes$salt$hash`.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
ITERACOES = 260_000
NOMES = ("ULTRON_PIN", "ULTRON_PIN_HASH")


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode().rstrip("=")


def gerar_hash(pin: str, iteracoes: int = ITERACOES) -> str:
    """Gera 'pbkdf2_sha256$iteracoes$salt$hash' com salt aleatório."""
    salt = secrets.token_bytes(16)
    chave = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iteracoes)
    return f"pbkdf2_sha256${iteracoes}${_b64(salt)}${_b64(chave)}"


def _sem_linhas_de_pin(linhas: list[str]) -> list[str]:
    return [linha for linha in linhas if linha.split("=", 1)[0].strip() not in NOMES]


def gravar_hash(caminho: Path, valor: str) -> None:
    """Troca ULTRON_PIN/ULTRON_PIN_HASH por uma única linha de hash (escrita atômica)."""
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    linhas = _sem_linhas_de_pin(linhas)
    linhas.append(f"ULTRON_PIN_HASH={valor}")
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    os.replace(temporario, caminho)


def remover_pin(caminho: Path) -> None:
    if not caminho.exists():
        return
    linhas = _sem_linhas_de_pin(caminho.read_text(encoding="utf-8").splitlines())
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    os.replace(temporario, caminho)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remover", action="store_true", help="apaga o PIN configurado")
    args = parser.parse_args()
    if args.remover:
        remover_pin(ENV)
        print("PIN removido do .env.")
        return 0
    try:
        pin = getpass.getpass("Novo PIN: ")
        confirmacao = getpass.getpass("Repita o PIN: ")
    except (EOFError, KeyboardInterrupt):
        print("Cancelado.")
        return 1
    if pin != confirmacao:
        print("Os PINs não coincidem. Nada foi alterado.")
        return 1
    if not 4 <= len(pin.strip()) <= 64:
        print("O PIN deve ter de 4 a 64 caracteres. Nada foi alterado.")
        return 1
    gravar_hash(ENV, gerar_hash(pin.strip()))
    print("PIN salvo como hash em .env. O PIN não foi impresso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
