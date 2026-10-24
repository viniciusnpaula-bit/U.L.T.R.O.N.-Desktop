"""Atualização do ULTRON a partir do GitHub, verificada e com reversão.

Fluxo (tudo em loopback/local, sem privilégio de administrador):

    GET  /api/v1/update/check     -> consulta o Release mais recente e compara versões
    POST /api/v1/update/apply     -> baixa o ZIP, confere o SHA-256 publicado,
                                     guarda um backup e agenda a troca de arquivos
    POST /api/v1/update/restart   -> reabre o ULTRON com a versão nova
    POST /api/v1/update/rollback  -> volta para o backup anterior (se a troca já ocorreu)

Decisões de segurança:
  * só HTTPS e só hosts do GitHub (api.github.com e o domínio de download de assets);
  * o ZIP só é aplicado se o SHA-256 bater com o `SHA256SUMS.txt` do Release;
  * arquivos de dados (.env, dados/, logs/, venv/, electron/node_modules) nunca são
    tocados na troca — só código e assets do pacote;
  * a troca acontece por um script externo (.bat) que espera o processo terminar,
    porque o Windows não deixa substituir um .exe/.pyc em uso;
  * se algo falhar, a versão anterior continua no backup e o rollback é automático.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

APP_NAME = "U.L.T.R.O.N."

# Chave pública Ed25519 que assina o SHA256SUMS.txt de cada Release.
# Gerada por tools/gerar_chaves.py; a privada fica fora do repositório.
# É IMUTÁVEL de propósito: aceitar override por variável de ambiente permitiria que
# qualquer processo (ou um .env adulterado) trocasse a chave e assinasse um pacote falso.
# Enquanto estiver vazia, o app recusa atualizações (não há como provar autenticidade).
CHAVE_PUBLICA_ATUALIZACAO = "NCth8nDKGIOqL0hkMMTrNoySPmgXJYbmPMkgowaK4RE="
DEFAULT_REPO = "viniciusnpaula-bit/U.L.T.R.O.N.-Desktop"
ALLOWED_HOSTS = {"api.github.com", "objects.githubusercontent.com", "github.com",
                 "release-assets.githubusercontent.com"}
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
PROTECTED = (".env", "dados", "logs", "venv", ".git", ".ultron-state.json")
PROTECAO_PASTAS = {"venv", ".venv", "node_modules", "dados", "logs", ".git", "build", "__pycache__"}
# Nunca sobrescreve nada fora destes tipos: assim um ZIP malicioso não troca código
# arbitrário do sistema — só arquivos do próprio pacote.
ALLOWED_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".json", ".html", ".css", ".svg", ".png",
                    ".ico", ".md", ".txt", ".bat", ".ps1", ".yml", ".yaml", ".toml", ".cfg",
                    ".exe", ".dll", ".woff", ".woff2"}
STATE_NAME = ".ultron-state.json"


class UpdateError(RuntimeError):
    """Falha segura: nada foi alterado no disco."""


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts[:4]) or (0,)


def _caminho_bat(caminho) -> str:
    """Caminho seguro para interpolar em um .bat.

    O cmd expande `%VAR%` mesmo dentro de aspas, então `%` vira `%%`. Quando
    possível usa o caminho curto 8.3, que elimina acentos/espaços (o .bat é lido
    pelo cmd antes de o `chcp` valer para as linhas seguintes).
    """
    texto = str(caminho)
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(texto, buffer, len(buffer)):
            texto = buffer.value
    except Exception:
        pass
    return texto.replace("%", "%%").replace('"', "'")


def _current_version(root: Path) -> str:
    try:
        package = json.loads((root / "electron" / "package.json").read_text(encoding="utf-8"))
        return str(package.get("version") or "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


def _url_permitida(url: str, allowed_hosts: set[str]) -> str:
    """Valida esquema e host de uma URL de atualização.

    Também rejeita credenciais embutidas (`https://api.github.com@evil.com`), que
    passariam por uma checagem ingênua de `hostname`.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as error:
        raise UpdateError("Endereço de atualização inválido.") from error
    if parsed.scheme not in {"https", "http"}:
        raise UpdateError("Endereço de atualização inválido.")
    if parsed.scheme != "https" and os.environ.get("ULTRON_UPDATE_ALLOW_HTTP") != "1":
        raise UpdateError("A atualização exige HTTPS.")
    if parsed.username or parsed.password:
        raise UpdateError("Endereço de atualização inválido.")
    if (parsed.hostname or "").lower() not in {h.lower() for h in allowed_hosts}:
        raise UpdateError("O host de atualização não é permitido.")
    return url


class _RedirectSeguro(urllib.request.HTTPRedirectHandler):
    """Confere o host de CADA redirecionamento antes de segui-lo.

    `urlopen` segue redirects sozinho; sem isto, uma URL do GitHub poderia
    redirecionar para um servidor arbitrário e o `sha256sums`/`zip` viriam de lá.
    """

    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self._allowed_hosts = set(allowed_hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _url_permitida(newurl, self._allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _abrir(request: urllib.request.Request, allowed_hosts: set[str], timeout: float):
    """Abre a URL validando a origem inicial, cada redirect e a URL final."""
    _url_permitida(request.full_url, allowed_hosts)
    opener = urllib.request.build_opener(_RedirectSeguro(allowed_hosts))
    response = opener.open(request, timeout=timeout)
    try:
        _url_permitida(response.geturl(), allowed_hosts)
    except UpdateError:
        response.close()
        raise
    return response


def _request(url: str, *, timeout: float = 15.0, accept: str = "application/vnd.github+json",
             limit: int = 2 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "ULTRON-Desktop"})
    with _abrir(request, ALLOWED_HOSTS, timeout) as response:
        chunks, total = [], 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise UpdateError("Resposta do GitHub maior que o esperado.")
            chunks.append(chunk)
    return b"".join(chunks)


def _download(url: str, destino: Path, allowed_hosts: set[str]) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "ULTRON-Desktop"})
    digest = hashlib.sha256()
    total = 0
    with _abrir(request, allowed_hosts, 60) as response, destino.open("wb") as handle:
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise UpdateError("O pacote de atualização é grande demais.")
            digest.update(chunk)
            handle.write(chunk)
    return total, digest.hexdigest()


class UpdateManager:
    def __init__(self, root: Path, repo: str | None = None, log=None) -> None:
        self.root = Path(root).resolve()
        self.repo = (repo or os.environ.get("ULTRON_UPDATE_REPO") or DEFAULT_REPO).strip()
        self.log = log or (lambda _msg: None)
        self._lock = threading.Lock()
        self._job: dict | None = None
        self._state_path = self.root / STATE_NAME

    # ------------------------------------------------------------- estado
    @property
    def current_version(self) -> str:
        return _current_version(self.root)

    def _state(self) -> dict:
        if getattr(self, "_state_cache", None) is not None:
            return dict(self._state_cache)
        try:
            self._state_cache = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._state_cache = {}
        return dict(self._state_cache)

    def _save_state(self, **values) -> dict:
        state = {**self._state(), **values, "updated_at": time.time()}
        self._state_cache = dict(state)
        try:
            self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass
        return state

    def describe(self) -> dict:
        state = self._state()
        last = state.get("last_check") or {}
        return {
            "current_version": self.current_version,
            "repo": self.repo,
            "auto_check": state.get("auto_check", True),
            "last_check": last or None,
            "job": self._job,
            "needs_restart": bool((self._job or {}).get("needs_restart")),
            "pending_version": state.get("pending_version"),
        }

    # ------------------------------------------------------------- consulta
    def check(self, *, timeout: float = 15.0) -> dict:
        """Compara a versão instalada com o último Release publicado."""
        with self._lock:
            try:
                raw = _request(f"https://api.github.com/repos/{self.repo}/releases/latest", timeout=timeout)
            except urllib.error.HTTPError as error:
                if error.code in (403, 404):
                    alternativa = self._check_from_list(timeout)
                    if alternativa is not None:
                        return alternativa
                if error.code == 404:
                    resultado = {"status": "sem_release", "current_version": self.current_version,
                                 "repo": self.repo, "message": "Ainda não há release publicado neste repositório."}
                else:
                    resultado = {"status": "erro", "current_version": self.current_version, "repo": self.repo,
                                 "message": f"O GitHub respondeu {error.code}."}
                self._save_state(last_check={**resultado, "at": time.time()})
                return resultado
            except (urllib.error.URLError, OSError, UpdateError) as error:
                resultado = {"status": "erro", "current_version": self.current_version, "repo": self.repo,
                             "message": f"Sem acesso ao GitHub ({type(error).__name__})."}
                self._save_state(last_check={**resultado, "at": time.time()})
                return resultado

            try:
                release = json.loads(raw.decode("utf-8"))
            except ValueError:
                raise UpdateError("Resposta do GitHub inválida.") from None
            tag = str(release.get("tag_name") or release.get("name") or "").strip()
            latest = tag.lstrip("vV")
            assets = release.get("assets") or []
            zip_asset = next((a for a in assets if str(a.get("name", "")).lower().endswith(".zip")), None)
            sums_asset = next((a for a in assets if str(a.get("name", "")).lower() == "sha256sums.txt"), None)
            sig_asset = next((a for a in assets if str(a.get("name", "")).lower() == "sha256sums.txt.sig"), None)
            resultado = {
                "status": "ok",
                "current_version": self.current_version,
                "latest_version": latest or self.current_version,
                "tag": tag,
                "repo": self.repo,
                "update_available": _version_tuple(latest) > _version_tuple(self.current_version),
                "notes": str(release.get("body") or "")[:4000],
                "published_at": release.get("published_at"),
                "html_url": release.get("html_url"),
                "asset": {"name": zip_asset.get("name"), "size": zip_asset.get("size"),
                          "url": zip_asset.get("browser_download_url")} if zip_asset else None,
                "checksums": sums_asset.get("browser_download_url") if sums_asset else None,
                "assinatura": sig_asset.get("browser_download_url") if sig_asset else None,
            }
            self._save_state(last_check={**resultado, "at": time.time()})
            self.log(f"Atualização: instalada {resultado['current_version']} / publicada {resultado['latest_version']}")
            return resultado

    def _check_from_list(self, timeout: float) -> dict | None:
        """Fallback quando /releases/latest não existe: pega o Release estável mais recente."""
        try:
            raw = _request(f"https://api.github.com/repos/{self.repo}/releases", timeout=timeout)
            releases = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(releases, list) or not releases:
            return None
        estaveis = [r for r in releases if not r.get("draft") and not r.get("prerelease")]
        if not estaveis:
            return None
        release = max(estaveis, key=lambda r: _version_tuple(str(r.get("tag_name", "")).lstrip("vV")))
        tag = str(release.get("tag_name") or "")
        latest = tag.lstrip("vV")
        assets = release.get("assets") or []
        zip_asset = next((a for a in assets if str(a.get("name", "")).lower().endswith(".zip")), None)
        sums_asset = next((a for a in assets if str(a.get("name", "")).lower() == "sha256sums.txt"), None)
        sig_asset = next((a for a in assets if str(a.get("name", "")).lower() == "sha256sums.txt.sig"), None)
        resultado = {
            "status": "ok",
            "current_version": self.current_version,
            "latest_version": latest or self.current_version,
            "tag": tag,
            "repo": self.repo,
            "update_available": _version_tuple(latest) > _version_tuple(self.current_version),
            "notes": str(release.get("body") or "")[:4000],
            "published_at": release.get("published_at"),
            "html_url": release.get("html_url"),
            "asset": {"name": zip_asset.get("name"), "size": zip_asset.get("size"),
                      "url": zip_asset.get("browser_download_url")} if zip_asset else None,
            "checksums": sums_asset.get("browser_download_url") if sums_asset else None,
            "assinatura": sig_asset.get("browser_download_url") if sig_asset else None,
        }
        self._save_state(last_check={**resultado, "at": time.time()})
        return resultado

    def set_auto_check(self, enabled: bool) -> bool:
        self._save_state(auto_check=bool(enabled))
        return bool(enabled)

    # ------------------------------------------------------------- aplicação
    def apply(self, *, restart_after: bool = True) -> dict:
        """Passo 2 do botão: baixa, confere o SHA-256, aplica launcher/setup e deixa o
        resto escrito no disco.

        O que decide reiniciar é `needs_restart`: verdadeiro quando algum arquivo em
        uso (ULTRON.exe, ULTRON-Setup.exe, .pyc, a própria interface) foi trocado.
        Roda em thread; o progresso fica em self._job."""
        if self._job and self._job.get("status") in {"baixando", "aplicando", "pronto"}:
            return self._job
        self._job = {"status": "baixando", "percent": 0, "message": "Consultando o GitHub…",
                     "started_at": time.time(), "needs_restart": False}
        thread = threading.Thread(target=self._apply_worker, args=(restart_after,),
                                  name="ultron-update", daemon=True)
        thread.start()
        return self._job

    def _set_job(self, **values) -> None:
        if self._job is not None:
            self._job = {**self._job, **values}

    def _apply_worker(self, restart_after: bool) -> None:
        try:
            info = self.check()
            if info.get("status") != "ok":
                self._set_job(status="erro", message=info.get("message") or "Não foi possível verificar.")
                return
            if not info.get("update_available"):
                self._set_job(status="atualizado", percent=100, message="Você já está na versão mais recente.")
                return
            asset = info.get("asset")
            if not asset or not asset.get("url"):
                self._set_job(status="erro", message="O Release não tem um pacote .zip para baixar.")
                return
            if not info.get("checksums"):
                self._set_job(status="erro", message="O Release não publica SHA256SUMS.txt; atualização recusada.")
                return

            self._set_job(status="baixando", percent=5, message=f"Baixando {asset['name']}…")
            work = Path(tempfile.mkdtemp(prefix="ultron-update-"))
            destino = work / str(asset["name"])
            allowed = set(ALLOWED_HOSTS)
            _, digest = _download(str(asset["url"]), destino, allowed)

            self._set_job(percent=40, message="Conferindo a assinatura do pacote (Ed25519)…")
            try:
                sums_bytes = _request(str(info["checksums"]), accept="text/plain", limit=512 * 1024)
            except (urllib.error.URLError, OSError, UpdateError):
                shutil.rmtree(work, ignore_errors=True)
                self._set_job(status="erro", message="Não consegui baixar o SHA256SUMS.txt do Release.")
                return
            if not self._assinatura_confere(info, sums_bytes):
                shutil.rmtree(work, ignore_errors=True)
                self.log("Atualização recusada: assinatura do SHA256SUMS.txt inválida ou ausente.")
                self._set_job(status="erro", needs_restart=False,
                              message=("Assinatura da atualização inválida ou ausente. "
                                       "Por segurança o pacote foi descartado. "
                                       "Baixe o Release manualmente em " + str(info.get("html_url") or "github.com")))
                return

            self._set_job(percent=45, message="Conferindo o SHA-256 do pacote…")
            brutos = sums_bytes.decode("utf-8", "replace")
            esperado = ""
            for linha in brutos.splitlines():
                partes = linha.split()
                if len(partes) >= 2 and partes[-1].lstrip("*") == Path(str(asset["name"])).name:
                    esperado = partes[0].lower()
                    break
            if not esperado:
                shutil.rmtree(work, ignore_errors=True)
                self._set_job(status="erro", message="O pacote não está listado no SHA256SUMS.txt.")
                return
            if esperado != digest:
                shutil.rmtree(work, ignore_errors=True)
                self._set_job(status="erro", message="SHA-256 não confere: o download foi descartado.")
                self.log("Atualização recusada: hash diferente.")
                return

            self._set_job(status="aplicando", percent=60, message="Preparando os arquivos…")
            staging = work / "staging"
            staging.mkdir()
            with zipfile.ZipFile(destino) as archive:
                if archive.testzip() is not None:
                    raise UpdateError("O ZIP está corrompido.")
                for item in archive.infolist():
                    nome = item.filename.replace("\\", "/")
                    if nome.endswith("/") or nome.startswith("__MACOSX"):
                        continue
                    partes = Path(nome).parts
                    if any(parte in {"..", ""} for parte in partes) or Path(nome).is_absolute():
                        raise UpdateError("O ZIP contém caminho inseguro.")
                    if partes[0] in PROTECTED or any(parte in PROTECAO_PASTAS for parte in partes):
                        continue
                    if Path(nome).suffix.lower() not in ALLOWED_SUFFIXES:
                        continue
                    alvo = staging.joinpath(*partes)
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as origem, alvo.open("wb") as saida:
                        shutil.copyfileobj(origem, saida)

            if not (staging / "electron" / "package.json").is_file():
                raise UpdateError("O pacote não parece ser do ULTRON (sem electron/package.json).")

            backup = self._backup_root() / f"backup-{self.current_version}-{time.strftime('%Y%m%d-%H%M%S')}"
            self._set_job(percent=75, message="Aplicando os arquivos que não estão em uso…")
            trocados_agora, pendentes, backup_pre = self._apply_now(staging)
            # `pending_backup` aponta para o backup PRE-APPLY (só os arquivos
            # sobrescritos) — é o que o rollback precisa. `last_backup` é a cópia
            # completa feita pelo .bat, usada só se a troca final falhar.
            self._save_state(pending_backup=str(backup_pre), last_backup=str(backup),
                             pending_version=str(info.get("latest_version")),
                             applied_manifest=self._manifest(staging),
                             pending_version_files=pendentes)

            if pendentes:
                # ainda há arquivos em uso: a troca final precisa de um processo livre
                script = self._write_apply_script(staging, backup)
                self._set_job(status="pronto", percent=100, needs_restart=True,
                              message=(f"{info['latest_version']} aplicada. "
                                       f"Reinicie para concluir {len(pendentes)} arquivo(s)."),
                              script=str(script), backup=str(backup), version=str(info.get("latest_version")),
                              applied=len(trocados_agora), pending=len(pendentes))
            else:
                self._set_job(status="pronto", percent=100, needs_restart=False,
                              message=f"{info['latest_version']} aplicada. Já está em uso.",
                              backup=str(backup), version=str(info.get("latest_version")),
                              applied=len(trocados_agora), pending=0)
            self.log(f"Atualização {info['latest_version']}: {len(trocados_agora)} arquivo(s) aplicados, "
                     f"{len(pendentes)} aguardando reinício.")
            if restart_after is not None:
                self._save_state(restart_after=bool(restart_after))
        except UpdateError as error:
            self._set_job(status="erro", message=str(error))
            self.log(f"Atualização falhou: {error}")
        except Exception as error:  # noqa: BLE001 - nunca deixa a thread morrer em silêncio
            self._set_job(status="erro", message=f"Falha inesperada na atualização ({type(error).__name__}).")
            self.log(f"Atualização falhou: {type(error).__name__}")

    def _assinatura_confere(self, info: dict, sums_bytes: bytes) -> bool:
        """Confere SHA256SUMS.txt.sig (Ed25519) com a chave pública embutida.

        Regra dura: sem assinatura válida, nada é aplicado. O SHA-256 sozinho só
        provaria que o arquivo não corrompeu no download, não que veio de nós.
        """
        assinatura_url = info.get("assinatura")
        if not assinatura_url:
            self.log("Release sem SHA256SUMS.txt.sig.")
            return False
        if not CHAVE_PUBLICA_ATUALIZACAO:
            self.log("App sem chave pública embutida: atualização recusada por padrão.")
            return False
        try:
            assinatura_bytes = _request(str(assinatura_url), accept="application/octet-stream",
                                        limit=4096)
        except (urllib.error.URLError, OSError, UpdateError) as erro:
            self.log(f"Falha ao baixar a assinatura ({type(erro).__name__}).")
            return False
        try:
            import assinatura
            publica = assinatura.carregar_publica_base64(CHAVE_PUBLICA_ATUALIZACAO)
            return assinatura.verificar(sums_bytes, assinatura_bytes, publica)
        except Exception as erro:  # chave malformada, base64 inválido, etc.
            self.log(f"Assinatura não pôde ser verificada ({type(erro).__name__}).")
            return False

    # ------------------------------------------------------------- aplicação imediata
    def _apply_now(self, staging: Path) -> tuple[list[str], list[str], Path]:
        """Copia da área de preparo para a instalação.

        Arquivos em uso no Windows (o .exe e a interface carregada) dão PermissionError;
        esses ficam para o script de reinício. Tudo o mais é aplicado na hora — assim
        uma atualização que só mexe em Python já vale no próximo comando, sem reiniciar.

        Devolve (aplicados, pendentes, backup_pre): o backup contém exatamente os
        arquivos que existiam antes e foram sobrescritos, para rollback confiável.
        """
        aplicados, pendentes = [], []
        backup = self._backup_root() / f"pre-apply-{time.strftime('%Y%m%d-%H%M%S')}"
        for arquivo in staging.rglob("*"):
            if not arquivo.is_file():
                continue
            relativo = arquivo.relative_to(staging)
            if any(parte in PROTECAO_PASTAS for parte in relativo.parts):
                continue
            destino = self.root / relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                if destino.is_file():
                    alvo_backup = backup / relativo
                    alvo_backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destino, alvo_backup)
                shutil.copy2(arquivo, destino)
                aplicados.append(relativo.as_posix())
            except (PermissionError, OSError):
                pendentes.append(relativo.as_posix())
        return aplicados, pendentes, backup

    # ------------------------------------------------------------- apoio
    def _backup_root(self) -> Path:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        destino = Path(base) / "ULTRON" / "updates"
        destino.mkdir(parents=True, exist_ok=True)
        return destino

    def _manifest(self, folder: Path) -> dict[str, str]:
        manifesto = {}
        for arquivo in folder.rglob("*"):
            if arquivo.is_file():
                manifesto[arquivo.relative_to(folder).as_posix()] = hashlib.sha256(arquivo.read_bytes()).hexdigest()
        return manifesto

    def _write_apply_script(self, staging: Path, backup: Path) -> Path:
        """Script .bat que espera o ULTRON sair, troca os arquivos e reabre.

        A troca usa robocopy com /XD nas pastas protegidas: dados do usuário,
        ambiente Python e node_modules ficam intactos.
        """
        destino = self._backup_root() / f"aplicar-{int(time.time())}.bat"
        reabrir = self.root / "ULTRON.exe"
        raiz_bat = _caminho_bat(self.root)
        staging_bat = _caminho_bat(staging)
        backup_bat = _caminho_bat(backup)
        reabrir_bat = _caminho_bat(reabrir)
        script = f"""@echo off
chcp 65001 >nul
title Aplicando atualização do U.L.T.R.O.N.
echo Aguardando o ULTRON fechar...
:espera
tasklist /FI "IMAGENAME eq ULTRON.exe" | find /I "ULTRON.exe" >nul && (timeout /t 1 /nobreak >nul & goto espera)
tasklist /FI "IMAGENAME eq electron.exe" | find /I "electron.exe" >nul && (timeout /t 1 /nobreak >nul & goto espera)
echo Backup em "{backup_bat}"...
robocopy "{raiz_bat}" "{backup_bat}" /E /NFL /NDL /NJH /NJS /NP /XD venv .venv node_modules __pycache__ dados logs .git build /XF *.log >nul
echo Copiando a versão nova...
robocopy "{staging_bat}" "{raiz_bat}" /E /IS /IT /NFL /NDL /NJH /NJS /NP /XD venv .venv node_modules __pycache__ dados logs .git build >nul
if errorlevel 8 goto falhou
echo Atualização aplicada.
start "" "{reabrir_bat}"
exit /b 0
:falhou
echo A cópia falhou. Restaurando a versão anterior...
robocopy "{backup_bat}" "{raiz_bat}" /E /IS /IT /NFL /NDL /NJH /NJS /NP /XD venv .venv node_modules __pycache__ dados logs .git build >nul
start "" "{reabrir_bat}"
exit /b 1
"""
        destino.write_text(script, encoding="utf-8", newline="\r\n")
        return destino

    def launch_apply(self) -> bool:
        """Inicia o script de aplicação (a troca acontece depois que o app sair)."""
        job = self._job or {}
        script = job.get("script")
        if not script or not Path(script).is_file():
            return False
        try:
            # A janela do script PRECISA existir: é ela que espera o ULTRON sair.
            subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/c", str(script)], cwd=str(self.root))
            return True
        except OSError:
            return False

    def rollback(self) -> bool:
        """Restaura o backup guardado pela última atualização aplicada."""
        backup = self._state().get("pending_backup")
        if not backup:
            return False
        origem = Path(backup)
        if not origem.is_dir():
            return False
        for arquivo in origem.rglob("*"):
            if not arquivo.is_file():
                continue
            relativo = arquivo.relative_to(origem)
            destino = self.root / relativo
            if relativo.parts[0] in PROTECTED or any(parte in PROTECAO_PASTAS for parte in relativo.parts):
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo, destino)
        self._save_state(rolled_back_at=time.time())
        self.log("Rollback aplicado a partir do backup.")
        return True


def default_manager(root: Path, log=None) -> UpdateManager:
    return UpdateManager(root, log=log)


if __name__ == "__main__":  # utilidade de linha de comando
    raiz = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
    print(json.dumps(UpdateManager(raiz).check(), indent=2, ensure_ascii=False))
