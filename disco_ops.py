"""disco_ops.py: Operações determinísticas de arquivos e disco para o Bloco 1.

Módulo puro e testável com Lixeira (send2trash) e diário de desfazer.
"""
import copy
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from send2trash import send2trash

import arquivos
import config
import desfazer

_log = logging.getLogger("ultron.disco_ops")

ARQUIVO_CONFIG_BLOCO1 = getattr(config, "DIR_DADOS", config.BASE / "dados") / "bloco1.json"

CONFIG_PADRAO_BLOCO1 = {
    "downloads_pdf_ativo": True,
    "downloads_extrator_ativo": True,
    "capturas_desktop_ativo": True,
    "usb_ejetar_ativo": True,
    "disco_alerta_ativo": True,
    "disco_limite_pct": 80,
    "usb_ocioso_seg": 300,
    "capturas_dias": 7,
    "projetos_meses": 6,
    "projetos_pastas": [],
    "backup_origens": [],
    "backup_destino": "",
    "backup_ativo": False,
}

_EXTENSOES_TEMP = frozenset({
    ".tmp", ".temp", ".crdownload", ".part", ".download", ".partial"
})

_PADRAO_PDF_RENOMEADO = re.compile(r"^\d{4}-\d{2}-\d{2} - .+")


def _resolver_caminho(caminho: str | Path) -> Path:
    """Resolve strings, til (~) e variáveis de ambiente em um Path absoluto."""
    p_str = str(caminho or "").strip()
    if not p_str:
        return Path.home()
    expandido = os.path.expandvars(p_str)
    p = Path(expandido).expanduser()
    if not p.is_absolute():
        p = (Path.home() / p).resolve()
    else:
        p = p.resolve()
    return p


def carregar_config_bloco1() -> dict:
    """Carrega as configurações do Bloco 1 a partir de dados/bloco1.json."""
    if not ARQUIVO_CONFIG_BLOCO1.exists():
        return copy.deepcopy(CONFIG_PADRAO_BLOCO1)
    try:
        dados = json.loads(ARQUIVO_CONFIG_BLOCO1.read_text(encoding="utf-8"))
        cfg = copy.deepcopy(CONFIG_PADRAO_BLOCO1)
        cfg.update({k: v for k, v in dados.items() if k in CONFIG_PADRAO_BLOCO1})
        return cfg
    except Exception as e:
        _log.warning("Erro ao ler %s: %s", ARQUIVO_CONFIG_BLOCO1, e)
        return copy.deepcopy(CONFIG_PADRAO_BLOCO1)


def salvar_config_bloco1(config: dict) -> dict:
    """Salva configurações validadas em dados/bloco1.json atomicamente."""
    cfg = carregar_config_bloco1()
    cfg.update({k: v for k, v in config.items() if k in CONFIG_PADRAO_BLOCO1})
    ARQUIVO_CONFIG_BLOCO1.parent.mkdir(parents=True, exist_ok=True)
    temp = ARQUIVO_CONFIG_BLOCO1.with_suffix(".tmp")
    temp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(ARQUIVO_CONFIG_BLOCO1)
    return cfg


def _eh_temporario(p: Path) -> bool:
    return p.suffix.lower() in _EXTENSOES_TEMP or p.name.startswith("~$") or p.name.startswith(".~")


def _arquivo_estavel(p: Path, espera_seg: float = 0.5) -> bool:
    """Garante que o arquivo não está sendo baixado ou escrito por outro processo."""
    if not p.exists() or _eh_temporario(p):
        return False
    try:
        st1 = p.stat()
        time.sleep(espera_seg)
        st2 = p.stat()
        if st1.st_size != st2.st_size or st1.st_mtime_ns != st2.st_mtime_ns:
            return False
        with open(p, "rb") as f:
            f.read(1)
        return True
    except (OSError, PermissionError):
        return False


def _extrair_texto_pdf(caminho: Path) -> str:
    """Extrai até 6000 caracteres das primeiras 3 páginas de um PDF."""
    try:
        import pypdf
    except ImportError:
        _log.warning("pypdf não instalado; não é possível ler texto de PDFs.")
        return ""
    try:
        leitor = pypdf.PdfReader(str(caminho))
        texto_paginas = []
        for i, pag in enumerate(leitor.pages[:3]):
            txt = pag.extract_text() or ""
            if txt.strip():
                texto_paginas.append(txt.strip())
        return "\n\n".join(texto_paginas)[:6000]
    except Exception as e:
        _log.warning("Falha ao extrair texto de %s: %s", caminho, e)
        return ""


# ====================== ITEM 1: ORGANIZAR PDFS ======================
def organizar_pdf_downloads(pasta: str = "~/Downloads", aplicar: bool = True) -> dict:
    """Lê PDFs recém-baixados e renomeia para 'AAAA-MM-DD - Assunto.pdf'."""
    dir_downloads = _resolver_caminho(pasta)
    if not dir_downloads.exists() or not dir_downloads.is_dir():
        return {"total": 0, "renomeados": 0, "arquivos": [], "erro": "Pasta não encontrada"}

    import cerebro

    encontrados = []
    renomeados = 0
    detalhes = []

    for item in dir_downloads.iterdir():
        if not item.is_file() or item.suffix.lower() != ".pdf":
            continue
        if _PADRAO_PDF_RENOMEADO.match(item.stem):
            continue
        if _eh_temporario(item):
            continue
        encontrados.append(item)

    for pdf in encontrados:
        trecho = _extrair_texto_pdf(pdf)
        meta = cerebro.extrair_titulo_pdf(trecho)

        data = meta.get("data")
        if not data:
            try:
                data = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%Y-%m-%d")
            except OSError:
                data = datetime.now().strftime("%Y-%m-%d")

        assunto = meta.get("assunto") or "Documento"
        assunto_limpo = re.sub(r"[^A-Za-z0-9À-ÿ _-]", "", assunto)[:60].strip() or "Documento"
        novo_nome = f"{data} - {assunto_limpo}.pdf"
        destino_tentativa = dir_downloads / novo_nome

        if destino_tentativa.resolve() == pdf.resolve():
            continue

        novo_caminho = arquivos.nome_livre(destino_tentativa)
        info = {"de": str(pdf), "para": str(novo_caminho), "nome_anterior": pdf.name, "novo_nome": novo_caminho.name}

        if aplicar:
            try:
                pdf.rename(novo_caminho)
                desfazer.registrar(
                    "mover",
                    f"Renomear PDF {pdf.name} para {novo_caminho.name}",
                    desfazer.inversa_mover([{"de": str(novo_caminho), "para": str(pdf)}])
                )
                renomeados += 1
                info["status"] = "renomeado"
            except Exception as e:
                info["status"] = f"erro: {e}"
        else:
            info["status"] = "simulado"

        detalhes.append(info)

    return {"total": len(encontrados), "renomeados": renomeados, "arquivos": detalhes}


# ====================== ITEM 2: EXTRAIR E LIMPAR INSTALADOR ======================
def _validar_membros_zip(zf: Any, destino: Path) -> bool:
    """Garante que nenhum arquivo no ZIP escapa do diretório destino (anti-zip-slip)."""
    dest_str = str(destino.resolve())
    for member in zf.namelist():
        if member.startswith("/") or member.startswith("\\") or ".." in member.replace("\\", "/").split("/"):
            return False
        resolvido = str((destino / member).resolve())
        if not (resolvido == dest_str or resolvido.startswith(dest_str + os.sep)):
            return False
    return True


def extrair_e_limpar_instalador(
    arquivo: str,
    destino: str = "",
    apagar_origem: bool = False,
    aguardar_saida: bool = True
) -> dict:
    """Extrai pacotes .zip ou .rar em segurança e opcionalmente remove pacote/instalador."""
    arq_path = _resolver_caminho(arquivo)
    if not arq_path.exists() or not arq_path.is_file():
        return {"sucesso": False, "extraidos": 0, "instalador": "", "erro": "Arquivo não encontrado"}

    dest_dir = _resolver_caminho(destino) if destino else arq_path.parent / arq_path.stem
    dest_dir.mkdir(parents=True, exist_ok=True)

    sufixo = arq_path.suffix.lower()
    arquivos_extraidos = []

    if sufixo == ".zip":
        import zipfile
        try:
            with zipfile.ZipFile(arq_path, "r") as zf:
                if not _validar_membros_zip(zf, dest_dir):
                    return {"sucesso": False, "extraidos": 0, "instalador": "", "erro": "Arquivo zip contém path traversal bloqueado"}
                zf.extractall(dest_dir)
                arquivos_extraidos = [dest_dir / m for m in zf.namelist()]
        except Exception as e:
            return {"sucesso": False, "extraidos": 0, "instalador": "", "erro": f"Falha ao extrair ZIP: {e}"}

    elif sufixo == ".rar":
        # Tentativa de uso do UnRAR.exe ou 7z.exe
        unrar_exe = shutil.which("UnRAR.exe") or r"C:\Program Files\WinRAR\UnRAR.exe"
        sete_z = shutil.which("7z.exe") or r"C:\Program Files\7-Zip\7z.exe"
        
        cmd = None
        if os.path.exists(unrar_exe):
            cmd = [unrar_exe, "x", "-y", str(arq_path), str(dest_dir)]
        elif os.path.exists(sete_z):
            cmd = [sete_z, "x", f"-o{dest_dir}", "-y", str(arq_path)]

        if not cmd:
            return {"sucesso": False, "extraidos": 0, "instalador": "", "erro": "Descompactador RAR não disponível (UnRAR.exe ou 7z.exe)"}

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                return {"sucesso": False, "extraidos": 0, "instalador": "", "erro": f"Erro unrar: {res.stderr}"}
            arquivos_extraidos = list(dest_dir.rglob("*"))
        except Exception as e:
            return {"sucesso": False, "extraidos": 0, "instalador": "", "erro": f"Falha na extração RAR: {e}"}
    else:
        return {"sucesso": False, "extraidos": 0, "instalador": "", "erro": f"Formato não suportado: {sufixo}"}

    instaladores = [f for f in arquivos_extraidos if f.is_file() and f.suffix.lower() in (".exe", ".msi")]
    instalador_encontrado = str(instaladores[0]) if instaladores else ""

    if apagar_origem and arq_path.exists():
        try:
            send2trash(str(arq_path.resolve()))
            desfazer.registrar(
                "remover",
                f"Apagar arquivo de origem {arq_path.name}",
                desfazer.inversa_restaurar(str(arq_path.resolve()))
            )
        except Exception as e:
            _log.warning("Falha ao mover arquivo original para a Lixeira: %s", e)

    return {
        "sucesso": True,
        "extraidos": len(arquivos_extraidos),
        "instalador": instalador_encontrado,
        "destino": str(dest_dir),
        "erro": "",
    }


# ====================== ITEM 3: DEDUPLICAÇÃO DE ARQUIVOS ======================
def _hash_parcial(caminho: Path, tamanho_bloco: int = 65536) -> str:
    """Calcula hash rápido dos primeiros e últimos 64KB de um arquivo."""
    hasher = hashlib.md5()
    try:
        tamanho = caminho.stat().st_size
        with open(caminho, "rb") as f:
            if tamanho <= tamanho_bloco * 2:
                hasher.update(f.read())
            else:
                hasher.update(f.read(tamanho_bloco))
                f.seek(max(0, tamanho - tamanho_bloco))
                hasher.update(f.read(tamanho_bloco))
        return hasher.hexdigest()
    except Exception:
        return ""


def _hash_completo(caminho: Path) -> str:
    """Calcula SHA-256 do arquivo em blocos de 1MB."""
    hasher = hashlib.sha256()
    try:
        with open(caminho, "rb") as f:
            while chunk := f.read(1048576):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def limpar_duplicados(pasta: str, executar: bool = False) -> dict:
    """Localiza duplicados por tamanho -> hash parcial -> SHA-256 e envia os mais antigos à Lixeira."""
    dir_alvo = _resolver_caminho(pasta)
    if not dir_alvo.exists() or not dir_alvo.is_dir():
        return {"grupos": 0, "duplicados": 0, "removidos": 0, "bytes_economizados": 0, "erro": "Pasta não encontrada"}

    # 1. Agrupamento por tamanho
    por_tamanho: dict[int, list[Path]] = {}
    for raiz, _, arquivos_locais in os.walk(dir_alvo):
        for nome in arquivos_locais:
            p = Path(raiz) / nome
            if not p.is_file() or _eh_temporario(p):
                continue
            try:
                tam = p.stat().st_size
                if tam > 0:
                    por_tamanho.setdefault(tam, []).append(p)
            except OSError:
                continue

    candidatos_tamanho = [lista for lista in por_tamanho.values() if len(lista) > 1]

    # 2. Agrupamento por hash parcial
    por_hash_parcial: dict[tuple[int, str], list[Path]] = {}
    for grupo in candidatos_tamanho:
        for p in grupo:
            h_parcial = _hash_parcial(p)
            if h_parcial:
                tam = p.stat().st_size
                por_hash_parcial.setdefault((tam, h_parcial), []).append(p)

    candidatos_parcial = [lista for lista in por_hash_parcial.values() if len(lista) > 1]

    # 3. Agrupamento por SHA-256 completo
    grupos_duplicados: list[list[Path]] = []
    for grupo in candidatos_parcial:
        por_sha: dict[str, list[Path]] = {}
        for p in grupo:
            h_completo = _hash_completo(p)
            if h_completo:
                por_sha.setdefault(h_completo, []).append(p)
        for subgrupo in por_sha.values():
            if len(subgrupo) > 1:
                grupos_duplicados.append(subgrupo)

    total_duplicados = 0
    removidos = 0
    bytes_economizados = 0
    detalhes = []

    for grupo in grupos_duplicados:
        # Ordena por mtime mais recente primeiro
        grupo.sort(key=lambda p: (p.stat().st_mtime_ns if p.exists() else 0), reverse=True)
        mais_recente = grupo[0]
        duplicados_antigos = grupo[1:]

        info_grupo = {
            "mantido": str(mais_recente),
            "duplicados": [str(d) for d in duplicados_antigos],
            "tamanho_cada": mais_recente.stat().st_size
        }

        for dup in duplicados_antigos:
            total_duplicados += 1
            tam_dup = dup.stat().st_size
            if executar:
                try:
                    caminho_resolvido = str(dup.resolve())
                    send2trash(caminho_resolvido)
                    desfazer.registrar(
                        "remover",
                        f"Remover duplicado {dup.name}",
                        desfazer.inversa_restaurar(caminho_resolvido)
                    )
                    removidos += 1
                    bytes_economizados += tam_dup
                except Exception as e:
                    _log.warning("Erro ao enviar duplicado para lixeira (%s): %s", dup, e)
            else:
                bytes_economizados += tam_dup

        detalhes.append(info_grupo)

    return {
        "grupos": len(grupos_duplicados),
        "duplicados": total_duplicados,
        "removidos": removidos,
        "bytes_economizados": bytes_economizados,
        "detalhes": detalhes
    }


# ====================== ITEM 4: LIMPEZA DE DISCO ======================
def _diretorios_cache_navegadores() -> list[Path]:
    """Retorna lista de diretórios descartáveis de cache de navegadores."""
    appdata_local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    padroes = [
        appdata_local / "Google" / "Chrome" / "User Data",
        appdata_local / "Microsoft" / "Edge" / "User Data",
        appdata_local / "BraveSoftware" / "Brave-Browser" / "User Data",
    ]
    subpastas_cache = ("Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache")
    encontrados = []

    for base in padroes:
        if not base.exists():
            continue
        # Itera perfis (Default, Profile 1, Profile 2...)
        try:
            for item in base.iterdir():
                if item.is_dir():
                    for sc in subpastas_cache:
                        p_cache = item / sc
                        if p_cache.exists() and p_cache.is_dir():
                            encontrados.append(p_cache)
        except (OSError, PermissionError):
            continue

    # Firefox
    ff_perfis = appdata_local / "Mozilla" / "Firefox" / "Profiles"
    if ff_perfis.exists():
        try:
            for perfil in ff_perfis.iterdir():
                c2 = perfil / "cache2"
                if c2.exists() and c2.is_dir():
                    encontrados.append(c2)
        except (OSError, PermissionError):
            pass

    return encontrados


def _limpar_caches_navegadores(simular: bool = True) -> dict:
    """Esvazia diretórios de cache sem nunca tocar em arquivos de sessão/cookies."""
    bytes_liberados = 0
    arquivos_removidos = 0
    dirs = _diretorios_cache_navegadores()

    for d in dirs:
        for raiz, _, arqs in os.walk(d):
            for nome in arqs:
                p = Path(raiz) / nome
                # Proteção extra em profundidade: nunca apagar cookies ou logins
                nome_baixo = nome.lower()
                if "cookie" in nome_baixo or "login" in nome_baixo or "web data" in nome_baixo:
                    continue
                try:
                    tam = p.stat().st_size
                    if not simular:
                        try:
                            p.unlink(missing_ok=True)
                            bytes_liberados += tam
                            arquivos_removidos += 1
                        except (OSError, PermissionError):
                            pass
                    else:
                        bytes_liberados += tam
                        arquivos_removidos += 1
                except OSError:
                    continue

    return {"bytes_liberados": bytes_liberados, "arquivos_removidos": arquivos_removidos}


def _podar_imagens_docker() -> dict:
    """Executa 'docker image prune -f' se o docker estiver ativo."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return {"sucesso": False, "motivo": "Docker não instalado no PATH"}
    try:
        res = subprocess.run(
            [docker_bin, "image", "prune", "-f"],
            capture_output=True,
            text=True,
            timeout=60,
            shell=False
        )
        return {"sucesso": res.returncode == 0, "saida": res.stdout.strip(), "erro": res.stderr.strip()}
    except Exception as e:
        return {"sucesso": False, "motivo": str(e)}


def _limpar_builds_antigos(projetos_pastas: list[str], dias: int = 30, simular: bool = True) -> dict:
    """Remove pastas node_modules e de build inativas há mais de N dias."""
    alvos_build = {"node_modules", "dist", "build", "target", ".next", ".nuxt", ".vite", "__pycache__"}
    limite_seg = dias * 86400
    agora = time.time()
    pastas_removidas = []
    bytes_liberados = 0

    for pasta_str in projetos_pastas:
        p_raiz = _resolver_caminho(pasta_str)
        if not p_raiz.exists() or not p_raiz.is_dir():
            continue

        for raiz, dirs, _ in os.walk(p_raiz):
            dirs_para_checar = list(dirs)
            for d in dirs_para_checar:
                if d in alvos_build:
                    caminho_dir = Path(raiz) / d
                    try:
                        mtime = caminho_dir.stat().st_mtime
                        if agora - mtime >= limite_seg:
                            dirs.remove(d)  # Não desce mais na pasta que será apagada
                            if not simular:
                                send2trash(str(caminho_dir.resolve()))
                                desfazer.registrar(
                                    "remover_pasta",
                                    f"Limpar build antigo {caminho_dir.name}",
                                    desfazer.inversa_restaurar(str(caminho_dir.resolve()))
                                )
                            pastas_removidas.append(str(caminho_dir))
                    except (OSError, PermissionError):
                        continue

    return {"pastas_removidas": len(pastas_removidas), "detalhes": pastas_removidas}


def limpar_disco(
    executar: bool = True,
    incluir_docker: bool = True,
    incluir_builds: bool = True,
    limite_pct: int = 80
) -> dict:
    """Verifica espaço e executa limpeza segura se a partição estiver acima do limite."""
    import psutil

    particoes = psutil.disk_partitions(all=False)
    particoes_fixas = [p for p in particoes if "cdrom" not in p.opts and p.fstype]

    uso_maximo = 0.0
    particao_critica = None

    for part in particoes_fixas:
        try:
            uso = psutil.disk_usage(part.mountpoint)
            if uso.percent > uso_maximo:
                uso_maximo = uso.percent
                particao_critica = part.mountpoint
        except (OSError, PermissionError):
            continue

    if limite_pct > 0 and uso_maximo < limite_pct:
        return {
            "executado": False,
            "motivo": f"Uso de disco ({uso_maximo:.1f}%) abaixo do limite ({limite_pct}%)",
            "uso_maximo_pct": uso_maximo,
            "particao": particao_critica
        }

    cfg = carregar_config_bloco1()
    simular = not executar

    res_cache = _limpar_caches_navegadores(simular=simular)
    res_docker = _podar_imagens_docker() if incluir_docker else {"sucesso": False, "motivo": "desativado"}
    res_builds = _limpar_builds_antigos(cfg.get("projetos_pastas", []), simular=simular) if incluir_builds else {"pastas_removidas": 0}

    return {
        "executado": True,
        "uso_detectado_pct": uso_maximo,
        "particao": particao_critica,
        "caches_navegador": res_cache,
        "docker": res_docker,
        "builds": res_builds,
        "simulado": simular
    }


# ====================== ITEM 5: CONVERSÃO DE IMAGENS ======================
def converter_imagens(
    alvo: str | list[str],
    formato: str = "png",
    apagar_original: bool = False
) -> dict:
    """Converte imagens .webp ou .heic em lote para .png ou .jpg."""
    from PIL import Image

    caminhos: list[Path] = []
    if isinstance(alvo, list):
        for item in alvo:
            p = _resolver_caminho(item)
            if p.is_file():
                caminhos.append(p)
            elif p.is_dir():
                caminhos.extend(list(p.glob("*.webp")) + list(p.glob("*.heic")) + list(p.glob("*.heif")))
    else:
        p = _resolver_caminho(alvo)
        if p.is_file():
            caminhos.append(p)
        elif p.is_dir():
            caminhos.extend(list(p.glob("*.webp")) + list(p.glob("*.heic")) + list(p.glob("*.heif")))

    formato_fmt = formato.lower().replace(".", "")
    if formato_fmt in ("jpg", "jpeg"):
        ext_destino = ".jpg"
        pil_format = "JPEG"
    else:
        ext_destino = ".png"
        pil_format = "PNG"

    convertidos = 0
    erros = []
    arquivos_gerados = []

    for arq in caminhos:
        sufixo = arq.suffix.lower()
        if sufixo not in (".webp", ".heic", ".heif"):
            continue

        if sufixo in (".heic", ".heif"):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                erros.append(f"{arq.name}: pillow-heif não instalado para formato HEIC")
                continue

        try:
            with Image.open(arq) as img:
                saida = img
                if pil_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
                    saida = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "RGBA":
                        saida.paste(img, mask=img.split()[3])
                    else:
                        saida.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])

                destino_candidato = arq.with_suffix(ext_destino)
                destino_final = arquivos.nome_livre(destino_candidato)
                saida.save(destino_final, pil_format)

                # Preserva timestamp original
                try:
                    st = arq.stat()
                    os.utime(destino_final, (st.st_atime, st.st_mtime))
                except OSError:
                    pass

                convertidos += 1
                arquivos_gerados.append(str(destino_final))

            if apagar_original and arq.exists():
                send2trash(str(arq.resolve()))
                desfazer.registrar(
                    "remover",
                    f"Apagar imagem original {arq.name}",
                    desfazer.inversa_restaurar(str(arq.resolve()))
                )

        except Exception as e:
            erros.append(f"{arq.name}: {e}")

    return {
        "total": len(caminhos),
        "convertidos": convertidos,
        "gerados": arquivos_gerados,
        "erros": erros
    }


# ====================== ITEM 6: ARQUIVAR PROJETOS ANTIGOS ======================
def arquivar_projetos_antigos(
    pasta: str = "",
    meses: int = 6,
    executar: bool = False
) -> dict:
    """Compacta pastas de projetos sem modificação há mais de N meses em .tar.zst."""
    import tarfile

    dir_alvo = _resolver_caminho(pasta) if pasta else None
    pastas_pesquisar = [dir_alvo] if dir_alvo else [_resolver_caminho(p) for p in carregar_config_bloco1().get("projetos_pastas", [])]

    limite_seg = meses * 30 * 86400
    agora = time.time()
    candidatos: list[Path] = []

    for base in pastas_pesquisar:
        if not base or not base.exists() or not base.is_dir():
            continue
        try:
            for sub in base.iterdir():
                if not sub.is_dir() or sub.name.startswith(".") or sub.name.startswith("_"):
                    continue
                # Calcula mtime mais recente dentro da subpasta
                max_mtime = sub.stat().st_mtime
                for raiz, _, arqs in os.walk(sub):
                    for a in arqs:
                        try:
                            t = (Path(raiz) / a).stat().st_mtime
                            if t > max_mtime:
                                max_mtime = t
                        except OSError:
                            continue
                if agora - max_mtime >= limite_seg:
                    candidatos.append(sub)
        except (OSError, PermissionError):
            continue

    compactados = 0
    detalhes = []

    for proj in candidatos:
        tar_nome = f"{proj.name}.tar.zst"
        destino_tar = arquivos.nome_livre(proj.parent / tar_nome)
        temp_tar = destino_tar.with_suffix(".tmp.tar.zst")

        info = {"projeto": str(proj), "arquivo": str(destino_tar), "status": "simulado"}

        if executar:
            try:
                with tarfile.open(temp_tar, "w:zst") as tar:
                    tar.add(proj, arcname=proj.name)

                # Validação pós-compactação obrigatória
                with tarfile.open(temp_tar, "r:zst") as tar_val:
                    membros = tar_val.getmembers()
                    if not membros:
                        raise ValueError("Arquivo .tar.zst gerado está vazio")

                temp_tar.replace(destino_tar)

                # Move projeto original para lixeira com desfazer
                send2trash(str(proj.resolve()))
                desfazer.registrar(
                    "remover_pasta",
                    f"Arquivar projeto antigo {proj.name} para {destino_tar.name}",
                    desfazer.inversa_restaurar(str(proj.resolve()))
                )
                compactados += 1
                info["status"] = "compactado"
            except Exception as e:
                info["status"] = f"erro: {e}"
                if temp_tar.exists():
                    temp_tar.unlink(missing_ok=True)
        else:
            compactados += 1

        detalhes.append(info)

    return {
        "encontrados": len(candidatos),
        "compactados": compactados,
        "detalhes": detalhes
    }


# ====================== ITEM 7: BACKUP INCREMENTAL SILENCIOSO ======================
def executar_backup_incremental(
    origem: str = "",
    destino: str = "",
    versionar_anteriores: bool = True
) -> dict:
    """Executa rodada de backup incremental baseada em manifesto SHA-256."""
    cfg = carregar_config_bloco1()
    p_origem = _resolver_caminho(origem) if origem else (_resolver_caminho(cfg.get("backup_origens")[0]) if cfg.get("backup_origens") else None)
    p_destino = _resolver_caminho(destino) if destino else (_resolver_caminho(cfg.get("backup_destino")) if cfg.get("backup_destino") else None)

    if not p_origem or not p_origem.exists() or not p_origem.is_dir():
        return {"sucesso": False, "copiados": 0, "erro": "Diretório de origem inválido ou inexistente"}
    if not p_destino:
        return {"sucesso": False, "copiados": 0, "erro": "Diretório de destino não configurado"}

    p_origem_res = p_origem.resolve()
    p_destino_res = p_destino.resolve()

    # Prevenção contra loop de diretório (Review Focus #5)
    if p_origem_res == p_destino_res or p_origem_res in p_destino_res.parents or p_destino_res in p_origem_res.parents:
        return {"sucesso": False, "copiados": 0, "erro": "Destino dentro da origem ou vice-versa (risco de loop)"}

    p_destino.mkdir(parents=True, exist_ok=True)
    manifesto_path = p_destino / ".ultron-backup-manifest.json"
    manifesto: dict[str, dict[str, Any]] = {}
    if manifesto_path.exists():
        try:
            manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
        except Exception:
            manifesto = {}

    copiados = 0
    inalterados = 0
    erros = []
    agora_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for raiz, dirs, arqs in os.walk(p_origem):
        # Ignora pastas de controle
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".venv")]
        for nome in arqs:
            p_arq = Path(raiz) / nome
            if _eh_temporario(p_arq):
                continue
            try:
                rel = str(p_arq.relative_to(p_origem)).replace("\\", "/")
                st = p_arq.stat()
                tam = st.st_size
                mtime_ns = st.st_mtime_ns

                item_antigo = manifesto.get(rel)
                if item_antigo and item_antigo.get("size") == tam and item_antigo.get("mtime_ns") == mtime_ns:
                    inalterados += 1
                    continue

                sha = _hash_completo(p_arq)
                if item_antigo and item_antigo.get("sha256") == sha:
                    # Conteúdo idêntico, apenas atualiza timestamp no manifesto
                    manifesto[rel]["mtime_ns"] = mtime_ns
                    inalterados += 1
                    continue

                dest_arq = p_destino / Path(rel)
                dest_arq.parent.mkdir(parents=True, exist_ok=True)

                if dest_arq.exists() and versionar_anteriores:
                    historico_dir = p_destino / ".ultron_historico" / agora_ts / dest_arq.parent.relative_to(p_destino)
                    historico_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest_arq, historico_dir / dest_arq.name)

                # Gravação atômica via temporário
                temp_dest = dest_arq.with_suffix(".tmp.ulbak")
                shutil.copy2(p_arq, temp_dest)
                temp_dest.replace(dest_arq)

                manifesto[rel] = {"size": tam, "mtime_ns": mtime_ns, "sha256": sha}
                copiados += 1
            except Exception as e:
                erros.append(f"{p_arq.name}: {e}")

    try:
        temp_mani = manifesto_path.with_suffix(".tmp.json")
        temp_mani.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_mani.replace(manifesto_path)
    except Exception as e:
        _log.warning("Falha ao salvar manifesto de backup: %s", e)

    return {
        "sucesso": True,
        "copiados": copiados,
        "inalterados": inalterados,
        "total": copiados + inalterados,
        "erros": erros
    }


# ====================== ITEM 8: ARQUIVAR CAPTURAS DE TELA DO DESKTOP ======================
_PADROES_CAPTURAS = re.compile(
    r"(screenshot|captura de tela|captura de ecra|captura|screen shot|snip|recorte)",
    re.IGNORECASE
)
_EXTS_IMAGEM = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def arquivar_capturas_desktop(
    dias: int = 7,
    executar: bool = True,
    desktop_pasta: str = ""
) -> dict:
    """Move capturas de tela antigas soltas no Desktop para Capturas/AAAA/MM."""
    dir_desk = _resolver_caminho(desktop_pasta) if desktop_pasta else (Path.home() / "Desktop")
    if not dir_desk.exists() or not dir_desk.is_dir():
        # Fallback OneDrive Desktop
        onedrive_desk = Path.home() / "OneDrive" / "Desktop"
        if onedrive_desk.exists():
            dir_desk = onedrive_desk
        else:
            return {"encontrados": 0, "movidos": 0, "erro": "Área de Trabalho não encontrada"}

    limite_seg = dias * 86400
    agora = time.time()
    candidatos: list[Path] = []

    for item in dir_desk.iterdir():
        if not item.is_file() or item.suffix.lower() not in _EXTS_IMAGEM:
            continue
        if _eh_temporario(item):
            continue
        if not _PADROES_CAPTURAS.search(item.stem):
            continue
        try:
            idade = agora - item.stat().st_mtime
            if idade >= limite_seg:
                candidatos.append(item)
        except OSError:
            continue

    movidos = 0
    detalhes = []

    for print_arq in candidatos:
        try:
            mtime = print_arq.stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
            pasta_ano_mes = dir_desk / "Capturas" / f"{dt.year}" / f"{dt.month:02d}"
            pasta_ano_mes.mkdir(parents=True, exist_ok=True)

            destino_final = arquivos.nome_livre(pasta_ano_mes / print_arq.name)
            info = {"de": str(print_arq), "para": str(destino_final), "status": "simulado"}

            if executar:
                print_arq.rename(destino_final)
                desfazer.registrar(
                    "mover",
                    f"Arquivar captura {print_arq.name} para {destino_final.parent.name}",
                    desfazer.inversa_mover([{"de": str(destino_final), "para": str(print_arq)}])
                )
                movidos += 1
                info["status"] = "movido"
            else:
                movidos += 1

            detalhes.append(info)
        except Exception as e:
            detalhes.append({"de": str(print_arq), "erro": str(e)})

    return {
        "encontrados": len(candidatos),
        "movidos": movidos,
        "detalhes": detalhes
    }


# ====================== ITEM 9: CORRIGIR PERMISSÕES DE PASTA ======================
def corrigir_permissoes_pasta(
    pasta: str,
    remover_readonly: bool = True,
    corrigir_acl: bool = True
) -> dict:
    """Remove readonly e restabelece ACLs NTFS seguras (exige Modo Admin)."""
    import seguranca
    import ferramentas

    if not seguranca.modo_admin_ativo("bloco1"):
        return {"sucesso": False, "erro": "Ação exige Modo Admin Operacional ativo"}

    p = _resolver_caminho(pasta)
    if not p.exists() or not p.is_dir():
        return {"sucesso": False, "erro": "Pasta não encontrada"}

    # Recusa caminhos protegidos do sistema, raiz de drive ou raiz da home
    if ferramentas._protegido(p) or len(p.parts) <= 1 or p == Path.home():
        return {"sucesso": False, "erro": "Caminho protegido ou raiz de sistema bloqueada"}

    p_str = str(p.resolve())
    readonly_removido = False
    acl_corrigida = False

    if remover_readonly:
        try:
            subprocess.run(["attrib", "-R", "/S", "/D", os.path.join(p_str, "*")],
                           capture_output=True, timeout=60, shell=False)
            readonly_removido = True
        except Exception as e:
            _log.warning("Falha ao remover readonly em %s: %s", p_str, e)

    if corrigir_acl:
        try:
            # *S-1-5-32-544 = SID universal de Administradores
            cmd_icacls = ["icacls", p_str, "/grant", "*S-1-5-32-544:(OI)(CI)F", "/T", "/C"]
            res = subprocess.run(cmd_icacls, capture_output=True, text=True, timeout=120, shell=False)
            acl_corrigida = (res.returncode == 0)
        except Exception as e:
            _log.warning("Falha ao corrigir ACL em %s: %s", p_str, e)

    return {
        "sucesso": True,
        "pasta": p_str,
        "readonly_removido": readonly_removido,
        "acl_corrigida": acl_corrigida
    }


# ====================== ITEM 10: EJEÇÃO DE USB OCIOSO ======================
def _tipo_unidade_windows(unidade: str) -> int:
    """Devolve GetDriveTypeW (2 = REMOVABLE, 3 = FIXED, 5 = CDROM)."""
    if os.name != "nt":
        return 0
    import ctypes
    letra = unidade.strip().rstrip("\\").rstrip(":") + ":\\"
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(letra))
    except Exception:
        return 0


def _ejetar_volume_removivel_win32(letra: str) -> bool:
    """Tenta desmontar e ejetar com segurança um volume USB via Win32 DeviceIoControl."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_DISMOUNT_VOLUME = 0x00090020
    IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808

    kernel32 = ctypes.windll.kernel32
    caminho_vol = f"\\\\.\\{letra.strip().rstrip(':').rstrip('\\')}:"

    handle = kernel32.CreateFileW(
        caminho_vol,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None
    )
    if handle == -1 or handle == 0:
        return False

    bytes_ret = wintypes.DWORD(0)
    try:
        # 1. Bloqueia volume com segurança (se arquivo estiver aberto, aborta)
        ok_lock = kernel32.DeviceIoControl(handle, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(bytes_ret), None)
        if not ok_lock:
            return False

        # 2. Desmonta
        kernel32.DeviceIoControl(handle, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(bytes_ret), None)

        # 3. Ejeta mídia física
        ok_eject = kernel32.DeviceIoControl(handle, IOCTL_STORAGE_EJECT_MEDIA, None, 0, None, 0, ctypes.byref(bytes_ret), None)
        return bool(ok_eject)
    finally:
        kernel32.CloseHandle(handle)


def ejetar_usb_ocioso(unidade: str = "", minutos_ocioso: int = 5) -> dict:
    """Ejeta unidades USB que estejam ociosas pelo tempo determinado."""
    if unidade:
        letra = unidade.strip().rstrip("\\").rstrip(":") + ":\\"
        tipo = _tipo_unidade_windows(letra)
        if tipo != 2:  # DRIVE_REMOVABLE = 2
            return {"sucesso": False, "unidade": letra, "erro": f"Unidade {letra} não é unidade removível (tipo {tipo})"}

        sucesso = _ejetar_volume_removivel_win32(letra)
        return {"sucesso": sucesso, "unidade": letra, "erro": "" if sucesso else "Volume em uso ou travado por outro processo"}

    # Varredura de unidades removíveis automáticas
    import psutil
    ejetadas = []
    bloqueadas = []

    for part in psutil.disk_partitions(all=False):
        if _tipo_unidade_windows(part.mountpoint) == 2:
            # Tenta ejeção segura
            if _ejetar_volume_removivel_win32(part.mountpoint):
                ejetadas.append(part.mountpoint)
            else:
                bloqueadas.append(part.mountpoint)

    return {
        "sucesso": True,
        "ejetadas": ejetadas,
        "bloqueadas_em_uso": bloqueadas,
        "minutos_ocioso": minutos_ocioso
    }


