"""Logs rotativos: ultron.log e seguranca.log param de crescer sem limite."""
import logging
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seguranca


class RotacaoDeLogsTests(unittest.TestCase):
    def test_handlers_do_app_rotacionam(self):
        seg = [h for h in seguranca._log_seg.handlers
               if isinstance(h, RotatingFileHandler)]
        self.assertEqual(len(seg), 1)
        raiz = [h for h in logging.getLogger().handlers
                if isinstance(h, RotatingFileHandler)]
        self.assertGreaterEqual(len(raiz), 1)
        for handler in seg + raiz:
            self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
            self.assertEqual(handler.backupCount, 3)
            self.assertEqual(handler.encoding, "utf-8")

    def test_roda_ao_passar_de_5mb(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste.log"
            handler = RotatingFileHandler(str(caminho), maxBytes=5 * 1024 * 1024,
                                          backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger = logging.getLogger("teste.rotacao")
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)
            logger.propagate = False
            try:
                linha = "x" * 1023
                for _ in range(6 * 1024):
                    logger.info(linha)
            finally:
                logger.removeHandler(handler)
                handler.close()
            self.assertTrue(caminho.exists())
            self.assertTrue((Path(pasta) / "teste.log.1").exists())
            self.assertLessEqual(caminho.stat().st_size, 5 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
