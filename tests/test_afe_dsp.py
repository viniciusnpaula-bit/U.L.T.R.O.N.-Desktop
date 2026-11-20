"""Testes do pipeline DSP do Audio Front-End: passa-alta, AEC PBFDAF e AGC suave."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AfeDspTests(unittest.TestCase):
    def test_passa_alta_atenua_grave_e_preserva_voz(self):
        import afe_dsp

        fs = 16000
        t = np.arange(fs, dtype=np.float32) / fs
        grave_30hz = 0.5 * np.sin(2 * np.pi * 30.0 * t)
        voz_440hz = 0.25 * np.sin(2 * np.pi * 440.0 * t)

        filtro_a = afe_dsp.FiltroPassaAlta(fs=fs, corte_hz=80.0)
        filtro_b = afe_dsp.FiltroPassaAlta(fs=fs, corte_hz=80.0)

        # Descarta transitório inicial (primeiros 0.2s)
        saida_grave = filtro_a.processar(grave_30hz)[3200:]
        saida_voz = filtro_b.processar(voz_440hz)[3200:]

        rms_in_grave = float(np.sqrt(np.mean(grave_30hz[3200:] ** 2)))
        rms_out_grave = float(np.sqrt(np.mean(saida_grave ** 2)))
        atenuacao_db = 20.0 * np.log10(max(rms_in_grave, 1e-9) / max(rms_out_grave, 1e-9))

        rms_in_voz = float(np.sqrt(np.mean(voz_440hz[3200:] ** 2)))
        rms_out_voz = float(np.sqrt(np.mean(saida_voz ** 2)))

        self.assertGreater(atenuacao_db, 14.0)
        self.assertGreater(rms_out_voz / rms_in_voz, 0.90)

    def test_aec_pbfdaf_atenua_eco_e_preserva_double_talk(self):
        import afe_dsp

        rng = np.random.default_rng(42)
        fs = 16000
        n_amostras = fs * 3  # 3 segundos para convergência adaptativa
        ref = rng.normal(0.0, 0.25, size=n_amostras).astype(np.float32)

        # Caminho acústico simulado da sala: atraso de 120 amostras + reflexão fraca
        eco = np.zeros_like(ref)
        eco[120:] += 0.65 * ref[:-120]
        eco[310:] += 0.20 * ref[:-310]

        # Trecho 1 (0..2s): apenas eco (convergência); Trecho 2 (2..3s): eco + voz do usuário
        t = np.arange(n_amostras, dtype=np.float32) / fs
        voz = np.zeros_like(ref)
        voz[2 * fs:] = 0.22 * np.sin(2 * np.pi * 520.0 * t[2 * fs:])
        mic = (eco + voz).astype(np.float32)

        aec = afe_dsp.CanceladorEcoPBFDAF(tamanho_bloco=256, particoes=8, passo=0.35)
        limpo = np.zeros_like(mic)
        for ini in range(0, n_amostras - 256 + 1, 256):
            limpo[ini:ini + 256] = aec.processar(mic[ini:ini + 256], ref[ini:ini + 256])

        # Mede atenuação do eco puro entre 1.0s e 2.0s
        rms_eco = float(np.sqrt(np.mean(mic[fs:2 * fs] ** 2)))
        rms_res = float(np.sqrt(np.mean(limpo[fs:2 * fs] ** 2)))
        atenuacao_db = 20.0 * np.log10(max(rms_eco, 1e-9) / max(rms_res, 1e-9))
        self.assertGreater(atenuacao_db, 10.0)

        # Mede preservação da voz durante double-talk (2.2s..3.0s)
        seg_limpo = limpo[int(2.2 * fs):3 * fs]
        seg_voz = voz[int(2.2 * fs):3 * fs]
        corr = float(np.corrcoef(seg_limpo, seg_voz)[0, 1])
        self.assertGreater(corr, 0.70)

    def test_agc_suave_amplifica_voz_baixa_sem_clipping_e_poupa_silencio(self):
        import afe_dsp

        t = np.arange(4000, dtype=np.float32) / 16000
        voz_baixa = (0.01 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        saida = afe_dsp.aplicar_agc_suave(voz_baixa, alvo_rms=0.12, ganho_max=12.0)

        rms_saida = float(np.sqrt(np.mean(saida ** 2)))
        self.assertGreater(rms_saida, 0.05)
        self.assertLessEqual(float(np.max(np.abs(saida))), 0.96)

        silencio = np.full(1600, 1e-4, dtype=np.float32)
        saida_sil = afe_dsp.aplicar_agc_suave(silencio, alvo_rms=0.12, ganho_max=12.0)
        np.testing.assert_allclose(saida_sil, silencio, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
