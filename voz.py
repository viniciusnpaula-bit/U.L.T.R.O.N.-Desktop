"""Voz: fala (edge-tts, voz grave) e escuta (microfone + reconhecimento do Google, grátis)."""
import asyncio
import json
import collections
import glob
import math
import os
import queue
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import sounddevice as sd
import speech_recognition as sr

import config
import seguranca
from microphone_devices import resolve_input_device

try:
    import transcricao
except Exception:      # atualização parcial: sem o módulo, cai para o Google
    transcricao = None

try:
    import voz_nativa
except Exception:      # o Windows pode não ter PowerShell/System.Speech
    voz_nativa = None

# VAD opcional: webrtcvad quando instalado; caso contrário, um VAD simples em
# Python puro (energia nas bandas de voz humana + cruzamento por zero) que já
# é bem mais robusto que volume RMS sozinho.
try:
    import webrtcvad as _webrtcvad
    _VAD_DISPONIVEL = True
except Exception:
    _webrtcvad = None
    _VAD_DISPONIVEL = False

_VAD_FRAME_MS = 20          # frame de 20 ms (320 amostras a 16 kHz)
_VAD_AGRESSIVIDADE = 2      # 0 (permissivo) a 3 (restrito)
_VAD_VOZ_MIN_HZ = 300       # banda inferior da fala humana
_VAD_VOZ_MAX_HZ = 3400      # banda superior da fala humana


class _Vad:
    """Detecção de atividade de voz.

    Prefere webrtcvad quando instalado. Caso contrário, usa um VAD simples em
    Python puro: um frame é voz quando tem energia nas bandas da fala humana
    (300-3400 Hz) e padrão de cruzamento por zero compatível — muito mais
    robusto que volume RMS sozinho, que confunde silêncio com voz baixa.
    """

    def __init__(self, agressividade=_VAD_AGRESSIVIDADE):
        self.disponivel = _VAD_DISPONIVEL
        self._vad = None
        if self.disponivel:
            try:
                self._vad = _webrtcvad.Vad(agressividade)
            except Exception:
                self.disponivel = False
                self._vad = None
        self._frame = int(16000 * _VAD_FRAME_MS / 1000)  # 320 amostras

    def _energia_bandas_voz(self, quadro: np.ndarray) -> float:
        """Energia normalizada nas bandas de frequência da fala humana."""
        if quadro.size < self._frame:
            return 0.0
        janela = np.hanning(quadro.size)
        espectro = np.abs(np.fft.rfft(quadro.astype(np.float32) * janela))
        freqs = np.fft.rfftfreq(quadro.size, d=1 / 16000)
        mask = (freqs >= _VAD_VOZ_MIN_HZ) & (freqs <= _VAD_VOZ_MAX_HZ)
        if not mask.any():
            return 0.0
        total = float(espectro.sum()) or 1.0
        return float(espectro[mask].sum() / total)

    def _taxa_cruzamento_zero(self, quadro: np.ndarray) -> float:
        """Taxa de cruzamento por zero: voz tem padrão característico."""
        if quadro.size < 2:
            return 0.0
        sinais = np.sign(quadro.astype(np.float32))
        mudancas = np.where(sinais[:-1] * sinais[1:] < 0, 1, 0)
        return float(mudancas.sum()) / max(quadro.size - 1, 1)

    def is_speech(self, quadro: np.ndarray, sample_rate: int = 16000) -> bool:
        """True se o quadro parece fala humana."""
        quadro = np.asarray(quadro, dtype=np.int16).reshape(-1)
        if quadro.size != self._frame:
            # preenche/corta para o tamanho do frame
            if quadro.size < self._frame:
                quadro = np.pad(quadro, (0, self._frame - quadro.size))
            else:
                quadro = quadro[: self._frame]
        if self.disponivel and self._vad is not None:
            try:
                return bool(self._vad.is_speech(quadro.tobytes(), sample_rate))
            except Exception:
                pass
        # Fallback puro Python: energia em bandas de voz + ZCR.
        energia = self._energia_bandas_voz(quadro)
        zcr = self._taxa_cruzamento_zero(quadro)
        nivel = float(np.sqrt(np.mean(quadro.astype(np.float32) ** 2)))
        # Voz: energia nas bandas de fala, ZCR na faixa da voz (não muito baixa,
        # não muito alta) e nível acima de um ruído mínimo.
        return (
            energia > 0.25
            and 0.02 < zcr < 0.35
            and nivel > 60
        )


_lock_fala = threading.RLock()
_parar = threading.Event()
falando = threading.Event()   # ligado enquanto o ULTRON está falando (a interface mostra no orbe)


def parar_fala():
    _parar.set()


def limpar(texto):
    texto = re.sub(r"https?://\S+", "", texto)
    texto = re.sub(r"[*#_`>~|]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


async def _sintetizar(texto, arquivo):
    import edge_tts
    await edge_tts.Communicate(texto, config.VOZ, rate=config.VOZ_RATE, pitch=config.VOZ_PITCH).save(arquivo)


def _tocar(arquivo):
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    pygame.mixer.music.load(arquivo)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy() and not _parar.is_set():
        time.sleep(0.05)
    pygame.mixer.music.stop()
    pygame.mixer.music.unload()
    try:
        os.remove(arquivo)
    except OSError:
        pass


def _falar_offline(texto):
    import pyttsx3
    motor = pyttsx3.init()
    for v in motor.getProperty("voices"):
        if "pt" in (v.id + v.name).lower() or "portug" in v.name.lower():
            motor.setProperty("voice", v.id)
            break
    motor.setProperty("rate", 165)
    motor.say(texto)
    motor.runAndWait()


def _frases(texto):
    """Divide em frases (juntando as muito curtas) para tocar a 1ª enquanto a 2ª ainda é gerada."""
    saida = []
    for p in re.split(r"(?<=[.!?])\s+", texto):
        if saida and len(saida[-1]) < 25:
            saida[-1] += " " + p
        else:
            saida.append(p)
    return saida


def falar_partes(partes, eco=0.3):
    """Fala frases conforme elas chegam (streaming da IA).

    Diferente de `falar(texto)`, `partes` é um iterável que pode BLOQUEAR: cada item
    é uma frase completa produzida pela IA. A síntese de cada frase roda em paralelo,
    então a 1ª toca enquanto as próximas ainda estão sendo geradas.
    Devolve o texto completo falado (útil para o histórico e para o painel).
    """
    with _lock_fala:
        _parar.clear()
        t0 = time.perf_counter()
        base = os.path.join(tempfile.gettempdir(), f"ultron_{os.getpid()}_{uuid.uuid4().hex[:6]}")
        fila, parou = queue.Queue(), threading.Event()
        completo = []

        def produzir():
            indice = 0
            try:
                for bruto in partes:
                    if parou.is_set() or _parar.is_set():
                        break
                    for frase in _frases(str(bruto or "").strip()):
                        if not frase.strip():
                            continue
                        completo.append(frase)
                        arq = f"{base}_{indice}.mp3"
                        indice += 1
                        try:
                            asyncio.run(_sintetizar(frase, arq))
                        except Exception as e:
                            seguranca.log.warning(f"Voz online falhou ({e}); usando voz offline.")
                            fila.put((None, " ".join(completo[indice - 1:])))
                            return
                        fila.put((arq, frase))
            finally:
                fila.put(None)

        threading.Thread(target=produzir, daemon=True).start()
        primeira = True
        try:
            while True:
                item = fila.get()
                if item is None:
                    break
                arq, resto = item
                if arq is None:
                    falando.set()
                    try:
                        _falar_offline(resto)
                    except Exception as e2:
                        seguranca.log.error(f"Voz offline falhou: {e2}")
                    break
                if primeira:
                    seguranca.log.info(f"[tempo] 1º áudio {time.perf_counter() - t0:.1f}s")
                    primeira = False
                    falando.set()
                _tocar(arq)
                if _parar.is_set():
                    break
        finally:
            falando.clear()
            parou.set()
            for sobra in glob.glob(base + "_*.mp3"):
                try:
                    os.remove(sobra)
                except OSError:
                    pass
        time.sleep(eco)  # evita o microfone captar o eco
        return " ".join(completo)


def testar_microfone(segundos=1.5):
    """Mede o nível de entrada por alguns segundos. Não grava nem envia nada."""
    try:
        import sounddevice as sd
        import numpy as np
    except Exception:
        return {"ok": False, "erro": ERROS["sem_microfone"], "nivel": 0}
    try:
        dados = sd.rec(int(segundos * 16000), samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        nivel = float(np.sqrt(np.mean(dados.astype(np.float32) ** 2)))
        return {"ok": nivel > 0, "nivel": int(nivel), "limiar_padrao": 400,
                "resumo": ("O microfone está captando áudio." if nivel > 20
                           else "O microfone respondeu, mas o nível está muito baixo. Aproxime-se ou aumente o ganho.")}
    except Exception as e:
        return {"ok": False, "erro": ERROS["sem_microfone"], "detalhe": type(e).__name__, "nivel": 0}


def testar_voz(texto="Ultrason, testes de voz concluídos."):
    """Fala uma frase curta com a voz configurada (usa a reserva se a online falhar)."""
    try:
        falar(texto, eco=0)
        return {"ok": True, "voz": voz_ativa()}
    except Exception as e:
        return {"ok": False, "erro": "Não consegui falar: a voz online e a reserva falharam.",
                "detalhe": type(e).__name__}


def falar(texto, eco=0.5):
    texto = limpar(texto)
    if not texto:
        return
    with _lock_fala:
        _parar.clear()
        t0 = time.perf_counter()
        frases = _frases(texto)
        base = os.path.join(tempfile.gettempdir(), f"ultron_{os.getpid()}_{uuid.uuid4().hex[:6]}")
        fila, parou = queue.Queue(), threading.Event()

        def produzir():
            for i, f in enumerate(frases):
                if parou.is_set() or _parar.is_set():
                    break
                arq = f"{base}_{i}.mp3"
                try:
                    asyncio.run(_sintetizar(f, arq))
                except Exception as e:
                    seguranca.log.warning(f"Voz online falhou ({e}); usando voz offline.")
                    fila.put((None, " ".join(frases[i:])))
                    return
                fila.put((arq, f))
            fila.put(None)

        threading.Thread(target=produzir, daemon=True).start()
        primeira = True
        try:
            while True:
                item = fila.get()
                if item is None:
                    break
                arq, resto = item
                if arq is None:
                    falando.set()
                    try:
                        _falar_offline(resto)
                    except Exception as e2:
                        seguranca.log.error(f"Voz offline falhou: {e2}")
                    break
                if primeira:
                    seguranca.log.info(f"[tempo] 1º áudio {time.perf_counter() - t0:.1f}s")
                    primeira = False
                    falando.set()
                _tocar(arq)
                if _parar.is_set():
                    break
        finally:
            falando.clear()
            parou.set()
            for sobra in glob.glob(base + "_*.mp3"):   # arquivos gerados mas não tocados (parada)
                try:
                    os.remove(sobra)
                except OSError:
                    pass
        time.sleep(eco)  # evita o microfone captar o eco


# Erros de voz em português: o que houve e o que fazer (nada de mensagem técnica solta).
ERROS = {
    "sem_microfone": "Nenhum microfone disponível. Conecte um microfone ou escolha outra entrada em Ajustes › Voz.",
    "microfone_desconectado": "O microfone selecionado foi desconectado. Escolha outra entrada em Ajustes › Voz.",
    "sem_internet": "O reconhecimento de voz precisa de internet e ela parece estar fora. Os comandos escritos continuam funcionando.",
    "nao_entendi": "Não entendi a fala. Repita mais devagar ou escreva o comando.",
    "silencio": "Não ouvi nada. Fale mais perto do microfone.",
    "audio_falhou": "O microfone parou de enviar áudio. Vou tentar reiniciar a captura.",
    "calibracao": "Não consegui medir o ruído do ambiente. Vou seguir com o limiar padrão.",
}

try:   # preferências salvas vencem o .env, mas nunca quebram a inicialização
    _pref = preferencias()
    config.VOZ, config.VOZ_PITCH, config.VOZ_RATE = _pref["voz"], _pref["pitch"], _pref["rate"]
except Exception:
    pass

VOZES_PT = [
    {"id": "pt-BR-AntonioNeural", "rotulo": "Antônio (masculina, grave)"},
    {"id": "pt-BR-FranciscaNeural", "rotulo": "Francisca (feminina)"},
    {"id": "pt-BR-ThalitaNeural", "rotulo": "Thalita (feminina, jovem)"},
    {"id": "pt-BR-BrendaNeural", "rotulo": "Brenda (feminina, calma)"},
    {"id": "pt-BR-DonatoNeural", "rotulo": "Donato (masculina)"},
    {"id": "pt-BR-FabioNeural", "rotulo": "Fábio (masculina)"},
    {"id": "pt-BR-GiovannaNeural", "rotulo": "Giovanna (feminina)"},
    {"id": "pt-BR-HumbertoNeural", "rotulo": "Humberto (masculina, madura)"},
    {"id": "pt-BR-JulioNeural", "rotulo": "Júlio (masculina)"},
    {"id": "pt-BR-LeilaNeural", "rotulo": "Leila (feminina)"},
    {"id": "pt-BR-LeticiaNeural", "rotulo": "Letícia (feminina)"},
    {"id": "pt-BR-ManuelaNeural", "rotulo": "Manuela (feminina)"},
    {"id": "pt-BR-NicolauNeural", "rotulo": "Nicolau (masculina)"},
    {"id": "pt-BR-ValerioNeural", "rotulo": "Valério (masculina)"},
    {"id": "pt-BR-YaraNeural", "rotulo": "Yara (feminina)"},
]


ARQUIVO_PREFERENCIAS = Path(__file__).resolve().parent / "dados" / "voz.json"


def preferencias():
    """Preferências de voz salvas (voz, tom, velocidade). Padrão = .env."""
    base = {"voz": getattr(config, "VOZ", "pt-BR-AntonioNeural"),
            "pitch": getattr(config, "VOZ_PITCH", "-12Hz"),
            "rate": getattr(config, "VOZ_RATE", "+0%")}
    try:
        salvo = json.loads(ARQUIVO_PREFERENCIAS.read_text(encoding="utf-8"))
        for chave, limite in (("voz", 64), ("pitch", 12), ("rate", 12)):
            if isinstance(salvo.get(chave), str) and salvo[chave].strip():
                base[chave] = salvo[chave].strip()[:limite]
    except (OSError, ValueError, AttributeError):
        pass
    return base


def salvar_preferencias(valores):
    """Grava a escolha do usuário e passa a usá-la na hora."""
    atual = preferencias()
    for chave, limite in (("voz", 64), ("pitch", 12), ("rate", 12)):
        valor = valores.get(chave)
        if isinstance(valor, str) and valor.strip():
            atual[chave] = valor.strip()[:limite]
    ARQUIVO_PREFERENCIAS.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_PREFERENCIAS.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    config.VOZ, config.VOZ_PITCH, config.VOZ_RATE = atual["voz"], atual["pitch"], atual["rate"]
    return atual


def restaurar_preferencias():
    try:
        ARQUIVO_PREFERENCIAS.unlink()
    except FileNotFoundError:
        pass
    return preferencias()


def vozes_disponiveis():
    """Catálogo conhecido do Edge TTS (online). A voz reserva local é o pyttsx3."""
    return [dict(v) for v in VOZES_PT]


def voz_ativa():
    return {"id": getattr(config, "VOZ", "pt-BR-AntonioNeural"), "reserva": "pyttsx3 (local, sem internet)"}


class Ouvido:
    FS = 16000

    # Recalibração automática do limiar durante o uso.
    # Se passar esse tempo sem um comando reconhecido, ou se vários "não entendi"
    # seguidos acontecerem, o limiar de volume é reajustado ao ruído atual do
    # ambiente. Nunca recalibra enquanto o ULTRON está falando (não captura eco).
    RECALIBRAR_SEM_COMANDO_SEG = 300          # 5 minutos sem comando reconhecido
    MAX_NAO_ENTENDI_RECALIBRAR = 3            # não-entendi seguidos que disparam recalibração

    def __init__(self, device_index=None, device_id=None):
        self.rec = sr.Recognizer()
        self.limiar = getattr(config, "LIMIAR_VOZ", 0) or 400.0
        self.pausado = None  # threading.Event: quando ligado, o microfone é liberado
        self.capturando = threading.Event()  # ligado somente enquanto InputStream está aberto
        self.ultimo_erro = None
        self.ultimo_stt = None
        self.nivel_atual = 0.0
        self.device_index = device_index
        self.device_id = device_id
        self.device_generation = 0
        self.nativo_tentado = False
        self.nativo_ok = False
        self.rec.operation_timeout = 15
        self.vad = _Vad()
        # Estado da recalibração automática.
        self._ultimo_comando_ok = 0.0         # timestamp do último comando reconhecido
        self._nao_entendi_consecutivos = 0    # contador de "não entendi" seguidos

    def set_device(self, device_index, device_id=None):
        self.device_index = device_index
        self.device_id = device_id
        self.device_generation += 1

    def _capture_device(self):
        if self.device_id is not None:
            index = resolve_input_device(self.device_id)
            if index is None:
                raise RuntimeError("O microfone selecionado foi desconectado. Escolha outra entrada de áudio.")
            self.device_index = index
        if self.device_index == -1:
            raise RuntimeError("O microfone selecionado não está disponível. Escolha outra entrada de áudio.")
        return self.device_index

    def _preferir_nativo(self):
        """“sempre”: tenta o motor do Windows antes do Google."""
        return str(getattr(config, "VOZ_NATIVA", "auto")).lower() in ("sempre", "on", "1")

    def _nativo_disponivel(self):
        modo = str(getattr(config, "VOZ_NATIVA", "auto")).lower()
        if voz_nativa is None or modo in ("nunca", "off", "0"):
            return False
        if not getattr(self, "nativo_tentado", False):
            self.nativo_tentado = True
            try:
                self.nativo_ok = bool(voz_nativa.disponivel())
            except Exception:
                self.nativo_ok = False
            if self.nativo_ok:
                seguranca.log.info("Reconhecimento nativo do Windows disponível.")
        return bool(getattr(self, "nativo_ok", False))

    def _tentar_nativo(self, pcm):
        """Transcreve pelo motor do Windows. None quando não há motor ou fala."""
        if not pcm or not self._nativo_disponivel():
            return None
        try:
            texto = voz_nativa.reconhecer(pcm, self.FS)
        except Exception:
            return None
        if texto:
            self.ultimo_erro = None
            seguranca.log.info("[voz] reconhecimento nativo")
            return texto.strip() or None
        return None

    def _motor_escuta(self):
        """Motor principal: auto/groq (Groq grátis), google ou nativo."""
        motor = str(getattr(config, "VOZ_MOTOR", "auto") or "auto").strip().lower()
        return motor if motor in ("auto", "groq", "google", "nativo") else "auto"

    def _tentar_remoto(self, pcm):
        """Transcreve pela Groq. None quando não é remoto ou falhou de verdade.

        Também devolve o resultado quando a Groq conclui que não houve fala:
        nesse caso não vale gastar uma chamada no Google nem contar como
        "não entendi" (o silêncio não pede recalibração).
        """
        if transcricao is None or self._motor_escuta() not in ("auto", "groq"):
            return None
        try:
            resultado = transcricao.transcrever(pcm, self.FS)
        except Exception as erro:
            seguranca.log.warning(f"[stt] falha inesperada ({type(erro).__name__})")
            return None
        self.ultimo_stt = resultado
        if resultado.get("texto"):
            self.ultimo_erro = None
            confianca = (resultado.get("confianca") or {}).get("nivel") or "?"
            seguranca.log.info(
                f"[stt] groq {float(resultado.get('latencia') or 0):.2f}s conf={confianca}")
            return resultado
        if resultado.get("motivo") == "sem_fala":
            return resultado
        if resultado.get("erro"):
            seguranca.log.warning(f"[stt] Groq indisponível ({resultado['erro']})")
        return None

    def calibrar(self):
        self.capturando.set()
        try:
            d = sd.rec(int(1.5 * self.FS), samplerate=self.FS, channels=1, dtype="int16",
                       device=self._capture_device())
            sd.wait()
        finally:
            self.capturando.clear()
        ambiente = float(np.sqrt(np.mean(d.astype(np.float32) ** 2)))
        self.limiar = getattr(config, "LIMIAR_VOZ", 0) or max(300.0, ambiente * 3)
        print(f"[mic] ruído ambiente {ambiente:.0f}, limiar {self.limiar:.0f}")
        # Uma calibração (manual ou automática) sempre reinicia os gatilhos, senão
        # o primeiro laço do uso recalibraria de novo logo após calibrar.
        self._ultimo_comando_ok = time.time()
        self._nao_entendi_consecutivos = 0

    def notificar_comando_reconhecido(self):
        """Chamado quando um comando é reconhecido com sucesso: reseta os gatilhos de recalibração."""
        self._ultimo_comando_ok = time.time()
        self._nao_entendi_consecutivos = 0

    def notificar_nao_entendido(self):
        """Chamado quando a fala não foi compreendida: após N seguidos, dispara recalibração."""
        self._nao_entendi_consecutivos += 1

    def precisa_recalibrar(self) -> bool:
        """True se o limiar deve ser reajustado ao ambiente atual."""
        if self._nao_entendi_consecutivos >= self.MAX_NAO_ENTENDI_RECALIBRAR:
            return True
        if time.time() - self._ultimo_comando_ok > self.RECALIBRAR_SEM_COMANDO_SEG:
            return True
        return False

    def recalibrar_se_necessario(self):
        """Recalibra o limiar se precisar, mas nunca enquanto o ULTRON está falando."""
        import voz as _voz  # falando é um atributo de módulo
        if _voz.falando.is_set():
            return False
        if not self.precisa_recalibrar():
            return False
        self.calibrar()
        self._nao_entendi_consecutivos = 0
        self._ultimo_comando_ok = time.time()
        return True

    def _eh_voz(self, dados: np.ndarray, fator: float = 1.0) -> bool:
        """True se o bloco de áudio contém fala humana (VAD com fallback de volume)."""
        bloco = dados.reshape(-1)
        # 1) webrtcvad, quando instalado: detecção baseada no padrão de voz humana.
        if self.vad.disponivel and self.vad._vad is not None:
            frame = self.vad._frame
            votos = 0
            total = 0
            for ini in range(0, len(bloco) - frame + 1, frame):
                votos += 1 if self.vad.is_speech(bloco[ini:ini + frame]) else 0
                total += 1
            if total == 0:
                return False
            return votos >= max(1, total // 2)  # maioria dos frames de 20 ms é voz
        # 2) Fallback puro Python: energia nas bandas da fala (300-3400 Hz) +
        #    taxa de cruzamento por zero compatível com voz. Muito mais robusto
        #    que volume RMS sozinho, que confunde qualquer som alto com fala.
        #    O nível mínimo vem do limiar calibrado: é isso que faz a
        #    recalibração automática valer alguma coisa quando a sala muda.
        energia = self.vad._energia_bandas_voz(bloco)
        zcr = self.vad._taxa_cruzamento_zero(bloco)
        nivel = float(np.sqrt(np.mean(bloco.astype(np.float32) ** 2)))
        return (
            energia > 0.25
            and 0.02 < zcr < 0.35
            and nivel > max(60.0, self.limiar * 0.5) * fator
        )

    def _gravar(self, espera, max_seg=15, silencio=None, min_voz=3, fator=1.0, gatilho=None):
        """Captura áudio. Com `gatilho` (Event), grava SÓ enquanto ele estiver ligado."""
        silencio = getattr(config, "SILENCIO_FIM", 0.7) if silencio is None else silencio
        if self.pausado is not None and self.pausado.is_set():
            return None
        bloco = int(self.FS * 0.1)
        fila = queue.Queue()
        pre = collections.deque(maxlen=4)
        quadros, falou, sil, voz_n = [], False, 0.0, 0
        ini = ini_fala = time.time()

        def cb(indata, frames, tempo, status):
            fila.put(indata.copy())

        manual = gatilho is not None
        try:
            self.capturando.set()
            with sd.InputStream(samplerate=self.FS, channels=1, dtype="int16", blocksize=bloco,
                                device=self._capture_device(), callback=cb):
                while True:
                    if manual and not gatilho.is_set():
                        break          # soltou a tecla: encerra e usa tudo o que já foi captado
                    if self.pausado is not None and self.pausado.is_set():
                        return None
                    try:
                        dados = fila.get(timeout=3)
                    except queue.Empty:
                        raise RuntimeError("o microfone parou de enviar áudio")
                    nivel = float(np.sqrt(np.mean(dados.astype(np.float32) ** 2)))
                    self.nivel_atual = nivel
                    agora = time.time()
                    if manual:
                        # segurar para falar: guarda tudo, sem depender de limiar/silêncio
                        quadros.append(dados)
                        falou = True
                        if agora - ini > max_seg:
                            break
                        continue
                    if self._eh_voz(dados, fator):
                        if not falou:
                            quadros, falou, ini_fala = list(pre), True, agora
                        sil, voz_n = 0.0, voz_n + 1
                        quadros.append(dados)
                    elif falou:
                        quadros.append(dados)
                        sil += 0.1
                        if sil >= silencio:
                            break
                    else:
                        pre.append(dados)
                        if agora - ini > espera:
                            return None
                    if falou and agora - ini_fala > max_seg:
                        break
        finally:
            self.capturando.clear()
        if voz_n < min_voz:
            return None
        return np.concatenate(quadros).tobytes()

    def escutar_manual(self, limite=30.0):
        """Segurar para falar: grava enquanto `pedido_manual` estiver ligado.

        Devolve o texto reconhecido (None se nada foi dito ou se a escuta estava
        pausada). Nunca grava com a escuta pausada.
        """
        gatilho = getattr(self, "pedido_manual", None)
        if gatilho is None or (self.pausado is not None and self.pausado.is_set()):
            return None
        pcm = self._gravar(0.2, max_seg=limite, silencio=limite, min_voz=1, gatilho=gatilho)
        if not pcm:
            return None
        nativo_tentado = False
        if self._motor_escuta() == "nativo" or self._preferir_nativo():
            nativo = self._tentar_nativo(pcm)
            nativo_tentado = True
            if nativo:
                return nativo
        remoto = self._tentar_remoto(pcm)
        if remoto:
            if not remoto.get("texto"):
                return None
            return remoto["texto"]
        audio = sr.AudioData(pcm, self.FS, 2)
        t0 = time.perf_counter()
        try:
            texto = self.rec.recognize_google(audio, language="pt-BR")
            self.ultimo_erro = None
            seguranca.log.info(f"[tempo] reconhecimento de voz {time.perf_counter() - t0:.1f}s")
            return (texto or "").strip() or None
        except Exception as e:
            if not nativo_tentado:
                nativo = self._tentar_nativo(pcm)
                if nativo:
                    return nativo
            self.ultimo_erro = str(e)[:180]
            seguranca.log.warning(f"Reconhecimento manual falhou ({type(e).__name__})")
            return None

    def escutar_detalhado(self, espera=60):
        """Como escutar(), mas devolve todas as interpretações (para confirmar incerteza).

        Retorna {"texto": str|None, "alternativas": [str], "erro": str|None,
                 "confianca": dict|None}. Nada aqui executa ação: quem decide é o núcleo.
        """
        pcm = self._gravar(espera)
        if not pcm:
            return {"texto": None, "alternativas": [], "erro": None, "confianca": None}
        nativo_tentado = False
        if self._motor_escuta() == "nativo" or self._preferir_nativo():
            nativo = self._tentar_nativo(pcm)
            nativo_tentado = True
            if nativo:
                return {"texto": nativo, "alternativas": [nativo], "erro": None,
                        "confianca": None}
        remoto = self._tentar_remoto(pcm)
        if remoto:
            texto = remoto.get("texto")
            if not texto:
                # Silêncio confirmado pela Groq: nada para o Google acrescentar.
                return {"texto": None, "alternativas": [], "erro": None,
                        "confianca": remoto.get("confianca")}
            return {"texto": texto,
                    "alternativas": remoto.get("alternativas") or [texto],
                    "erro": None,
                    "confianca": remoto.get("confianca")}
        audio = sr.AudioData(pcm, self.FS, 2)
        try:
            r = self.rec.recognize_google(audio, language="pt-BR", show_all=True)
            alternativas = []
            if isinstance(r, dict):
                for alt in r.get("alternative", []):
                    frase = (alt.get("transcript") or "").strip()
                    if frase and frase not in alternativas:
                        alternativas.append(frase)
            self.ultimo_erro = None
            return {"texto": alternativas[0] if alternativas else None,
                    "alternativas": alternativas[:3], "erro": None, "confianca": None}
        except sr.UnknownValueError:
            self.ultimo_erro = None
            return {"texto": None, "alternativas": [], "erro": ERROS["nao_entendi"],
                    "confianca": None}
        except sr.RequestError:
            if not nativo_tentado:
                nativo = self._tentar_nativo(pcm)
                if nativo:
                    return {"texto": nativo, "alternativas": [nativo], "erro": None,
                            "confianca": None}
            self.ultimo_erro = ERROS["sem_internet"]
            return {"texto": None, "alternativas": [], "erro": ERROS["sem_internet"],
                    "confianca": None}

    def escutar(self, espera=60, curto=False):
        """Espera você falar. Devolve o texto (None se nada foi entendido).
        curto=True: modo para respostas rápidas como 'sim'/'não'; devolve uma LISTA de interpretações."""
        if curto:
            pcm = self._gravar(espera, max_seg=5, silencio=0.7, min_voz=2, fator=0.8)
        else:
            pcm = self._gravar(espera)
        if not pcm:
            return None
        nativo_tentado = False
        if self._motor_escuta() == "nativo" or self._preferir_nativo():
            nativo = self._tentar_nativo(pcm)
            nativo_tentado = True
            if nativo:
                return [nativo] if curto else nativo
        remoto = self._tentar_remoto(pcm)
        if remoto:
            texto = remoto.get("texto")
            if not texto:
                return None
            return [texto] if curto else texto
        audio = sr.AudioData(pcm, self.FS, 2)
        t0 = time.perf_counter()
        try:
            if curto:
                r = self.rec.recognize_google(audio, language="pt-BR", show_all=True)
                alts = [a.get("transcript", "") for a in r.get("alternative", [])] if isinstance(r, dict) else []
                self.ultimo_erro = None
                return alts or None
            texto = self.rec.recognize_google(audio, language="pt-BR")
            self.ultimo_erro = None
            seguranca.log.info(f"[tempo] reconhecimento de voz {time.perf_counter() - t0:.1f}s")
            return texto
        except sr.UnknownValueError:
            self.ultimo_erro = None
            return None
        except sr.RequestError as e:
            if not nativo_tentado:
                nativo = self._tentar_nativo(pcm)
                if nativo:
                    return [nativo] if curto else nativo
            self.ultimo_erro = f"Reconhecimento de voz indisponível: {e}"
            seguranca.log.warning(f"Reconhecimento de voz falhou: {e}")
            print("[voz] Falha no reconhecimento (internet?)")
            return None
