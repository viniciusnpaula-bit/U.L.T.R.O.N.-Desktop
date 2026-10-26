"""Hardware do PC: CPU, memória, GPU e discos — só leitura, sem privilégio.

A GPU vem do WMI (Windows) e, quando existe, do `nvidia-smi`. Se o WMI falhar,
o relatório continua com o que o psutil sabe: nunca inventa modelo nem VRAM.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time

import psutil

_CACHE = {"ts": 0.0, "texto": ""}
_CACHE_SEGUNDOS = 60
_GB = 1024 ** 3


def _powershell(comando: str, timeout: float = 12.0) -> str:
    """Roda um comando somente-leitura do PowerShell e devolve a saída."""
    exe = shutil.which("powershell") or "powershell"
    criacao = 0x08000000 if os.name == "nt" else 0
    feito = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", comando],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=criacao,
    )
    return (feito.stdout or "").strip()


def _json(texto: str):
    try:
        return json.loads(texto) if texto else None
    except (TypeError, ValueError):
        return None


def _cpu_e_gpu():
    """Nome da CPU e da GPU pelo WMI; devolve (cpu, gpu) ou (None, None)."""
    comando = (
        "$c = Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors;"
        "$g = Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion;"
        "[pscustomobject]@{cpu=$c; gpu=@($g)} | ConvertTo-Json -Compress -Depth 4"
    )
    dados = _json(_powershell(comando))
    if not isinstance(dados, dict):
        return None, None
    cpu = dados.get("cpu") if isinstance(dados.get("cpu"), dict) else None
    gpu = dados.get("gpu")
    if isinstance(gpu, dict):
        gpu = [gpu]
    gpus = [g for g in (gpu or []) if isinstance(g, dict) and g.get("Name")]
    return cpu, gpus


def _nvidia() -> str:
    """VRAM real pelo nvidia-smi, quando a NVIDIA está instalada."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return ""
    try:
        feito = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except Exception:
        return ""
    linhas = [l.strip() for l in (feito.stdout or "").splitlines() if l.strip()]
    return "; ".join(linhas[:2])


def _discos() -> list[str]:
    linhas = []
    for parte in psutil.disk_partitions(all=False):
        opcoes = (parte.opts or "").lower()
        if "cdrom" in opcoes or "removable" in opcoes:
            continue
        try:
            uso = psutil.disk_usage(parte.mountpoint)
        except OSError:
            continue
        linhas.append(
            f"{parte.device.rstrip(chr(92))} ({parte.fstype or '?'}): "
            f"{uso.total / _GB:.1f} GB no total, {uso.free / _GB:.1f} GB livres"
        )  # chr(92) = barra invertida, sem escapar string dentro de f-string
    return linhas


def _uptime() -> str:
    segundos = max(0, int(time.time() - psutil.boot_time()))
    horas, resto = divmod(segundos, 3600)
    minutos = resto // 60
    if horas >= 24:
        return f"{horas // 24} dia(s) e {horas % 24} h"
    return f"{horas} h {minutos} min"


def descrever(forcar: bool = False) -> str:
    """Relatório curto em texto. Cache de 60 s para não repetir o WMI a cada pergunta."""
    if not forcar and time.time() - _CACHE["ts"] < _CACHE_SEGUNDOS and _CACHE["texto"]:
        return _CACHE["texto"]

    cpu_wmi, gpus = (None, None)
    if os.name == "nt":
        try:
            cpu_wmi, gpus = _cpu_e_gpu()
        except Exception:
            cpu_wmi, gpus = None, None

    linhas = []
    if cpu_wmi and cpu_wmi.get("Name"):
        nucleos = cpu_wmi.get("NumberOfCores") or psutil.cpu_count(logical=False) or "?"
        threads = cpu_wmi.get("NumberOfLogicalProcessors") or psutil.cpu_count() or "?"
        linhas.append(f"CPU: {cpu_wmi['Name'].strip()} ({nucleos} núcleos, {threads} threads)")
    else:
        modelo = platform.processor() or platform.machine() or "desconhecida"
        linhas.append(f"CPU: {modelo} ({psutil.cpu_count(logical=False) or '?'} núcleos, "
                      f"{psutil.cpu_count() or '?'} threads)")
    linhas.append(f"Uso agora: CPU {psutil.cpu_percent(interval=0.2):.0f}%, "
                  f"memória {psutil.virtual_memory().percent:.0f}%")

    memoria = psutil.virtual_memory()
    linhas.append(f"Memória: {memoria.total / _GB:.1f} GB no total, {memoria.available / _GB:.1f} GB disponíveis")

    if gpus:
        for gpu in gpus[:3]:
            nome = str(gpu.get("Name", "")).strip()
            driver = str(gpu.get("DriverVersion", "")).strip()
            linhas.append("GPU: " + nome + (f" (driver {driver})" if driver else ""))
    else:
        linhas.append("GPU: não consegui identificar pelo WMI.")

    nvidia = _nvidia()
    if nvidia:
        linhas.append(f"VRAM (nvidia-smi): {nvidia} MB")

    discos = _discos()
    if discos:
        linhas.extend("Disco: " + d for d in discos)
    else:
        linhas.append("Disco: não consegui listar.")
    linhas.append(f"Ligado há {_uptime()}")

    texto = "\n".join(linhas)
    _CACHE.update(ts=time.time(), texto=texto)
    return texto
