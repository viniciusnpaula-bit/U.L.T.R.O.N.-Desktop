"""Reconhecimento de voz nativo do Windows (System.Speech), offline e opcional.

O Windows só reconhece português se o pacote de fala pt-BR estiver instalado.
Quando não está, `disponivel()` devolve False e o ULTRON continua com o Google
(online), sem erro e sem espera extra. O áudio vira um WAV temporário, apagado
logo depois; nada é enviado para a rede por este módulo.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "tools" / "reconhecer_nativo.ps1"
_TRAVA = threading.Lock()
_CULTURAS = None


def _powershell() -> str:
    return os.environ.get("ULTRON_POWERSHELL") or "powershell.exe"


def _executar(argumentos, timeout):
    return subprocess.run(
        argumentos, capture_output=True, text=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def culturas(timeout=8) -> list[str]:
    """Culturas de reconhecimento instaladas no Windows (lista vazia se nenhuma)."""
    global _CULTURAS
    with _TRAVA:
        if _CULTURAS is not None:
            return list(_CULTURAS)
    script = ("Add-Type -AssemblyName System.Speech; "
              "[System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | "
              "ForEach-Object { $_.Culture.Name }")
    try:
        saida = _executar([_powershell(), "-NoProfile", "-NonInteractive", "-Command", script], timeout)
        nomes = [linha.strip() for linha in (saida.stdout or "").splitlines() if linha.strip()] \
            if saida.returncode == 0 else []
    except Exception:
        nomes = []
    with _TRAVA:
        _CULTURAS = tuple(nomes)
    return list(nomes)


def disponivel(cultura="pt-BR") -> bool:
    """Há um reconhecedor instalado para a cultura pedida (ou para português)?"""
    alvo = str(cultura or "").lower()
    for nome in culturas():
        baixo = nome.lower()
        if baixo == alvo or (alvo.startswith("pt") and baixo.startswith("pt")):
            return True
    return False


def _wav(pcm: bytes, taxa: int) -> Path:
    arquivo = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    arquivo.close()
    caminho = Path(arquivo.name)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(taxa))
        w.writeframes(pcm)
    return caminho


def reconhecer(pcm: bytes, taxa=16000, cultura="pt-BR", timeout=15):
    """Transcreve PCM 16-bit mono. Devolve None quando não há motor ou fala."""
    if not pcm:
        return None
    caminho = _wav(pcm, taxa)
    try:
        saida = _executar(
            [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(SCRIPT), str(caminho), str(cultura)], timeout)
        if saida.returncode != 0:
            return None
        texto = (saida.stdout or "").strip()
        return texto or None
    except Exception:
        return None
    finally:
        try:
            caminho.unlink()
        except OSError:
            pass
