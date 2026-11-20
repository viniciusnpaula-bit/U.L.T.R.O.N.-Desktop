"""Gerador automatizado do runtime Python 3.12 Embedded para U.L.T.R.O.N. Desktop.

Etapas 10.2, 10.2.1 e 10.2.2: Construção, Auditoria e Homologação Final para Windows.

Este script realiza de ponta a ponta:
1. Validação estrita de integridade via hashes SHA-256 pré-homologados (python.org e get-pip.py).
2. Extração para diretório temporário de staging totalmente isolado.
3. Extração da biblioteca padrão de python312.zip para Lib/ (mitigando limites do zipimport).
4. Configuração estrita de python312._pth com suporte a site, Lib e site-packages.
5. Instalação determinística a partir do lockfile versionado oficial (tools/requirements-lock-win-py312.txt)
   utilizando --require-hashes e --no-deps no modo de produção padrão.
6. Isolamento estrito de cache e temporários para o disco de build (protegendo partição C:).
7. Verificação exaustiva de imports de módulos padrão, dependências nativas e núcleo U.L.T.R.O.N.
8. Suporte opcional a otimização (--strip-build-tools e --remove-zip).
9. Substituição atômica com backup e reversão automática (rollback) em caso de falha no Windows.
10. Geração do manifesto criptográfico RUNTIME_INFO.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

# ==============================================================================
# CONSTANTES DE PROCEDÊNCIA E INTEGRIDADE HOMOLOGADAS (ETAPAS 10.2 / 10.2.1 / 10.2.2)
# ==============================================================================

OFFICIAL_EMBED_RELEASES: dict[str, dict[str, str]] = {
    "3.12.9": {
        "url": "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip",
        "sha256": "615861fb801e8b04c847598db4e1e46e4b046295017caa37cb5486dde72b5865",
    },
    "3.12.10": {
        "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
        "sha256": "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3",
    },
    "3.13.16": {
        "url": "https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip",
        "sha256": "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297",
    },
    "3.14.10": {
        "url": "https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip",
        "sha256": "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159",
    },
}

DEFAULT_PYTHON_VERSION = "3.14.10"
PYTHON_ARCH = "AMD64"
PYTHON_BITNESS = 64

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
GET_PIP_SHA256 = (
    "356e0d0de21cdc348c3394084d90939b85e4246c4d14c76aee6ca4f46646ea98"
)

ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT_DIR / "build"
CACHE_DIR = BUILD_DIR / ".cache"
TMP_DIR = BUILD_DIR / ".tmp"
STAGING_DIR = BUILD_DIR / ".staging_python_runtime"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "runtime" / "python"
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"


def get_default_lockfile(python_version: str) -> Path:
    if python_version.startswith("3.14"):
        return ROOT_DIR / "tools" / "requirements-lock-win-py314.txt"
    return ROOT_DIR / "tools" / "requirements-lock-win-py312.txt"


def log(msg: str) -> None:
    print(f"[build_python_runtime] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def download_and_verify(url: str, dest: Path, expected_sha256: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        actual_hash = sha256_file(dest)
        if actual_hash.lower() == expected_sha256.lower():
            log(f"Arquivo em cache verificado ({dest.name}): SHA-256 OK")
            return dest
        log(f"Cache invalido para {dest.name} ({actual_hash} != {expected_sha256}). Baixando novamente...")
        dest.unlink(missing_ok=True)

    log(f"Baixando {url} -> {dest} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "ULTRON-Runtime-Builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)

    actual_hash = sha256_file(dest)
    if actual_hash.lower() != expected_sha256.lower():
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"FALHA DE INTEGRIDADE: SHA-256 incorreto para {dest.name}!\n"
            f"Esperado: {expected_sha256}\nObtido:   {actual_hash}"
        )
    log(f"Download concluido e verificado com sucesso: {dest.name} (SHA-256 OK)")
    return dest


def setup_pth(runtime_dir: Path, include_zip: bool = True) -> None:
    pth_candidates = list(runtime_dir.glob("python*._pth"))
    pth_file = pth_candidates[0] if pth_candidates else runtime_dir / "python312._pth"

    stdlib_zips = list(runtime_dir.glob("python*.zip"))
    zip_name = stdlib_zips[0].name if stdlib_zips else f"{pth_file.stem}.zip"

    lines = [
        "Lib",
        "Lib\\site-packages",
        ".",
        "..",
        "..\\..",
    ]
    if include_zip:
        lines.append(zip_name)
    lines.extend([
        "",
        "# Habilitar carregamento de site para site-packages",
        "import site",
        "",
    ])
    pth_file.write_text("\n".join(lines), encoding="utf-8")
    log(f"Configurado {pth_file.name} com Lib, Lib/site-packages e import site.")


def extract_stdlib_zip(runtime_dir: Path, remove_zip: bool = False) -> None:
    stdlib_zips = list(runtime_dir.glob("python*.zip"))
    lib_dir = runtime_dir / "Lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "site-packages").mkdir(parents=True, exist_ok=True)

    if stdlib_zips:
        zip_path = stdlib_zips[0]
        import zipfile
        log(f"Extraindo {zip_path.name} para Lib/ para acesso direto ao sistema de arquivos...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(lib_dir)
        log("Extracao da biblioteca padrao concluida.")
        if remove_zip:
            log(f"Opcao --remove-zip ativa. Removendo {zip_path.name} para economizar espaco...")
            zip_path.unlink()


def run_runtime_cmd(python_exe: Path, args: list[str], env: dict[str, str], description: str) -> subprocess.CompletedProcess[str]:
    log(f"Executando: {description} ...")
    cmd = [str(python_exe)] + args
    res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        stdout_txt = res.stdout.decode("latin-1", errors="replace")
        stderr_txt = res.stderr.decode("latin-1", errors="replace")
        raise RuntimeError(
            f"Falha ao executar '{description}' (exit {res.returncode}):\n"
            f"STDOUT:\n{stdout_txt}\nSTDERR:\n{stderr_txt}"
        )
    return res


def strip_build_artifacts(runtime_dir: Path) -> int:
    """Remove ferramentas de build (pip, setuptools, wheel e Scripts/) no runtime final."""
    site_pkgs = runtime_dir / "Lib" / "site-packages"
    scripts_dir = runtime_dir / "Scripts"
    removed_bytes = 0

    to_remove = [
        "pip", "pip-26.3.dist-info",
        "setuptools", "setuptools-84.2.1.dist-info",
        "wheel", "wheel-0.48.0.dist-info",
    ]

    for item in to_remove:
        target = site_pkgs / item
        if target.exists():
            if target.is_dir():
                sz = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
                shutil.rmtree(target, ignore_errors=True)
            else:
                sz = target.stat().st_size
                target.unlink(missing_ok=True)
            removed_bytes += sz

    if scripts_dir.exists():
        sz = sum(f.stat().st_size for f in scripts_dir.rglob("*") if f.is_file())
        shutil.rmtree(scripts_dir, ignore_errors=True)
        removed_bytes += sz

    log(f"Ferramentas de build removidas com sucesso: {round(removed_bytes / (1024 * 1024), 2)} MB liberados.")
    return removed_bytes


def verify_runtime_environment(python_exe: Path, root_dir: Path) -> dict[str, Any]:
    log("Iniciando auditoria e verificacao de imports no runtime...")
    test_script = f"""
import sys, os, json, platform

results = {{
    "python_version": sys.version,
    "architecture": platform.architecture()[0],
    "is_64bit": sys.maxsize > 2**32,
    "modules": {{}}
}}

sys.path.insert(0, r"{root_dir}")
os.environ["OPENBLAS_NUM_THREADS"] = "1"

modules_to_test = [
    # Modulos Nativos / Standard Library
    "sqlite3", "ssl", "ctypes", "asyncio", "hashlib",
    # Dependencias Criticas de requirements.txt
    "numpy",
    "cv2",
    "pygame",
    "sounddevice",
    "speech_recognition",
    "cryptography",
    "winrt.windows.security.credentials.ui",
    "psutil",
    "pystray",
    "pyttsx3",
    "pyautogui",
    "pyperclip",
    "openai",
    "edge_tts",
    "telegram",
    "requests",
    "dotenv",
    # Modulos do Nucleo U.L.T.R.O.N.
    "config",
    "seguranca",
    "memoria",
    "cofre",
    "cerebro",
    "desktop_api",
    "desktop_runtime",
]

for mod in modules_to_test:
    try:
        m = __import__(mod)
        version = getattr(m, "__version__", "loaded")
        results["modules"][mod] = {{"status": "OK", "version": str(version)}}
    except Exception as e:
        results["modules"][mod] = {{"status": "ERROR", "error": f"{{type(e).__name__}}: {{e}}"}}

# Validação funcional de criptografia AES-256-GCM
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key = AESGCM.generate_key(bit_length=256)
aesgcm = AESGCM(key)
ct = aesgcm.encrypt(b"123456789012", b"dados_teste", None)
pt = aesgcm.decrypt(b"123456789012", ct, None)
results["aes_gcm_functional"] = pt == b"dados_teste"

print(json.dumps(results))
"""
    cmd = [str(python_exe), "-c", test_script]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_txt = res.stdout.decode("latin-1", errors="replace").strip()
    stderr_txt = res.stderr.decode("latin-1", errors="replace").strip()

    if res.returncode != 0:
        raise RuntimeError(f"Verificacao do runtime falhou (exit {res.returncode}):\nSTDOUT: {stdout_txt}\nSTDERR: {stderr_txt}")

    json_start = stdout_txt.find("{")
    if json_start == -1:
        raise RuntimeError(f"Resposta JSON nao encontrada no teste:\n{stdout_txt}")

    data = json.loads(stdout_txt[json_start:])
    failures = [k for k, v in data["modules"].items() if isinstance(v, dict) and v.get("status") != "OK"]
    if failures:
        details = "\n".join(f" - {k}: {data['modules'][k]['error']}" for k in failures)
        raise RuntimeError(f"Falha na importacao dos seguintes modulos no runtime:\n{details}")

    if not data.get("aes_gcm_functional"):
        raise RuntimeError("Falha no teste funcional de criptografia AES-256-GCM!")

    log(f"Todos os {len(data['modules'])} modulos testados foram importados com SUCESSO no Python Embedded!")
    return data


def get_installed_packages(python_exe: Path) -> dict[str, str]:
    script = """
import sys
try:
    from importlib.metadata import distributions
    pkgs = {dist.metadata['Name']: dist.version for dist in distributions()}
    import json
    print(json.dumps(pkgs))
except Exception as e:
    import json
    print(json.dumps({"error": str(e)}))
"""
    res = subprocess.run([str(python_exe), "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    txt = res.stdout.decode("latin-1", errors="replace").strip()
    json_start = txt.find("{")
    if json_start != -1:
        return json.loads(txt[json_start:])
    return {}


def calculate_dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def is_valid_runtime_dir(path: Path) -> bool:
    """Verifica se um diretório é um runtime Python operacional contendo python.exe."""
    try:
        return path.is_dir() and (path / "python.exe").is_file()
    except Exception:
        return False


def recover_incomplete_state(target: Path) -> bool:
    """Identifica e recupera estados incompletos deixados por falhas ou interrupções abruptas no Windows."""
    parent = target.parent
    if not parent.exists():
        return False

    backup_candidates = sorted(
        parent.glob(f"{target.name}.backup_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    target_valid = is_valid_runtime_dir(target)

    if not target_valid:
        # Destino ausente ou incompleto: verificar se existe backup viável para recuperação imediata
        for b in backup_candidates:
            if is_valid_runtime_dir(b):
                log(f"Estado incompleto detectado! Recuperando runtime anterior a partir do backup: {b.name} ...")
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.move(str(b), str(target))
                log(f"Recuperacao automatica concluida com sucesso para {target}.")
                target_valid = True
                break

    # Se o target está válido e operacional, limpar eventuais backups orfaos remanescentes
    if target_valid:
        for b in parent.glob(f"{target.name}.backup_*"):
            log(f"Limpando backup orfao de execucao anterior: {b.name} ...")
            shutil.rmtree(b, ignore_errors=True)
        return True

    return False


def safe_atomic_replace(staging: Path, target: Path) -> None:
    """Substituição atômica com backup prévio, tolerância a interrupções e reversão automática (rollback) no Windows."""
    # 0. Recuperar previamente qualquer estado interrompido anterior
    recover_incomplete_state(target)

    backup = target.with_name(f"{target.name}.backup_{int(time.time())}_{os.getpid()}")
    target_existed = target.exists()

    if target_existed:
        log(f"Movendo runtime atual para backup temporario: {backup.name} ...")
        shutil.move(str(target), str(backup))

    try:
        log(f"Promovendo staging para destino final: {target} ...")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(target))

        # Confirmar integridade física do destino recém-promovido antes de descartar backup
        if not is_valid_runtime_dir(target):
            raise RuntimeError(f"Destino promovido incompleto ou vazio em {target}")

        if target_existed and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
            log("Backup temporario removido com sucesso apos confirmacao do novo runtime.")
    except Exception as e:
        log(f"ERRO CRITICO NA PROMOCAO DO RUNTIME: {e}. Executando rollback...")
        if target_existed and backup.exists():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(backup), str(target))
            log("Rollback concluido com sucesso. Runtime anterior restaurado.")
        raise


def build_runtime(
    output_dir: Path | None = None,
    clean: bool = False,
    python_version: str = DEFAULT_PYTHON_VERSION,
    lockfile: Path | None = None,
    use_requirements: bool = False,
    strip_build_tools: bool = False,
    remove_zip: bool = False,
) -> Path:
    target_dir = (output_dir or DEFAULT_OUTPUT_DIR).resolve()
    start_time = time.time()

    if python_version not in OFFICIAL_EMBED_RELEASES:
        raise ValueError(
            f"Versao '{python_version}' nao homologada. Opcoes validas: {list(OFFICIAL_EMBED_RELEASES.keys())}"
        )

    rel_info = OFFICIAL_EMBED_RELEASES[python_version]
    embed_url = rel_info["url"]
    embed_sha256 = rel_info["sha256"]

    log("=" * 70)
    log(f"Iniciando construcao do Python {python_version} Embedded ({PYTHON_ARCH})")
    log(f"Destino final: {target_dir}")
    log("=" * 70)

    # 1. Preparar pastas no Drive do projeto (protegendo C: contra falta de espaco)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # 1.1 Recuperar estado incompleto anterior se houver
    recover_incomplete_state(target_dir)

    if clean:
        log("Opcao --clean solicitada. Removendo diretorios de staging...")
        if STAGING_DIR.exists():
            shutil.rmtree(STAGING_DIR, ignore_errors=True)

    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Download e Verificacao do Python Embed ZIP
    embed_zip = CACHE_DIR / f"python-{python_version}-embed-amd64.zip"
    download_and_verify(embed_url, embed_zip, embed_sha256)

    # 3. Download e Verificacao do get-pip.py
    get_pip_script = CACHE_DIR / "get-pip.py"
    download_and_verify(GET_PIP_URL, get_pip_script, GET_PIP_SHA256)

    # 4. Extracao do Python Embed para Staging
    log(f"Extraindo {embed_zip.name} para staging...")
    import zipfile
    with zipfile.ZipFile(embed_zip, "r") as zf:
        zf.extractall(STAGING_DIR)

    # 5. Extracao da stdlib para Lib/ e configuracao de ._pth
    extract_stdlib_zip(STAGING_DIR, remove_zip=remove_zip)
    setup_pth(STAGING_DIR, include_zip=not remove_zip)

    staging_python = STAGING_DIR / "python.exe"
    if not staging_python.exists():
        raise RuntimeError(f"Binario python.exe nao encontrado em {STAGING_DIR}!")

    # 6. Preparar variaveis de ambiente para redirecionar temporarios e cache ao disco D:
    build_env = os.environ.copy()
    build_env["TEMP"] = str(TMP_DIR)
    build_env["TMP"] = str(TMP_DIR)
    build_env["PIP_CACHE_DIR"] = str(CACHE_DIR / "pip")
    build_env["OPENBLAS_NUM_THREADS"] = "1"
    build_env["PYTHONNOUSERSITE"] = "1"

    # 7. Instalar pip via get-pip.py
    run_runtime_cmd(
        staging_python,
        [str(get_pip_script), "--no-warn-script-location", "--quiet"],
        build_env,
        "Bootstrap do pip via get-pip.py",
    )

    # 8. Instalar ferramentas de build (setuptools, wheel) para pacotes sdist puros
    run_runtime_cmd(
        staging_python,
        ["-m", "pip", "install", "setuptools", "wheel", "--no-warn-script-location", "--quiet"],
        build_env,
        "Instalacao de setuptools e wheel",
    )

    # 9. Definir origem de dependencias (Lockfile como padrao obrigatorio em producao)
    if use_requirements:
        target_install_file = REQUIREMENTS_FILE
        log(f"Modo relaxado ativo: instalando diretamente de {REQUIREMENTS_FILE.name} ...")
        pip_args = [
            "-m", "pip", "install",
            "-r", str(target_install_file),
            "--prefer-binary", "--no-build-isolation", "--no-warn-script-location",
        ]
    else:
        target_install_file = lockfile or get_default_lockfile(python_version)
        if not target_install_file.exists():
            raise FileNotFoundError(
                f"Lockfile de producao nao encontrado em {target_install_file}! "
                "Crie-o ou passe --use-requirements para construcao relaxada."
            )
        log(f"Modo estrito de producao: instalando via lockfile com --require-hashes: {target_install_file.name} ...")
        pip_args = [
            "-m", "pip", "install",
            "-r", str(target_install_file),
            "--require-hashes", "--no-deps", "--no-warn-script-location",
        ]

    run_runtime_cmd(
        staging_python,
        pip_args,
        build_env,
        f"Instalacao de pacotes a partir de {target_install_file.name}",
    )

    # 10. Validacao exaustiva de imports e seguranca
    verification_data = verify_runtime_environment(staging_python, ROOT_DIR)

    # 11. Otimizacao opcional de ferramentas de build
    if strip_build_tools:
        strip_build_artifacts(STAGING_DIR)

    # 12. Coletar manifesto de pacotes e gerar RUNTIME_INFO.json
    installed_packages = get_installed_packages(staging_python)
    runtime_size_bytes = calculate_dir_size(STAGING_DIR)
    runtime_size_mb = round(runtime_size_bytes / (1024 * 1024), 2)

    manifest: dict[str, Any] = {
        "runtime_name": "ULTRON-Python-Embedded",
        "python_version": python_version,
        "architecture": PYTHON_ARCH,
        "bitness": PYTHON_BITNESS,
        "build_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "build_duration_seconds": round(time.time() - start_time, 2),
        "source_lockfile": str(target_install_file.name) if not use_requirements else None,
        "embed_distribution": {
            "url": embed_url,
            "sha256": embed_sha256,
        },
        "get_pip": {
            "url": GET_PIP_URL,
            "sha256": GET_PIP_SHA256,
        },
        "size_bytes": runtime_size_bytes,
        "size_mb": runtime_size_mb,
        "stripped_build_tools": strip_build_tools,
        "removed_python312_zip": remove_zip,
        "verified_modules_count": len(verification_data["modules"]),
        "installed_packages_count": len(installed_packages),
        "installed_packages": installed_packages,
        "verified_modules": verification_data["modules"],
    }

    manifest_file = STAGING_DIR / "RUNTIME_INFO.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Manifesto gerado em {manifest_file.name} ({len(installed_packages)} pacotes registrados).")

    # 13. Publicacao Atomica com Rollback
    safe_atomic_replace(STAGING_DIR, target_dir)

    total_time = round(time.time() - start_time, 2)
    log("=" * 70)
    log(f"SUCESSO: Runtime Python Embedded construido com exito em {total_time}s!")
    log(f"Caminho: {target_dir}")
    log(f"Tamanho total: {runtime_size_mb} MB")
    log("=" * 70)
    return target_dir


def check_existing_runtime(runtime_dir: Path) -> bool:
    recover_incomplete_state(runtime_dir)
    python_exe = runtime_dir / "python.exe"
    manifest_file = runtime_dir / "RUNTIME_INFO.json"
    pth_files = list(runtime_dir.glob("python*._pth"))

    if not python_exe.exists():
        log(f"FALHA: python.exe ausente em {runtime_dir}")
        return False
    if not manifest_file.exists():
        log(f"FALHA: RUNTIME_INFO.json ausente em {runtime_dir}")
        return False
    if not pth_files:
        log(f"FALHA: Arquivo ._pth ausente em {runtime_dir}")
        return False

    # Checar integridade de DLLs essenciais
    essential_dlls = ["python3.dll", "vcruntime140.dll", "vcruntime140_1.dll", "sqlite3.dll"]
    for dll in essential_dlls:
        if not (runtime_dir / dll).exists():
            log(f"FALHA: DLL essencial ausente: {dll}")
            return False

    try:
        verify_runtime_environment(python_exe, ROOT_DIR)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        log(f"Runtime valido em {runtime_dir}: Python {manifest.get('python_version')}, {manifest.get('size_mb')} MB.")
        return True
    except Exception as e:
        log(f"Falha na validacao do runtime: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Construcao automatizada do Python 3.12 Embedded para ULTRON Desktop.")
    parser.add_argument("--clean", action="store_true", help="Limpa artefatos anteriores antes de construir.")
    parser.add_argument("--check", action="store_true", help="Valida um runtime ja construido.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Diretorio de saida do runtime.")
    parser.add_argument("--python-version", default=DEFAULT_PYTHON_VERSION, choices=list(OFFICIAL_EMBED_RELEASES.keys()), help="Versao do Python Embed a ser utilizada.")
    parser.add_argument("--lockfile", type=Path, default=None, help="Caminho para arquivo lock customizado.")
    parser.add_argument("--use-requirements", action="store_true", help="Permite instalar de requirements.txt sem lockfile estrito.")
    parser.add_argument("--strip-build-tools", action="store_true", help="Remove pip, setuptools e wheel do runtime final.")
    parser.add_argument("--remove-zip", action="store_true", help="Remove python312.zip apos extracao para Lib/.")
    args = parser.parse_args()

    if args.check:
        valid = check_existing_runtime(args.output_dir)
        return 0 if valid else 1

    try:
        build_runtime(
            output_dir=args.output_dir,
            clean=args.clean,
            python_version=args.python_version,
            lockfile=args.lockfile,
            use_requirements=args.use_requirements,
            strip_build_tools=args.strip_build_tools,
            remove_zip=args.remove_zip,
        )
        return 0
    except Exception as e:
        log(f"ERRO CRITICO NA CONSTRUCAO: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
