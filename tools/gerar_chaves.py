"""Gera o par de chaves Ed25519 usado para assinar as atualizações do ULTRON.

    python tools/gerar_chaves.py            # cria (ou mostra) o par
    python tools/gerar_chaves.py --forcar   # troca o par (invalida Releases antigos)

A chave privada NUNCA vai para o repositório: fica em %USERPROFILE%\\.ultron-signing
(ou em ULTRON_SIGNING_DIR). Só a pública entra no código, na constante
CHAVE_PUBLICA_ATUALIZACAO de atualizacao.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assinatura


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forcar", action="store_true", help="substitui o par existente")
    args = parser.parse_args()
    try:
        privada, publica, base64_pub = assinatura.gerar_par(forcar=args.forcar)
    except FileExistsError as erro:
        print(erro)
        print(f"Chave pública atual: {assinatura.caminho_publica().read_text(encoding='utf-8').strip()}")
        return 1
    print(f"Chave privada: {privada}   (NUNCA versione este arquivo)")
    print(f"Chave pública: {publica}")
    print()
    print("Cole esta linha em atualizacao.py, constante CHAVE_PUBLICA_ATUALIZACAO:")
    print(f'CHAVE_PUBLICA_ATUALIZACAO = "{base64_pub}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
