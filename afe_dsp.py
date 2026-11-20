"""Blocos DSP em tempo real para o Audio Front-End: passa-alta, AEC PBFDAF e AGC."""
from __future__ import annotations

import numpy as np
from scipy import signal


class FiltroPassaAlta:
    """Filtro passa-alta Butterworth de 2ª ordem com estado contínuo entre blocos."""

    def __init__(self, fs: int = 16000, corte_hz: float = 80.0):
        self.fs = int(fs)
        self.corte_hz = float(corte_hz)
        self._sos = signal.butter(2, self.corte_hz, btype="highpass", fs=self.fs, output="sos")
        self._zi = np.zeros((self._sos.shape[0], 2), dtype=np.float64)

    def reset(self) -> None:
        self._zi.fill(0.0)

    def processar(self, bloco: np.ndarray) -> np.ndarray:
        entrada = np.asarray(bloco, dtype=np.float32).reshape(-1)
        if entrada.size == 0:
            return entrada
        saida, self._zi = signal.sosfilt(self._sos, entrada.astype(np.float64), zi=self._zi)
        return saida.astype(np.float32)


class CanceladorEcoPBFDAF:
    """Cancelador de eco acústico em blocos particionados no domínio da frequência (PBFDAF).

    Opera em blocos de `tamanho_bloco` amostras (FFT de `2 * tamanho_bloco` via overlap-save),
    com suavização espectral de potência e trava simples de double-talk.
    """

    def __init__(
        self,
        tamanho_bloco: int = 256,
        particoes: int = 8,
        passo: float = 0.25,
        regularizacao: float = 1e-4,
    ):
        self.B = int(tamanho_bloco)
        self.P = int(particoes)
        self.N = 2 * self.B
        self.n_bins = self.N // 2 + 1
        self.passo = float(passo)
        self.reg = float(regularizacao)
        self.reset()

    def reset(self) -> None:
        self._ref_anterior = np.zeros(self.B, dtype=np.float32)
        self._X_hist = np.zeros((self.P, self.n_bins), dtype=np.complex64)
        self._W = np.zeros((self.P, self.n_bins), dtype=np.complex64)
        self._potencia = np.full(self.n_bins, self.reg, dtype=np.float32)
        self._energia_ref_suave = 0.0
        self._energia_mic_suave = 0.0

    def processar(self, mic: np.ndarray, ref: np.ndarray) -> np.ndarray:
        mic_f = np.asarray(mic, dtype=np.float32).reshape(-1)
        ref_f = np.asarray(ref, dtype=np.float32).reshape(-1)
        if mic_f.size == 0:
            return mic_f
        if ref_f.size < mic_f.size:
            ref_f = np.pad(ref_f, (0, mic_f.size - ref_f.size))
        elif ref_f.size > mic_f.size:
            ref_f = ref_f[: mic_f.size]

        # Se não houver referência ativa, devolve o sinal do microfone direto.
        energia_ref_bloco = float(np.mean(ref_f ** 2))
        self._energia_ref_suave = 0.9 * self._energia_ref_suave + 0.1 * energia_ref_bloco
        self._energia_mic_suave = 0.9 * self._energia_mic_suave + 0.1 * float(np.mean(mic_f ** 2))
        if self._energia_ref_suave < 1e-9 and energia_ref_bloco < 1e-9:
            return mic_f

        if mic_f.size == self.B:
            return self._processar_bloco(mic_f, ref_f)

        # Processa em fatias múltiplas de B (padding temporário se o último pedaço for menor).
        saida = np.empty_like(mic_f)
        for ini in range(0, mic_f.size, self.B):
            fim = min(ini + self.B, mic_f.size)
            n_real = fim - ini
            if n_real == self.B:
                saida[ini:fim] = self._processar_bloco(mic_f[ini:fim], ref_f[ini:fim])
            else:
                m_pad = np.pad(mic_f[ini:fim], (0, self.B - n_real))
                r_pad = np.pad(ref_f[ini:fim], (0, self.B - n_real))
                saida[ini:fim] = self._processar_bloco(m_pad, r_pad)[:n_real]
        return saida

    def _processar_bloco(self, mic_b: np.ndarray, ref_b: np.ndarray) -> np.ndarray:
        janela_ref = np.concatenate([self._ref_anterior, ref_b])
        self._ref_anterior = ref_b.copy()

        X_novo = np.fft.rfft(janela_ref).astype(np.complex64)
        self._X_hist[1:] = self._X_hist[:-1]
        self._X_hist[0] = X_novo

        Y_spec = np.sum(self._W * self._X_hist, axis=0)
        y_tempo = np.fft.irfft(Y_spec, n=self.N)[self.B:].astype(np.float32)

        erro = mic_b - y_tempo
        e_fft_in = np.concatenate([np.zeros(self.B, dtype=np.float32), erro])
        E_spec = np.fft.rfft(e_fft_in).astype(np.complex64)

        # Atualiza potência espectral da referência por bin.
        pot_inst = np.mean(np.abs(self._X_hist) ** 2, axis=0)
        self._potencia = 0.85 * self._potencia + 0.15 * pot_inst

        # Proteção simples de double-talk: reduz muito o passo quando o erro residual
        # supera claramente o eco estimado e a referência está estável.
        rms_erro = float(np.sqrt(np.mean(erro ** 2)))
        rms_y = float(np.sqrt(np.mean(y_tempo ** 2)))
        double_talk = rms_y > 1e-4 and rms_erro > 1.8 * max(rms_y, float(np.sqrt(self._energia_ref_suave)) * 0.25)
        passo_efetivo = self.passo * (0.05 if double_talk else 1.0)

        norma = passo_efetivo / (self._potencia * self.P + self.reg)
        grad_spec = np.conj(self._X_hist) * (E_spec * norma)[None, :]

        # Projeção causal (gradient constraint: zera a segunda metade no tempo).
        grad_tempo = np.fft.irfft(grad_spec, n=self.N, axis=1)
        grad_tempo[:, self.B:] = 0.0
        self._W += np.fft.rfft(grad_tempo, n=self.N, axis=1).astype(np.complex64)

        return np.clip(erro, -1.0, 1.0).astype(np.float32)


def aplicar_agc_suave(
    audio_f32: np.ndarray,
    alvo_rms: float = 0.12,
    ganho_max: float = 12.0,
    piso_silencio: float = 0.002,
    pico_max: float = 0.92,
) -> np.ndarray:
    """Normaliza enunciados de voz distantes sem amplificar silêncio nem gerar clipping."""
    amostras = np.asarray(audio_f32, dtype=np.float32).reshape(-1)
    if amostras.size == 0:
        return amostras
    rms = float(np.sqrt(np.mean(amostras ** 2)))
    if rms < piso_silencio:
        return amostras.copy()
    pico = float(np.max(np.abs(amostras))) or 1e-6
    ganho = min(float(alvo_rms) / rms, float(pico_max) / pico, float(ganho_max))
    if ganho <= 1.0:
        return amostras.copy()
    return np.clip(amostras * ganho, -1.0, 1.0).astype(np.float32)
