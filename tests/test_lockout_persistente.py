import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import desktop_runtime
from desktop_runtime import DesktopRuntime


class PersistentLockoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "dados" / "sessao.json"
        self.patch = patch.object(desktop_runtime, "ARQUIVO_SESSAO", self.file)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.security = SimpleNamespace(
            pin_configurado=lambda: True,
            pin_valido=lambda pin: pin == "2468",
            log_seg=lambda *args: None,
        )

    def runtime(self):
        runtime = DesktopRuntime(start_voice=False)
        runtime._security = self.security
        return runtime

    def test_five_failures_lock_and_survive_restart(self):
        runtime = self.runtime()
        for _ in range(4):
            self.assertEqual(runtime.unlock_pin("0000")["error"], "pin_invalid")
        self.assertEqual(runtime.unlock_pin("0000")["error"], "too_many_attempts")
        # novo processo: o arquivo mantém a espera
        outro = self.runtime()
        self.assertEqual(outro.unlock_pin("2468")["error"], "too_many_attempts")
        self.assertNotIn("2468", self.file.read_text(encoding="utf-8"))

    def test_expired_wait_allows_attempt_and_success_clears_state(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text(json.dumps({"unlock_falhas": 0, "unlock_espera_ate": 1.0}),
                             encoding="utf-8")
        runtime = self.runtime()
        self.assertTrue(runtime.unlock_pin("2468")["unlocked"])
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")),
                         {"unlock_falhas": 0, "unlock_espera_ate": 0.0})

    def test_corrupted_file_is_ignored(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text("não é json", encoding="utf-8")
        self.assertEqual(self.runtime().unlock_pin("0000")["error"], "pin_invalid")


if __name__ == "__main__":
    unittest.main()
