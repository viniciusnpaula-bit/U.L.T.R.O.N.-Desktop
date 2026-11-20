"""Build the ULTRON Desktop distribution with clean native PE binaries.

    python tools/build_setup.py                 # build ULTRON.exe, ULTRON-Setup.exe and Inno installer
    python tools/build_setup.py --zip           # also rebuild ULTRON-Desktop-vX.zip
    python tools/build_setup.py --launcher-only # rebuild only native ULTRON.exe launcher

Why ULTRON.exe is compiled natively (csc.exe) instead of PyInstaller --onefile:
PyInstaller --onefile extracts a temporary Python runtime into %TEMP%\\_MEI* and
uses a generic bootloader stub frequently flagged as a false positive (Trojan/PUA)
by Windows Defender. The native launcher delegates directly to the embedded
runtime/python interpreter without extracting anything to %TEMP%.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
BUILD = ROOT / "build"
DIST = BUILD / "dist"
EXE_NAME = "ULTRON-Setup.exe"


def step(title: str) -> None:
    print(f"\n== {title}")


def run(command: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(command))
    completed = subprocess.run(command, cwd=str(cwd) if cwd else None)
    if completed.returncode != 0:
        raise SystemExit(f"comando falhou ({completed.returncode}): {command[0]}")


def python_exe() -> str:
    return sys.executable


def _product_version() -> tuple[str, str, str]:
    product_version = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))["version"]
    major, minor, patch = (product_version.split(".") + ["0", "0"])[:3]
    return product_version, f"{major}.{minor}.{patch}.0", f"{major}, {minor}, {patch}, 0"


def check_icon() -> None:
    step("Validando o ícone")
    run([python_exe(), str(TOOLS / "make_icon.py"), "--check"])


def ensure_icon() -> None:
    step("Gerando o ícone multi-resolução")
    run([python_exe(), str(TOOLS / "make_icon.py")])


def find_csc() -> Path | None:
    windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
    for rel in (
        r"Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        r"Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ):
        cand = windir / rel
        if cand.is_file():
            return cand
    found = shutil.which("csc")
    return Path(found) if found else None


def find_inno_compiler() -> Path | None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for cand in candidates:
        if str(cand) and cand.is_file():
            return cand
    found = shutil.which("iscc")
    return Path(found) if found else None


def sign_if_configured(paths: list[Path]) -> None:
    pfx = (os.environ.get("ULTRON_SIGN_PFX") or "").strip()
    if not pfx:
        return
    signtool = shutil.which("signtool")
    if not signtool:
        print("  (aviso: ULTRON_SIGN_PFX definido, mas signtool.exe não encontrado no PATH)")
        return
    step("Assinando binários com Authenticode")
    password = os.environ.get("ULTRON_SIGN_PASSWORD", "")
    ts_url = os.environ.get("ULTRON_SIGN_TIMESTAMP_URL", "http://timestamp.digicert.com")
    for path in paths:
        if not path.is_file():
            continue
        cmd = [signtool, "sign", "/fd", "SHA256", "/f", pfx, "/tr", ts_url, "/td", "SHA256"]
        if password:
            cmd.extend(["/p", password])
        cmd.append(str(path))
        run(cmd)


def build_native_launcher(name: str = "ULTRON") -> Path:
    """Compile the clean native Windows PE launcher (zero PyInstaller --onefile)."""
    csc = find_csc()
    source = TOOLS / "ultron_launcher.cs"
    if not csc or not source.is_file():
        return build_exe(
            name=name,
            entry="launcher.py",
            console=False,
            description="Painel do U.L.T.R.O.N. Desktop",
            onefile=False,
        )

    step(f"Compilando launcher nativo {name}.exe (sem PyInstaller)")
    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    product_version, version_4, _ = _product_version()
    assembly_info = BUILD / f"AssemblyInfo_{name}.cs"
    assembly_info.write_text(
        f"""using System.Reflection;

[assembly: AssemblyTitle("U.L.T.R.O.N. Desktop")]
[assembly: AssemblyDescription("Launcher oficial do U.L.T.R.O.N. Desktop")]
[assembly: AssemblyCompany("ULTRON")]
[assembly: AssemblyProduct("U.L.T.R.O.N. Desktop")]
[assembly: AssemblyCopyright("Copyright (C) 2026 ULTRON")]
[assembly: AssemblyVersion("{version_4}")]
[assembly: AssemblyFileVersion("{version_4}")]
[assembly: AssemblyInformationalVersion("{product_version}")]
""",
        encoding="utf-8",
    )
    out_exe = DIST / f"{name}.exe"
    icon = ROOT / "electron" / "assets" / "ULTRON.ico"
    run([
        str(csc),
        "/nologo",
        "/target:winexe",
        "/platform:anycpu",
        "/optimize+",
        f"/win32icon:{icon}",
        f"/out:{out_exe}",
        "/reference:System.Windows.Forms.dll",
        str(source),
        str(assembly_info),
    ])
    if not out_exe.is_file():
        raise SystemExit(f"{name}.exe não foi gerado")
    target = ROOT / f"{name}.exe"
    shutil.copyfile(out_exe, target)
    return target


def build_exe(name: str = "ULTRON-Setup", entry: str = "installer/ultron_setup.py",
              description: str = "Instalador do U.L.T.R.O.N. Desktop",
              console: bool = True, onefile: bool = True) -> Path:
    step(f"Compilando {name}")
    DIST.mkdir(parents=True, exist_ok=True)
    work = BUILD / f"pyinstaller-{name}"
    version_file = BUILD / f"version_info_{name}.txt"
    product_version, _, versao_num = _product_version()
    major, minor, patch = (product_version.split(".") + ["0", "0"])[:3]
    versao_txt = f"{major}.{minor}.{patch}"
    version_file.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({versao_num}), prodvers=({versao_num}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'ULTRON'),
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{versao_txt}.0'),
        StringStruct('InternalName', '{name}'),
        StringStruct('OriginalFilename', '{name}.exe'),
        StringStruct('ProductName', 'U.L.T.R.O.N. Desktop'),
        StringStruct('ProductVersion', '{versao_txt}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    cmd = [
        python_exe(), "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile" if onefile else "--onedir",
        "--console" if console else "--windowed",
        "--name", name,
        "--icon", str(ROOT / "electron" / "assets" / "ULTRON.ico"),
        "--version-file", str(version_file),
        "--distpath", str(DIST),
        "--workpath", str(work),
        "--specpath", str(BUILD),
        "--log-level", "WARN",
        str(ROOT / entry),
    ]
    run(cmd)
    exe = (DIST / f"{name}.exe") if onefile else (DIST / name / f"{name}.exe")
    if not exe.is_file():
        raise SystemExit(f"{name}.exe não foi gerado")
    if onefile:
        shutil.copyfile(exe, ROOT / f"{name}.exe")
        return ROOT / f"{name}.exe"
    return exe


def build_inno_installer() -> Path | None:
    iscc = find_inno_compiler()
    iss = ROOT / "installer" / "ultron_setup.iss"
    if not iscc or not iss.is_file():
        return None
    step("Compilando instalador Inno Setup")
    product_version, _, _ = _product_version()
    run([str(iscc), f"/DMyAppVersion={product_version}", str(iss)])
    out = ROOT / "installer" / "dist" / f"ULTRON-Setup-v{product_version}.exe"
    if not out.is_file():
        raise SystemExit(f"Instalador Inno Setup não foi gerado em {out}")
    return out


def write_checksums(paths: list[Path]) -> Path:
    target = DIST / "SHA256SUMS.txt"
    lines = []
    for path in paths:
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
        print(f"  sha256 {path.name}: {digest}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def build_zip(output: Path | None = None) -> Path:
    step("Montando o ZIP de distribuição")
    package_version = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))["version"]
    output = Path(output) if output else ROOT.parent / f"ULTRON-Desktop-v{package_version}.zip"
    skip_dirs = {"build", "venv", "node_modules", ".venv", "__pycache__", "logs", "dados",
                 "runtime", ".git", ".pytest_cache", "out",
                 ".internal", ".beads", ".agents", ".claude", ".codex", ".cursor"}
    members: list[Path] = []
    for item in sorted(ROOT.rglob("*")):
        relative = item.relative_to(ROOT)
        if any(part in skip_dirs for part in relative.parts):
            continue
        if any(part.startswith(("dist", "build-")) for part in relative.parts[:2]):
            continue
        if item.is_dir():
            continue
        if item.suffix.lower() in {".pyc", ".pyo", ".log", ".zip", ".spec", ".tmp"}:
            continue
        if item.name in {"preview-mock.js", "preview.html"}:
            continue
        if item.name.startswith(".ultron-") or item.name in {"setup.log", "SHA256SUMS.txt", ".env"}:
            continue
        if item.name.endswith((".gate.lock", ".lock")):
            continue
        if item.name.endswith((".db", ".sqlite", ".sqlite3")) or relative.parts[0] in {"logs", "dados"}:
            continue
        if item.stat().st_size > 40 * 1024 * 1024:
            print(f"  (ignorado por tamanho: {relative})")
            continue
        members.append(item)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in members:
            archive.write(item, item.relative_to(ROOT).as_posix())
    print(f"  {output} ({len(members)} arquivos, {output.stat().st_size / 1024 / 1024:.1f} MB)")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", action="store_true", help="também gerar o ZIP de distribuição")
    parser.add_argument("--icon-only", action="store_true", help="só regerar o ícone")
    parser.add_argument("--launcher-only", action="store_true", help="só compilar o launcher nativo ULTRON.exe")
    parser.add_argument("--skip-inno", action="store_true", help="não recompilar o instalador Inno Setup")
    arguments = parser.parse_args()
    ensure_icon()
    check_icon()
    if arguments.icon_only:
        return 0
    app_exe = build_native_launcher(name="ULTRON")
    if arguments.launcher_only:
        sign_if_configured([app_exe])
        write_checksums([app_exe])
        print("\nPronto:", app_exe)
        return 0
    setup_exe = build_exe()
    artifacts = [setup_exe, app_exe]
    sign_if_configured(artifacts)
    if not arguments.skip_inno:
        inno_exe = build_inno_installer()
        if inno_exe is not None:
            sign_if_configured([inno_exe])
            artifacts.append(inno_exe)
    write_checksums(artifacts)
    if arguments.zip:
        archive = build_zip()
        artifacts.append(archive)
        write_checksums(artifacts)
    print("\nPronto:", ", ".join(str(path) for path in artifacts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
