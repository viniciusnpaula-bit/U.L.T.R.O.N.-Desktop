"""Audio Front-End (AFE) contínuo: WASAPI loopback + AEC + Silero VAD + Wake Word PT-BR + GTCRN."""
from __future__ import annotations

import collections
import json
import math
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
from scipy import signal as _scipy_signal

import afe_dsp
import afe_modelos

SAMPLE_RATE = 16000
BLOCO_AMOSTRAS = 512  # 32 ms a 16 kHz (alinhado ao Silero VAD v5)
PRE_BUFFER_BLOCOS = 48  # ~1,54 s de histórico pré-fala
GRAMATICA_WAKE = json.dumps(
    ["ei ultron", "ei o tron", "ei", "ultron", "para", "[unk]"],
    ensure_ascii=False,
)
_RE_WAKE_LOCAL = re.compile(r"\b(?:ei\s+)?(?:ultron|o\s+tron)\b", re.IGNORECASE)
_RE_PARA_LOCAL = re.compile(r"\bpara\b", re.IGNORECASE)


def _classificar_kws(texto: str) -> str | None:
    limpo = str(texto or "").strip().lower()
    if not limpo:
        return None
    if _RE_WAKE_LOCAL.search(limpo):
        return "wake"
    if _RE_PARA_LOCAL.search(limpo):
        return "para"
    return None


def _carregar_motores_padrao(caminhos: dict[str, str]) -> dict:
    """Carrega Silero VAD, GTCRN Denoiser e Vosk PT-BR em memória RAM."""
    import sherpa_onnx
    import vosk

    vosk.SetLogLevel(-1)

    vad_cfg = sherpa_onnx.VadModelConfig()
    vad_cfg.silero_vad.model = caminhos["silero_vad"]
    vad_cfg.silero_vad.threshold = 0.45
    vad_cfg.silero_vad.min_silence_duration = 0.25
    vad_cfg.silero_vad.min_speech_duration = 0.10
    vad_cfg.sample_rate = SAMPLE_RATE
    vad = sherpa_onnx.VoiceActivityDetector(vad_cfg, buffer_size_in_seconds=30.0)

    den_cfg = sherpa_onnx.OfflineSpeechDenoiserConfig(
        model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
            gtcrn=sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(
                model=caminhos["gtcrn"],
                num_threads=1,
                provider="cpu",
            )
        )
    )
    denoiser = sherpa_onnx.OfflineSpeechDenoiser(den_cfg)

    modelo_vosk = vosk.Model(caminhos["vosk_pt"])
    kws = vosk.KaldiRecognizer(modelo_vosk, SAMPLE_RATE, GRAMATICA_WAKE)
    return {"vad": vad, "denoiser": denoiser, "kws": kws, "vosk_model": modelo_vosk}


class AudioFrontEnd:
    """Esteira contínua de captura e limpeza de voz para o ULTRON no Windows."""

    def __init__(
        self,
        modelos_dir: Path | None = None,
        falando_event: threading.Event | None = None,
        pausado_event: threading.Event | None = None,
        capturando_event: threading.Event | None = None,
        on_barge_in: Callable[[str, bytes | None], None] | None = None,
        carregador_modelos: Callable[[dict[str, str]], dict] | None = None,
        stream_factory: Callable | None = None,
        loopback_factory: Callable | None = None,
        watchdog_timeout_s: float = 2.5,
    ):
        self._modelos_dir = modelos_dir
        self.falando_event = falando_event or threading.Event()
        self.pausado_event = pausado_event or threading.Event()
        self.on_barge_in = on_barge_in
        self._carregador = carregador_modelos or _carregar_motores_padrao
        self._stream_factory = stream_factory
        self._loopback_factory = loopback_factory
        self._watchdog_timeout_s = float(watchdog_timeout_s)

        self._lock_motores = threading.RLock()
        self._vad = None
        self._kws = None
        self._denoiser = None
        self._vosk_model = None

        self._hpf = afe_dsp.FiltroPassaAlta(fs=SAMPLE_RATE, corte_hz=80.0)
        self._aec = afe_dsp.CanceladorEcoPBFDAF(tamanho_bloco=256, particoes=8, passo=0.25)

        self._capturando_ev = capturando_event or threading.Event()
        self._parar_ev = threading.Event()
        self._device_index: int | None = None
        self._device_mudou_ev = threading.Event()

        self._fila_mic: queue.Queue[np.ndarray] = queue.Queue(maxsize=120)
        self._fila_ref: collections.deque[np.ndarray] = collections.deque(maxlen=64)
        self._enunciados: queue.Queue[dict] = queue.Queue(maxsize=16)

        self._pre_buffer: collections.deque[np.ndarray] = collections.deque(maxlen=PRE_BUFFER_BLOCOS)
        self._blocos_fala: list[np.ndarray] = []
        self._em_fala = False
        self._blocos_silencio = 0
        self._wake_no_enunciado = False
        self._blocos_apos_wake = 0
        self._barge_in_wake_ativo = False
        self._silencio_cfg_s = 1.3
        self._max_seg_cfg_s = 15.0
        self._ultimo_barge_in_ts = 0.0
        self._ultimo_barge_in_tipo: str | None = None

        self.nivel_atual: float = 0.0
        self.aec_ativo: bool = False
        self.ultimo_erro: str | None = None
        self._thread_proc: threading.Thread | None = None
        self._thread_loopback: threading.Thread | None = None
        self._stream = None

    @property
    def capturando(self) -> threading.Event:
        return self._capturando_ev

    @property
    def modo_neural_ativo(self) -> bool:
        with self._lock_motores:
            return self._vad is not None and self._kws is not None

    def injetar_motores(self, vad=None, kws=None, denoiser=None, vosk_model=None) -> None:
        """Instala ou promove motores neurais em execução (thread-safe)."""
        with self._lock_motores:
            self._vad = vad
            self._kws = kws
            self._denoiser = denoiser
            self._vosk_model = vosk_model

    def preparar_modelos_em_ram(self, caminho_modelos: Path | None = None) -> bool:
        """Carrega modelos locais na RAM sem abrir nenhum dispositivo de áudio."""
        base = caminho_modelos if caminho_modelos is not None else self._modelos_dir
        estado = afe_modelos.estado_modelos(base)
        if not estado["pronto"]:
            return False
        try:
            motores = self._carregador(estado["caminhos"])
            self.injetar_motores(
                vad=motores.get("vad"),
                kws=motores.get("kws"),
                denoiser=motores.get("denoiser"),
                vosk_model=motores.get("vosk_model"),
            )
            return True
        except Exception as erro:
            self.ultimo_erro = f"{type(erro).__name__}: {erro}"[:180]
            return False

    def iniciar_provisionamento(self, ao_promover: Callable[[bool], None] | None = None) -> None:
        """Garante modelos em segundo plano e promove para modo neural quando prontos."""
        if self.modo_neural_ativo:
            if ao_promover:
                ao_promover(True)
            return
        if self.preparar_modelos_em_ram():
            if ao_promover:
                ao_promover(True)
            return

        def _quando_baixar(estado: dict) -> None:
            ok = False
            if estado.get("pronto"):
                ok = self.preparar_modelos_em_ram()
            if ao_promover:
                try:
                    ao_promover(ok)
                except Exception:
                    pass

        afe_modelos.garantir_modelos_em_segundo_plano(
            base_dir=self._modelos_dir,
            ao_concluir=_quando_baixar,
        )

    def set_device(self, device_index: int | None) -> None:
        if device_index != self._device_index:
            self._device_index = device_index
            self._device_mudou_ev.set()

    def tem_enunciado_pronto(self) -> bool:
        return not self._enunciados.empty()

    def limpar_enunciados(self) -> None:
        while True:
            try:
                self._enunciados.get_nowait()
            except queue.Empty:
                break

    def _abrir_stream_mic(self):
        def _cb(indata, frames, time_info, status):
            if self._parar_ev.is_set() or self.pausado_event.is_set():
                return
            arr = np.asarray(indata, dtype=np.float32)
            if arr.ndim == 2:
                arr = arr[:, 0]
            else:
                arr = arr.reshape(-1)
            for ini in range(0, len(arr), BLOCO_AMOSTRAS):
                fatia = arr[ini:ini + BLOCO_AMOSTRAS]
                if fatia.size < BLOCO_AMOSTRAS:
                    fatia = np.pad(fatia, (0, BLOCO_AMOSTRAS - fatia.size))
                try:
                    self._fila_mic.put_nowait(fatia.copy())
                except queue.Full:
                    try:
                        self._fila_mic.get_nowait()
                        self._fila_mic.put_nowait(fatia.copy())
                    except queue.Empty:
                        pass

        if self._stream_factory is not None:
            stream = self._stream_factory(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=BLOCO_AMOSTRAS,
                device=self._device_index,
                callback=_cb,
            )
            stream.start()
            return stream

        import sounddevice as sd
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=BLOCO_AMOSTRAS,
            device=self._device_index,
            callback=_cb,
        )
        stream.start()
        return stream

    def _fechar_stream_mic(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self._capturando_ev.clear()

    def _loop_wasapi_loopback(self) -> None:
        if self._loopback_factory is not None:
            return
        pa = None
        stream = None
        try:
            import pyaudiowpatch as pyaudio
            pa = pyaudio.PyAudio()
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            if not default_speakers.get("isLoopbackDevice"):
                loopback = None
                for dev in pa.get_loopback_device_info_generator():
                    if default_speakers["name"] in dev["name"]:
                        loopback = dev
                        break
                if loopback is None:
                    return
                default_speakers = loopback

            taxa_orig = int(default_speakers["defaultSampleRate"])
            canais = max(1, int(default_speakers["maxInputChannels"]))
            chunk_orig = max(256, int(taxa_orig * BLOCO_AMOSTRAS / SAMPLE_RATE))

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=canais,
                rate=taxa_orig,
                frames_per_buffer=chunk_orig,
                input=True,
                input_device_index=default_speakers["index"],
            )
            self.aec_ativo = True
            gcd = math.gcd(SAMPLE_RATE, taxa_orig)
            up, down = SAMPLE_RATE // gcd, taxa_orig // gcd

            while not self._parar_ev.is_set():
                if self.pausado_event.is_set():
                    time.sleep(0.05)
                    continue
                bruto = stream.read(chunk_orig, exception_on_overflow=False)
                pcm = np.frombuffer(bruto, dtype=np.int16).astype(np.float32) / 32768.0
                if canais > 1:
                    pcm = pcm.reshape(-1, canais).mean(axis=1)
                if taxa_orig != SAMPLE_RATE:
                    pcm = _scipy_signal.resample_poly(pcm, up, down).astype(np.float32)
                if pcm.size >= BLOCO_AMOSTRAS:
                    self._fila_ref.append(pcm[:BLOCO_AMOSTRAS])
        except Exception:
            self.aec_ativo = False
        finally:
            self.aec_ativo = False
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if pa is not None:
                try:
                    pa.terminate()
                except Exception:
                    pass

    def _eh_fala_bloco(self, bloco_f32: np.ndarray) -> bool:
        with self._lock_motores:
            vad = self._vad
        if vad is not None:
            try:
                vad.accept_waveform(bloco_f32.tolist() if hasattr(vad, "_is_list") else bloco_f32)
                return bool(vad.is_speech_detected())
            except TypeError:
                vad.accept_waveform(bloco_f32.tolist())
                return bool(vad.is_speech_detected())
            except Exception:
                pass
        # Fallback espectral simples (sem depender de limiar travado).
        janela = np.hanning(bloco_f32.size)
        espectro = np.abs(np.fft.rfft(bloco_f32 * janela))
        freqs = np.fft.rfftfreq(bloco_f32.size, d=1.0 / SAMPLE_RATE)
        mask = (freqs >= 300.0) & (freqs <= 3400.0)
        total = float(espectro.sum()) or 1.0
        energia_banda = float(espectro[mask].sum() / total) if mask.any() else 0.0
        rms = float(np.sqrt(np.mean(bloco_f32 ** 2)))
        return energia_banda > 0.25 and rms > 0.004

    def _detectar_kws(self, bloco_f32: np.ndarray) -> str | None:
        with self._lock_motores:
            kws = self._kws
        if kws is None:
            return None
        pcm_bytes = (np.clip(bloco_f32, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        try:
            finalizou = bool(kws.AcceptWaveform(pcm_bytes))
            if finalizou:
                texto = json.loads(kws.Result()).get("text", "")
            else:
                texto = json.loads(kws.PartialResult()).get("partial", "")
            hit = _classificar_kws(texto)
            if hit and hasattr(kws, "Reset"):
                kws.Reset()
            return hit
        except Exception:
            return None

    def _finalizar_enunciado(self, wake_detectado: bool, comando_direto: bool) -> None:
        if not self._blocos_fala:
            return
        bruto = np.concatenate(self._blocos_fala).astype(np.float32)
        self._blocos_fala.clear()
        self._em_fala = False
        self._blocos_silencio = 0
        self._wake_no_enunciado = False
        self._blocos_apos_wake = 0

        limpo = bruto
        with self._lock_motores:
            denoiser = self._denoiser
        if denoiser is not None:
            try:
                res = denoiser.run(limpo, SAMPLE_RATE)
                if hasattr(res, "samples"):
                    limpo = np.asarray(res.samples, dtype=np.float32)
            except Exception:
                limpo = bruto

        limpo = afe_dsp.aplicar_agc_suave(limpo)
        pcm_bytes = (np.clip(limpo, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        item = {
            "pcm": pcm_bytes,
            "wake_detectado": bool(wake_detectado),
            "comando_direto": bool(comando_direto),
            "erro": None,
        }
        try:
            self._enunciados.put_nowait(item)
        except queue.Full:
            try:
                self._enunciados.get_nowait()
                self._enunciados.put_nowait(item)
            except queue.Empty:
                pass

    def processar_bloco_sintetico(
        self,
        mic_f32: np.ndarray,
        ref_f32: np.ndarray | None,
        falando: bool = False,
        silencio_fim_override: float | None = None,
    ) -> None:
        """Processa um bloco de 512 amostras pelo pipeline completo (usado em runtime e testes)."""
        if silencio_fim_override is not None:
            self._silencio_cfg_s = float(silencio_fim_override)
        bloco = np.asarray(mic_f32, dtype=np.float32).reshape(-1)
        if ref_f32 is not None:
            bloco = self._aec.processar(bloco, ref_f32)
        bloco = self._hpf.processar(bloco)

        rms = float(np.sqrt(np.mean(bloco ** 2)))
        self.nivel_atual = rms * 32767.0
        self._pre_buffer.append(bloco)

        fala = self._eh_fala_bloco(bloco)
        kws_hit = self._detectar_kws(bloco) if (fala or self._em_fala) else None

        if falando:
            if kws_hit in ("para", "wake"):
                agora = time.monotonic()
                duplicado = (kws_hit == self._ultimo_barge_in_tipo) and (agora - self._ultimo_barge_in_ts < 0.4)
                if not duplicado:
                    self._ultimo_barge_in_ts = agora
                    self._ultimo_barge_in_tipo = kws_hit
                    if self.on_barge_in is not None:
                        self.on_barge_in(kws_hit, None)
                    if kws_hit == "wake":
                        self._barge_in_wake_ativo = True
                        self._em_fala = True
                        self._wake_no_enunciado = True
                        self._blocos_apos_wake = 0
                        self._blocos_silencio = 0
                        self._blocos_fala = list(self._pre_buffer)
                    else:
                        self._barge_in_wake_ativo = False
                        self._blocos_fala.clear()
                        self._em_fala = False
            elif self._barge_in_wake_ativo:
                self._blocos_fala.append(bloco)
                if fala:
                    self._blocos_silencio = 0
                    self._blocos_apos_wake += 1
                else:
                    self._blocos_silencio += 1
            return

        self._barge_in_wake_ativo = False
        # Em repouso, "para" não acorda o assistente.
        wake_agora = kws_hit == "wake"

        blocos_silencio_fim = max(2, int(round((self._silencio_cfg_s * SAMPLE_RATE) / BLOCO_AMOSTRAS)))
        max_blocos = max(10, int(round((self._max_seg_cfg_s * SAMPLE_RATE) / BLOCO_AMOSTRAS)))

        if fala or wake_agora:
            if not self._em_fala:
                self._em_fala = True
                self._blocos_fala = list(self._pre_buffer)
                self._blocos_silencio = 0
                self._wake_no_enunciado = wake_agora
                self._blocos_apos_wake = 0
            else:
                self._blocos_fala.append(bloco)
                self._blocos_silencio = 0
                if wake_agora:
                    self._wake_no_enunciado = True
                elif self._wake_no_enunciado:
                    self._blocos_apos_wake += 1
        elif self._em_fala:
            self._blocos_fala.append(bloco)
            self._blocos_silencio += 1
            if self._blocos_silencio >= blocos_silencio_fim:
                comando_direto = bool(self._wake_no_enunciado and self._blocos_apos_wake >= 2)
                self._finalizar_enunciado(self._wake_no_enunciado, comando_direto)
                return

        if self._em_fala and len(self._blocos_fala) >= max_blocos:
            comando_direto = bool(self._wake_no_enunciado and self._blocos_apos_wake >= 2)
            self._finalizar_enunciado(self._wake_no_enunciado, comando_direto)

    def _loop_processamento(self) -> None:
        falhas_seq = 0
        while not self._parar_ev.is_set():
            if self.pausado_event.is_set():
                if self._stream is not None:
                    self._fechar_stream_mic()
                time.sleep(0.05)
                continue

            if self._device_mudou_ev.is_set() or self._stream is None:
                self._device_mudou_ev.clear()
                self._fechar_stream_mic()
                try:
                    self._stream = self._abrir_stream_mic()
                    self._capturando_ev.set()
                    self.ultimo_erro = None
                    falhas_seq = 0
                except Exception as erro:
                    falhas_seq += 1
                    self.ultimo_erro = str(erro)[:180]
                    self._capturando_ev.clear()
                    time.sleep(min(0.3 * falhas_seq, 2.0))
                    continue

            try:
                bloco = self._fila_mic.get(timeout=self._watchdog_timeout_s)
            except queue.Empty:
                # Watchdog USB: reabre stream limpo sem derrubar o consumidor.
                self._fechar_stream_mic()
                self._device_mudou_ev.set()
                continue

            ref = self._fila_ref.popleft() if self._fila_ref else None
            self.processar_bloco_sintetico(
                bloco,
                ref,
                falando=self.falando_event.is_set(),
            )

    def iniciar_captura(
        self,
        device_index: int | None = None,
        on_barge_in: Callable[[str, bytes | None], None] | None = None,
    ) -> None:
        if device_index is not None:
            self._device_index = device_index
        if on_barge_in is not None:
            self.on_barge_in = on_barge_in
        if self._thread_proc is not None and self._thread_proc.is_alive():
            return
        self._parar_ev.clear()
        self._thread_proc = threading.Thread(
            target=self._loop_processamento,
            name="ultron-afe-captura",
            daemon=True,
        )
        self._thread_proc.start()
        if self._loopback_factory is None:
            self._thread_loopback = threading.Thread(
                target=self._loop_wasapi_loopback,
                name="ultron-afe-loopback",
                daemon=True,
            )
            self._thread_loopback.start()

    def parar_captura(self) -> None:
        self._parar_ev.set()
        self._fechar_stream_mic()
        if self._thread_proc is not None and self._thread_proc is not threading.current_thread():
            self._thread_proc.join(timeout=2.0)
        self._thread_proc = None
        if self._thread_loopback is not None and self._thread_loopback is not threading.current_thread():
            self._thread_loopback.join(timeout=2.0)
        self._thread_loopback = None

    def aguardar_enunciado(
        self,
        espera: float = 60.0,
        silencio_fim: float = 1.3,
        max_seg: float = 15.0,
        exigir_wake: bool = True,
        curto: bool = False,
    ) -> dict:
        self._silencio_cfg_s = 0.65 if curto else float(silencio_fim)
        self._max_seg_cfg_s = 5.0 if curto else float(max_seg)
        prazo = time.monotonic() + float(espera)

        while not self._parar_ev.is_set():
            if self.pausado_event.is_set():
                return {"pcm": None, "wake_detectado": False, "comando_direto": False, "erro": None}
            restante = prazo - time.monotonic()
            if restante <= 0:
                return {"pcm": None, "wake_detectado": False, "comando_direto": False, "erro": self.ultimo_erro}
            try:
                item = self._enunciados.get(timeout=min(0.25, restante))
            except queue.Empty:
                continue
            if exigir_wake and self.modo_neural_ativo and not item.get("wake_detectado"):
                continue
            return item

        return {"pcm": None, "wake_detectado": False, "comando_direto": False, "erro": None}
