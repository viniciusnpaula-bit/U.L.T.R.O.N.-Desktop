"""Palco: mostra vídeo, imagem, PDF, site ou texto dentro da interface.

O palco não abre nada sozinho: quem pede é o núcleo, por uma ferramenta. Aqui
ficam só as decisões de segurança e o estado que a interface desenha.

Segurança:
  * arquivo local precisa existir, ter extensão de mídia e não estar em área
    protegida (Windows, AppData, .ssh, o próprio ULTRON);
  * site/vídeo remoto só em http/https, sem usuário/senha na URL e sem
    localhost/rede privada (a mesma checagem do navegador controlado);
  * a interface recebe um id opaco, nunca o caminho absoluto do arquivo;
  * texto é texto: a interface usa textContent, então nada vira HTML.
"""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import BASE

PALCO_DIR = BASE / "dados" / "palco"
MANIFEST = PALCO_DIR / "manifest.json"

_MAX_TEXTO = 20_000
_MAX_ENTRADAS = 40
_TTL = 12 * 3600
_ID = re.compile(r"^[a-f0-9]{32}$")
_EXT = {
    "video": {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ogv"},
    "imagem": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    "pdf": {".pdf"},
}
_MIME = {
    ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".mov": "video/quicktime", ".m4v": "video/x-m4v", ".ogv": "video/ogg",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".pdf": "application/pdf",
}

_eventos: "queue.Queue[dict]" = queue.Queue()
_trava = threading.Lock()
_atual: dict | None = None


def _erro(mensagem: str) -> dict:
    return {"ok": False, "erro": mensagem}


def _texto_limpo(valor: str) -> str:
    """Remove caracteres de controle, preservando quebras de linha e tabulação."""
    return "".join(c for c in str(valor or "") if c in "\n\t" or ord(c) >= 32)[:_MAX_TEXTO]


def _titulo_limpo(valor: str, padrao: str = "") -> str:
    """Título em uma linha: sem controles, sem espaços repetidos."""
    texto = " ".join(_texto_limpo(valor).split())
    return (texto or padrao)[:120]


def _caminho(alvo: str) -> Path:
    """Resolve o caminho do mesmo jeito que as ferramentas de arquivo."""
    import ferramentas  # import tardio: evita ciclo na carga do módulo
    return ferramentas._caminho(alvo)


def _protegido(alvo: str) -> bool:
    import ferramentas
    return ferramentas._protegido(alvo)


def _ler_manifest() -> dict:
    try:
        dados = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def _gravar_manifest(dados: dict) -> None:
    PALCO_DIR.mkdir(parents=True, exist_ok=True)
    temporario = MANIFEST.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporario, MANIFEST)


def _podar(dados: dict) -> dict:
    agora = time.time()
    limpos = {
        chave: valor for chave, valor in dados.items()
        if isinstance(valor, dict) and float(valor.get("expira") or 0) > agora
    }
    if len(limpos) > _MAX_ENTRADAS:
        ordenados = sorted(limpos.items(), key=lambda item: float(item[1].get("criado") or 0))
        limpos = dict(ordenados[-_MAX_ENTRADAS:])
    return limpos


def _registrar(caminho: Path, tipo: str) -> str:
    identificador = secrets.token_hex(16)
    with _trava:
        dados = _podar(_ler_manifest())
        dados[identificador] = {
            "caminho": str(caminho),
            "tipo": tipo,
            "criado": time.time(),
            "expira": time.time() + _TTL,
        }
        _gravar_manifest(dados)
    return identificador


def _emitir(evento: dict) -> None:
    """Entrega um evento à interface sem deixar a fila crescer sem limite.

    Fora do Desktop ninguém consome esta fila; o teto evita que um uso longo do
    modo console acumule estado antigo indefinidamente.
    """
    while _eventos.qsize() > 32:
        try:
            _eventos.get_nowait()
        except queue.Empty:
            break
    _eventos.put(evento)


def _publicar(dados: dict) -> dict:
    global _atual
    with _trava:
        _atual = dados
    _emitir({"type": "palco_show", "palco": dict(dados)})
    return {"ok": True, "palco": dict(dados)}


def estado() -> dict | None:
    """Estado atual do palco (a interface usa para restaurar depois de um reload)."""
    with _trava:
        return dict(_atual) if _atual else None


def eventos() -> list[dict]:
    """Eventos pendentes para o runtime entregar à interface."""
    saida: list[dict] = []
    while True:
        try:
            saida.append(_eventos.get_nowait())
        except queue.Empty:
            return saida


def fechar() -> dict:
    global _atual
    with _trava:
        _atual = None
    _emitir({"type": "palco_hide"})
    return {"ok": True, "mensagem": "Palco fechado."}


def _youtube_id(url: str) -> str:
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        candidato = partes.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "youtube-nocookie.com", "m.youtube.com"}:
        if partes.path == "/watch":
            candidato = (parse_qs(partes.query).get("v") or [""])[0]
        else:
            candidato = ""
            for prefixo in ("/embed/", "/shorts/", "/live/"):
                if partes.path.startswith(prefixo):
                    candidato = partes.path[len(prefixo):].split("/")[0]
                    break
    else:
        candidato = ""
    return candidato if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidato or "") else ""


def _vimeo_id(url: str) -> str:
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    if host not in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        return ""
    achado = re.search(r"/(\d{4,12})(?:$|[/?#])", partes.path + "/")
    return achado.group(1) if achado else ""


def _url_remota(alvo: str) -> str:
    """Valida uma URL com a mesma régua do navegador controlado."""
    import navegador
    return navegador.validar_url(alvo)


def _tipo_por_extensao(caminho: Path) -> str:
    extensao = caminho.suffix.lower()
    for tipo, extensoes in _EXT.items():
        if extensao in extensoes:
            return tipo
    return ""


def _midia_mais_recente(pasta: Path, tipo: str = "") -> tuple[str, Path] | None:
    """Escolhe o arquivo de mídia mais recente da pasta, sem entrar em subpastas."""
    tipos = {tipo: _EXT[tipo]} if tipo in _EXT else _EXT
    melhor = None
    try:
        for item in pasta.iterdir():
            try:
                if not item.is_file() or item.is_symlink():
                    continue
                extensao = item.suffix.lower()
                achado = next((nome for nome, exts in tipos.items() if extensao in exts), "")
                if not achado:
                    continue
                chave = (item.stat().st_mtime, item.name.lower())
                if melhor is None or chave > melhor[0]:
                    melhor = (chave, achado, item)
            except OSError:
                continue
    except OSError:
        return None
    return (melhor[1], melhor[2]) if melhor else None


def _mostrar_local(tipo: str, alvo: str, titulo: str) -> dict:
    try:
        caminho = _caminho(alvo)
    except Exception:
        return _erro("Não consegui entender esse caminho.")
    if _protegido(str(caminho)):
        return _erro("Não mostro arquivos de uma área protegida do sistema.")
    de_pasta = caminho.is_dir()
    if de_pasta:
        achado = _midia_mais_recente(caminho, tipo)
        if not achado:
            if tipo in _EXT:
                return _erro(f"Não encontrei nenhum {tipo} na pasta {caminho}.")
            return _erro(f"Não encontrei vídeo, imagem ou PDF na pasta {caminho}.")
        tipo, caminho = achado
    elif tipo not in _EXT:
        return _erro("Não reconheci o tipo. Diga vídeo, imagem, pdf, site ou texto.")
    if not caminho.is_file():
        return _erro(f"Arquivo não encontrado: {caminho}")
    if _protegido(str(caminho)):
        return _erro("Não mostro arquivos de uma área protegida do sistema.")
    extensao = caminho.suffix.lower()
    if extensao not in _EXT.get(tipo, set()):
        return _erro(f"Esse arquivo não é um {tipo} que eu saiba mostrar.")
    identificador = _registrar(caminho, tipo)
    dados = {
        "id": identificador,
        "tipo": tipo,
        "titulo": _titulo_limpo(titulo, caminho.name),
        "fonte": f"ultron-palco://media/{identificador}",
        "url": "",
        "embed": False,
        "nota": "arquivo local — nada saiu do computador",
    }
    _publicar(dados)
    if de_pasta:
        mensagem = f"Mostrando o {tipo} mais recente da pasta: '{dados['titulo']}' no palco."
    else:
        mensagem = f"Mostrando {tipo} '{dados['titulo']}' no palco."
    return {"ok": True, "mensagem": mensagem, "palco": dados}


def mostrar(tipo: str = "auto", alvo: str = "", titulo: str = "") -> dict:
    """Mostra algo no palco. Devolve um dicionário com ok/mensagem/erro."""
    tipo = str(tipo or "auto").strip().lower()
    alvo = str(alvo or "").strip()
    titulo = _titulo_limpo(titulo)

    if tipo in {"fechar", "fechar_palco", "limpar"}:
        return fechar()
    if tipo == "texto":
        conteudo = _texto_limpo(alvo)
        if not conteudo.strip():
            return _erro("Não há texto para mostrar.")
        dados = {
            "id": secrets.token_hex(16),
            "tipo": "texto",
            "titulo": titulo or "texto",
            "fonte": "",
            "url": "",
            "embed": False,
            "conteudo": conteudo,
            "nota": "texto do núcleo",
        }
        _publicar(dados)
        return {"ok": True, "mensagem": "Texto mostrado no palco.", "palco": dados}
    if not alvo:
        return _erro("Faltou o que mostrar (caminho, URL ou texto).")

    remoto = alvo.lower().startswith(("http://", "https://"))
    if tipo == "auto":
        if remoto:
            tipo = "site"
        else:
            try:
                caminho_alvo = _caminho(alvo)
            except Exception:
                return _erro("Não consegui entender esse caminho.")
            if caminho_alvo.is_dir():
                tipo = ""   # _mostrar_local escolhe pelo conteúdo da pasta
            else:
                tipo = _tipo_por_extensao(caminho_alvo)
                if not tipo:
                    return _erro("Não reconheci o tipo. Diga vídeo, imagem, pdf, site ou texto.")

    if tipo == "site":
        try:
            url = _url_remota(alvo)
        except Exception as erro:
            return _erro(str(erro))
        dados = {
            "id": secrets.token_hex(16),
            "tipo": "site",
            "titulo": titulo or (urlparse(url).hostname or "site"),
            "fonte": url,
            "url": url,
            "embed": False,
            "nota": "site externo em área isolada; ele pode recusar exibição embutida",
        }
        _publicar(dados)
        return {"ok": True, "mensagem": f"Mostrando o site {url} no palco.", "palco": dados}

    if tipo in {"", "video", "imagem", "pdf"}:
        if remoto:
            try:
                url = _url_remota(alvo)
            except Exception as erro:
                return _erro(str(erro))
            if tipo == "video":
                video_id = _youtube_id(url)
                if video_id:
                    embed = f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&rel=0"
                    dados = {
                        "id": secrets.token_hex(16), "tipo": "video",
                        "titulo": titulo or "vídeo do YouTube", "fonte": embed,
                        "url": url, "embed": True,
                        "nota": "YouTube em modo de privacidade (youtube-nocookie)",
                    }
                    _publicar(dados)
                    return {"ok": True, "mensagem": "Vídeo do YouTube no palco.", "palco": dados}
                vimeo_id = _vimeo_id(url)
                if vimeo_id:
                    embed = f"https://player.vimeo.com/video/{vimeo_id}?autoplay=1"
                    dados = {
                        "id": secrets.token_hex(16), "tipo": "video",
                        "titulo": titulo or "vídeo do Vimeo", "fonte": embed,
                        "url": url, "embed": True,
                        "nota": "Vimeo em área isolada",
                    }
                    _publicar(dados)
                    return {"ok": True, "mensagem": "Vídeo do Vimeo no palco.", "palco": dados}
                if Path(urlparse(url).path).suffix.lower() in _EXT["video"]:
                    dados = {
                        "id": secrets.token_hex(16), "tipo": "video",
                        "titulo": titulo or "vídeo", "fonte": url,
                        "url": url, "embed": False,
                        "nota": "vídeo externo",
                    }
                    _publicar(dados)
                    return {"ok": True, "mensagem": "Vídeo externo no palco.", "palco": dados}
                return _erro("Para vídeo externo, use YouTube, Vimeo ou um link direto .mp4/.webm.")
            if tipo == "imagem":
                dados = {
                    "id": secrets.token_hex(16), "tipo": "imagem",
                    "titulo": titulo or "imagem", "fonte": url,
                    "url": url, "embed": False,
                    "nota": "imagem externa",
                }
                _publicar(dados)
                return {"ok": True, "mensagem": "Imagem no palco.", "palco": dados}
            dados = {
                "id": secrets.token_hex(16), "tipo": "pdf",
                "titulo": titulo or "PDF", "fonte": url,
                "url": url, "embed": False,
                "nota": "PDF externo",
            }
            _publicar(dados)
            return {"ok": True, "mensagem": "PDF no palco.", "palco": dados}
        return _mostrar_local(tipo, alvo, titulo)

    return _erro("Tipo desconhecido. Use vídeo, imagem, pdf, site, texto ou fechar.")
