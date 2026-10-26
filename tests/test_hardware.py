import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hardware


class HardwareTests(unittest.TestCase):
    def setUp(self):
        hardware._CACHE.update(ts=0.0, texto="")

    def test_relatorio_traz_cpu_gpu_e_discos(self):
        cpu = {"Name": "AMD Ryzen 7 5800X", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16}
        gpus = [{"Name": "NVIDIA GeForce RTX 3060", "DriverVersion": "31.0.15"}]
        with patch.object(hardware, "_cpu_e_gpu", return_value=(cpu, gpus)), \
             patch.object(hardware, "_nvidia", return_value=""), \
             patch.object(hardware, "_discos", return_value=["C: (NTFS): 100.0 GB no total, 40.0 GB livres"]):
            texto = hardware.descrever(forcar=True)
        self.assertIn("AMD Ryzen 7 5800X", texto)
        self.assertIn("NVIDIA GeForce RTX 3060", texto)
        self.assertIn("Disco: C:", texto)
        self.assertIn("Memória:", texto)

    def test_sem_wmi_nao_inventa_gpu(self):
        with patch.object(hardware, "_cpu_e_gpu", return_value=(None, None)), \
             patch.object(hardware, "_nvidia", return_value=""), \
             patch.object(hardware, "_discos", return_value=[]):
            texto = hardware.descrever(forcar=True)
        self.assertIn("não consegui identificar", texto)
        self.assertIn("não consegui listar", texto)

    def test_cache_evita_repetir_o_wmi(self):
        with patch.object(hardware, "_cpu_e_gpu", return_value=(None, None)) as chamada, \
             patch.object(hardware, "_nvidia", return_value=""), \
             patch.object(hardware, "_discos", return_value=[]):
            hardware.descrever(forcar=True)
            hardware.descrever()
        self.assertEqual(chamada.call_count, 1)


if __name__ == "__main__":
    unittest.main()
