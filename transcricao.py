"""Transcrição de voz pela API gratuita da Groq (Whisper).

Fluxo: PCM 16 kHz mono -> WAV em memória -> Whisper large-v3 -> texto + confiança.

Regras de ouro:
  * nada de arquivo temporário e nada de áudio nos logs;
  * o plano gratuito da Groq não cobra: se o limite estourar, devolve erro e o
    chamador cai para o Google/nativo;
  * a confiança vem dos metadados do próprio Whisper (avg_logprob,
    no_speech_prob, compression_ratio), não de adivinhação.
"""
from __future__ import annotations

import io
import threading
import time
import wave
from array import array

import requests

import config

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODELO = "whisper-large-v3"
IDIOMA = "pt"

# Limiares calibrados com comandos curtos em português (teste real de 26/10/2026):
# acertos ficaram entre -0,11 e -0,43; o erro "Crono" por "Chrome" veio -0,358.
LIMITE_MEDIA = -0.35
LIMITE_BAIXA = -0.60
LIMITE_DESCARTA = -1.0      # abaixo disso o texto é lixo/alucinação: não vira comando
LIMITE_SEM_FALA = 0.60
LIMITE_COMPRESSAO = 2.40

TIMEOUT = (3.05, 10.0)
MAX_FALHAS = 2
DESCANSO = 300.0
# RMS mínimo (int16) para valer uma requisição. Fala normal fica acima de 150;
# silêncio digital fica em 0. Evita gastar cota e evita alucinação do Whisper.
LIMITE_ENERGIA = 50.0

_trava = threading.Lock()
_falhas = 0
_aberto_ate = 0.0


def reiniciar_disjuntor() -> None:
    """Zera o disjuntor (usado nos testes e quando o usuário troca a chave)."""
    global _falhas, _aberto_ate
    with _trava:
        _falhas = 0
        _aberto_ate = 0.0


def _disjuntor_aberto() -> bool:
    with _trava:
        return time.monotonic() < _aberto_ate


def _registrar_falha() -> None:
    global _falhas, _aberto_ate
    with _trava:
        _falhas += 1
        if _falhas >= MAX_FALHAS:
            _aberto_ate = time.monotonic() + DESCANSO


def _registrar_sucesso() -> None:
    global _falhas, _aberto_ate
    with _trava:
        _falhas = 0
        _aberto_ate = 0.0


def chave() -> str:
    return str(config.CHAVES.get("groq") or "").strip()


def disponivel() -> bool:
    return bool(chave()) and not _disjuntor_aberto()


def wav(pcm: bytes, fs: int = 16000) -> bytes:
    """Empacota PCM int16 mono no WAV que a Groq espera (sem tocar no disco)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(int(fs) or 16000)
        arquivo.writeframes(pcm)
    return buffer.getvalue()


def energia(pcm: bytes) -> float:
    """RMS do PCM int16. Barato e suficiente para separar silêncio de fala."""
    amostras = array("h")
    amostras.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    if not amostras:
        return 0.0
    return (sum(a * a for a in amostras) / len(amostras)) ** 0.5


def montar_prompt() -> str:
    """Vocabulário do ULTRON para o Whisper acertar nomes e comandos.

    O limite da API é 224 tokens; 900 caracteres em português ficam abaixo disso.
    """
    partes = ["Ei, ULTRON."]
    try:
        import fala
        partes.append("Comandos: " + ", ".join(fala.COMANDOS_CONHECIDOS) + ".")
        apps = sorted({str(v) for v in fala.APPS.values() if str(v).strip()})
        partes.append("Aplicativos: " + ", ".join(apps) + ".")
    except Exception:
        pass
    try:
        import correcoes_voz
        nomes = sorted({str(v).strip() for v in correcoes_voz.carregar().values()
                        if str(v).strip()})
        if nomes:
            partes.append("Nomes e termos: " + ", ".join(nomes[:40]) + ".")
    except Exception:
        pass
    return " ".join(partes)[:900]


def nivel_confianca(segmentos) -> dict:
    """Resume os metadados do Whisper em alta/média/baixa confiança."""
    trechos = [s for s in (segmentos or []) if isinstance(s, dict)]
    avg = min((float(s.get("avg_logprob", 0) or 0) for s in trechos), default=None)
    sem_fala = max((float(s.get("no_speech_prob", 0) or 0) for s in trechos), default=None)
    compressao = max((float(s.get("compression_ratio", 0) or 0) for s in trechos), default=None)

    if sem_fala is not None and sem_fala >= LIMITE_SEM_FALA:
        nivel, motivo = "baixa", "provável ausência de fala"
    elif compressao is not None and compressao >= LIMITE_COMPRESSAO:
        nivel, motivo = "baixa", "repetição ou ruído na transcrição"
    elif avg is not None and avg <= LIMITE_BAIXA:
        nivel, motivo = "baixa", "áudio com pouca clareza"
    elif avg is not None and avg <= LIMITE_MEDIA:
        nivel, motivo = "media", "confiança média na transcrição"
    else:
        nivel, motivo = "alta", ""
    return {
        "nivel": nivel,
        "motivo": motivo,
        "avg_logprob": avg,
        "no_speech_prob": sem_fala,
        "compression_ratio": compressao,
    }


def _vazio(erro: str | None = None, motivo: str | None = None) -> dict:
    return {"texto": None, "alternativas": [], "confianca": None,
            "motor": "groq", "erro": erro, "motivo": motivo, "latencia": 0.0}


def _espera_do_erro(resposta) -> float:
    try:
        espera = float(resposta.headers.get("retry-after", "0.5"))
    except (TypeError, ValueError):
        espera = 0.5
    return max(0.0, min(espera, 2.0))


def _post(arquivos, dados, chave_api):
    """Uma nova tentativa só em 429/5xx; 401/403 não melhoram repetindo."""
    resposta = None
    for tentativa in range(2):
        resposta = requests.post(
            URL,
            headers={"Authorization": f"Bearer {chave_api}"},
            files=arquivos,
            data=dados,
            timeout=TIMEOUT,
        )
        if resposta.status_code == 429 or 500 <= resposta.status_code < 600:
            if tentativa == 0:
                time.sleep(_espera_do_erro(resposta))
                continue
        return resposta
    return resposta


def transcrever(pcm: bytes, fs: int = 16000) -> dict:
    """Transcreve o PCM. Nunca levanta exceção: erro vira dicionário."""
    if not pcm:
        return _vazio("sem_audio")
    chave_api = chave()
    if not chave_api:
        return _vazio("sem_chave")
    if _disjuntor_aberto():
        return _vazio("disjuntor")
    if energia(pcm) < LIMITE_ENERGIA:
        # Silêncio puro: não gasta cota e evita a alucinação do Whisper.
        return _vazio(motivo="sem_fala")

    dados = {
        "model": MODELO,
        "language": IDIOMA,
        "response_format": "verbose_json",
        "temperature": "0",
        "prompt": montar_prompt(),
    }
    arquivos = {"file": ("fala.wav", wav(pcm, fs), "audio/wav")}
    inicio = time.perf_counter()
    try:
        resposta = _post(arquivos, dados, chave_api)
        latencia = round(time.perf_counter() - inicio, 2)
    except requests.RequestException as erro:
        _registrar_falha()
        return _vazio(f"rede_{type(erro).__name__.lower()}")

    if resposta.status_code != 200:
        _registrar_falha()
        return _vazio(f"http_{resposta.status_code}")

    try:
        corpo = resposta.json()
    except ValueError:
        _registrar_falha()
        return _vazio("resposta_invalida")
    if not isinstance(corpo, dict):
        _registrar_falha()
        return _vazio("resposta_invalida")

    _registrar_sucesso()
    texto = str(corpo.get("text") or "").strip()
    confianca = nivel_confianca(corpo.get("segments") or [])
    if not texto:
        return {**_vazio(motivo="sem_fala"), "confianca": confianca, "latencia": latencia}
    if (confianca.get("no_speech_prob") or 0) >= LIMITE_SEM_FALA:
        # O Whisper às vezes "inventa" texto em silêncio; não deixe isso virar ação.
        return {**_vazio(motivo="sem_fala"), "confianca": confianca, "latencia": latencia}
    if (confianca.get("avg_logprob") is not None
            and confianca["avg_logprob"] <= LIMITE_DESCARTA):
        # Ruído/alucinação: melhor devolver erro e deixar o Google tentar.
        return {**_vazio(erro="baixa_confianca"), "confianca": confianca,
                "latencia": latencia}

    return {
        "texto": texto,
        "alternativas": [texto],
        "confianca": confianca,
        "motor": "groq",
        "modelo": MODELO,
        "erro": None,
        "motivo": None,
        "latencia": latencia,
    }
