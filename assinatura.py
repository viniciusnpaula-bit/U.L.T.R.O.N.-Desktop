"""Assinatura Ed25519 das atualizações do ULTRON.

Por que Ed25519 com `cryptography`:
  * Ed25519 é assimétrico: a chave privada fica só na máquina de quem publica e a
    pública viaja dentro do app. Um Release comprometido (ou o GitHub fora do ar com
    um ZIP trocado) não consegue forjar assinatura — diferente do SHA-256 sozinho,
    que só prova que o arquivo chegou inteiro, não que veio de nós.
  * `cryptography` é gratuita, mantida, traz rodas prontas para Windows (sem compilar
    nada no PC do usuário) e suporta Python 3.9+ até 3.14. PyNaCl também serviria,
    mas `cryptography` já é dependência de transporte em muitos ambientes e tem
    atualizações mais frequentes para novas versões do Python.
  * Só usamos Ed25519 (sem curvas exóticas): chave pública de 32 bytes embutida em
    `CHAVE_PUBLICA_ATUALIZACAO` (atualizacao.py).

Formato do arquivo .sig: 64 bytes crus da assinatura (binário). O SHA256SUMS.txt
assinado é o arquivo exatamente como foi publicado (bytes, sem normalizar).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ASSINATURA_SUFIXO = ".sig"
TAMANHO_ASSINATURA = 64


def pasta_de_chaves() -> Path:
    """Chaves ficam FORA do repositório, por padrão em %USERPROFILE%\\.ultron-signing."""
    return Path(os.environ.get("ULTRON_SIGNING_DIR") or Path.home() / ".ultron-signing")


def caminho_privada() -> Path:
    return pasta_de_chaves() / "ultron-update.key"


def caminho_publica() -> Path:
    return pasta_de_chaves() / "ultron-update.pub"


def gerar_par(forcar: bool = False) -> tuple[Path, Path, str]:
    """Cria o par de chaves e devolve (privada, pública, pública em base64)."""
    privada, publica = caminho_privada(), caminho_publica()
    if privada.exists() and not forcar:
        raise FileExistsError(f"A chave privada já existe em {privada}. Use --forcar para trocar.")
    privada.parent.mkdir(parents=True, exist_ok=True)
    chave = Ed25519PrivateKey.generate()
    privada.write_bytes(chave.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:
        os.chmod(privada, 0o600)
    except OSError:
        pass
    crua = chave.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    publica.write_text(crua.hex() + "\n", encoding="utf-8")
    return privada, publica, base64.b64encode(crua).decode("ascii")


def carregar_privada(caminho: Path | None = None) -> Ed25519PrivateKey:
    dados = Path(caminho or caminho_privada()).read_bytes()
    if len(dados) != 32:
        raise ValueError("Arquivo de chave privada inválido (esperado 32 bytes crus).")
    return Ed25519PrivateKey.from_private_bytes(dados)


def carregar_publica_hex(hexadecimal: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hexadecimal.strip()))


def carregar_publica_base64(codigo: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(codigo))


def assinar(conteudo: bytes, privada: Ed25519PrivateKey | None = None) -> bytes:
    return (privada or carregar_privada()).sign(conteudo)


def assinar_arquivo(arquivo: Path, privada: Ed25519PrivateKey | None = None) -> Path:
    """Assina o arquivo e grava ao lado, com sufixo .sig (binário)."""
    arquivo = Path(arquivo)
    destino = arquivo.with_name(arquivo.name + ASSINATURA_SUFIXO)
    destino.write_bytes(assinar(arquivo.read_bytes(), privada))
    return destino


def verificar(conteudo: bytes, assinatura: bytes, publica: Ed25519PublicKey) -> bool:
    if not isinstance(assinatura, (bytes, bytearray)) or len(assinatura) != TAMANHO_ASSINATURA:
        return False
    try:
        publica.verify(bytes(assinatura), conteudo)
        return True
    except InvalidSignature:
        return False
