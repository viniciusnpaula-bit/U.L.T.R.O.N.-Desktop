"""Arquivos: compactar, descompactar e organizar por tipo — com limites e sem sobrescrever.

Regras que valem para todas as funções daqui:
  * nada é sobrescrito: destino existente faz a operação parar e explicar o motivo;
  * ZIP malicioso (caminho absoluto, "..", link simbólico) é recusado ANTES de extrair;
  * limites de tamanho e de quantidade evitam zip-bomb e pasta gigante;
  * a allowlist e os caminhos protegidos são decididos em `ferramentas.py`, não aqui.
"""
from __future__ import annotations

import os
import shutil
import stat
import zipfile
from pathlib import Path

MAX_BYTES = 2 * 1024 ** 3          # 2 GB descompactados
MAX_ARQUIVOS = 5000                # entradas por ZIP
MAX_COMPACTAR = 5000               # arquivos por compactação

CATEGORIAS = {
    "Imagens": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"},
    "Vídeos": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "Áudios": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
    "Documentos": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"},
    "Compactados": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Instaladores": {".exe", ".msi", ".bat", ".cmd"},
}


def categoria(sufixo: str) -> str:
    """Pasta de destino de um arquivo, pelo sufixo."""
    s = (sufixo or "").lower()
    for nome, sufixos in CATEGORIAS.items():
        if s in sufixos:
            return nome
    return "Outros"


def nome_livre(destino: Path) -> Path:
    """`destino` se estiver livre; senão "nome (2).ext", "nome (3).ext"..."""
    if not destino.exists():
        return destino
    for numero in range(2, 1000):
        candidato = destino.with_name(f"{destino.stem} ({numero}){destino.suffix}")
        if not candidato.exists():
            return candidato
    raise FileExistsError(f"não há nome livre para {destino.name}")


def plano_organizacao(pasta: Path) -> dict[str, list[Path]]:
    """Agrupa os arquivos soltos da pasta por categoria. Não move nada."""
    plano: dict[str, list[Path]] = {}
    for item in sorted(pasta.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_file() or item.is_symlink():
            continue
        plano.setdefault(categoria(item.suffix), []).append(item)
    return plano


def organizar(pasta: Path) -> dict:
    """Move os arquivos soltos para subpastas por tipo. Devolve o que aconteceu.

    `movimentos` e `pastas_criadas` existem para o diário de desfazer: sem eles
    não dá para devolver cada arquivo ao lugar exato sem adivinhar.
    """
    plano = plano_organizacao(pasta)
    movidos: dict[str, int] = {}
    erros: list[str] = []
    movimentos: list[dict] = []
    pastas_criadas: list[str] = []
    for grupo, itens in sorted(plano.items()):
        alvo_pasta = pasta / grupo
        existia = alvo_pasta.exists()
        try:
            alvo_pasta.mkdir(exist_ok=True)
        except OSError as erro:
            erros.append(f"{grupo}: não consegui criar a pasta ({erro.strerror or erro})")
            continue
        if not existia:
            pastas_criadas.append(str(alvo_pasta))
        for item in itens:
            try:
                destino = nome_livre(alvo_pasta / item.name)
                shutil.move(str(item), str(destino))
                movidos[grupo] = movidos.get(grupo, 0) + 1
                movimentos.append({"de": str(item), "para": str(destino)})
            except OSError as erro:
                erros.append(f"{item.name}: {erro.strerror or erro}")
    return {"movidos": movidos, "erros": erros, "total": sum(movidos.values()),
            "movimentos": movimentos, "pastas_criadas": pastas_criadas}


def _tamanho_arvore(origem: Path) -> tuple[int, int]:
    """(bytes, arquivos) de uma árvore, sem seguir links simbólicos."""
    if origem.is_file():
        return origem.stat().st_size, 1
    total = arquivos = 0
    for raiz, pastas, nomes in os.walk(origem, followlinks=False):
        pastas[:] = [p for p in pastas if not Path(raiz, p).is_symlink()]
        for nome in nomes:
            caminho = Path(raiz, nome)
            if caminho.is_symlink():
                continue
            total += caminho.stat().st_size
            arquivos += 1
    return total, arquivos


def compactar(origem: Path, destino: Path | None = None) -> dict:
    """Compacta arquivo ou pasta em um .zip. Recusa sobrescrever e recusa árvore enorme."""
    if not origem.exists():
        return {"ok": False, "motivo": f"não existe: {origem}"}
    destino = destino or origem.with_name(origem.name + ".zip")
    if destino.exists():
        return {"ok": False, "motivo": f"o destino já existe: {destino.name}"}
    if destino.suffix.lower() != ".zip":
        return {"ok": False, "motivo": "o destino precisa terminar em .zip"}

    total, arquivos = _tamanho_arvore(origem)
    if arquivos > MAX_COMPACTAR:
        return {"ok": False, "motivo": f"são {arquivos} arquivos; o limite é {MAX_COMPACTAR}"}
    if total > MAX_BYTES:
        return {"ok": False, "motivo": f"são {total / 1024 ** 3:.1f} GB; o limite é 2 GB"}

    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            if origem.is_file():
                z.write(origem, arcname=origem.name)
            else:
                for raiz, pastas, nomes in os.walk(origem, followlinks=False):
                    pastas[:] = sorted(p for p in pastas if not Path(raiz, p).is_symlink())
                    for nome in sorted(nomes):
                        caminho = Path(raiz, nome)
                        if caminho.is_symlink() or caminho == destino:
                            continue
                        z.write(caminho, arcname=str(Path(origem.name) / caminho.relative_to(origem)))
    except OSError as erro:
        destino.unlink(missing_ok=True)
        return {"ok": False, "motivo": f"falha ao gravar o ZIP ({erro.strerror or erro})"}
    return {"ok": True, "destino": destino, "arquivos": arquivos,
            "bytes": destino.stat().st_size}


def _entrada_segura(nome: str, destino: Path) -> bool:
    """O nome dentro do ZIP aponta para fora do destino? (zip-slip)"""
    if not nome or nome.startswith(("/", "\\")) or ":" in nome.split("/")[0]:
        return False
    alvo = (destino / nome).resolve()
    return alvo == destino.resolve() or destino.resolve() in alvo.parents


def descompactar(arquivo: Path, destino: Path | None = None) -> dict:
    """Extrai um .zip depois de validar todas as entradas. Não sobrescreve nada."""
    if not arquivo.is_file():
        return {"ok": False, "motivo": f"não existe: {arquivo}"}
    if arquivo.suffix.lower() != ".zip":
        return {"ok": False, "motivo": "por segurança, só extraio .zip"}
    if not zipfile.is_zipfile(arquivo):
        return {"ok": False, "motivo": "o arquivo não é um ZIP válido"}
    destino = destino or arquivo.with_suffix("")
    if destino.exists() and any(destino.iterdir()):
        return {"ok": False, "motivo": f"a pasta de destino não está vazia: {destino.name}"}

    with zipfile.ZipFile(arquivo) as z:
        entradas = z.infolist()
        if len(entradas) > MAX_ARQUIVOS:
            return {"ok": False, "motivo": f"o ZIP tem {len(entradas)} entradas; o limite é {MAX_ARQUIVOS}"}
        total = 0
        for info in entradas:
            if not _entrada_segura(info.filename, destino):
                return {"ok": False, "motivo": f"entrada insegura no ZIP: {info.filename}"}
            if stat.S_ISLNK(info.external_attr >> 16):
                return {"ok": False, "motivo": f"o ZIP contém um link simbólico: {info.filename}"}
            total += info.file_size
            if total > MAX_BYTES:
                return {"ok": False, "motivo": "o conteúdo passa de 2 GB; recusei extrair"}

        destino.mkdir(parents=True, exist_ok=True)
        extraidos = 0
        for info in entradas:
            alvo = (destino / info.filename).resolve()
            if info.is_dir():
                alvo.mkdir(parents=True, exist_ok=True)
                continue
            if alvo.exists():
                return {"ok": False, "motivo": f"já existe um arquivo com esse nome: {info.filename}"}
            alvo.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as origem, open(alvo, "wb") as saida:
                shutil.copyfileobj(origem, saida, length=1024 * 1024)
            extraidos += 1
    return {"ok": True, "destino": destino, "arquivos": extraidos}
