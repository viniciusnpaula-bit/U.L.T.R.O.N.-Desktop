"""Testes do provisionamento e validação de modelos do Audio Front-End (AFE)."""
import hashlib
import io
import sys
import threading
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _zip_em_memoria(arquivos: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nome, conteudo in arquivos.items():
            zf.writestr(nome, conteudo)
    return buf.getvalue()


class AfeModelosTests(unittest.TestCase):
    def test_estado_modelos_faltando_em_pasta_vazia(self):
        import tempfile
        import afe_modelos

        with tempfile.TemporaryDirectory() as tmp:
            estado = afe_modelos.estado_modelos(Path(tmp))
            self.assertFalse(estado["pronto"])
            self.assertEqual(set(estado["faltando"]), {"silero_vad", "gtcrn", "vosk_pt"})

    def test_baixar_e_verificar_modelo_valida_sha256_e_rejeita_corrompido(self):
        import tempfile
        import afe_modelos

        payload = b"conteudo-modelo-onnx-simulado"
        sha_ok = hashlib.sha256(payload).hexdigest()
        spec = {
            "id": "silero_vad",
            "arquivo": "silero_vad.onnx",
            "url": "https://example.com/silero_vad.onnx",
            "sha256": sha_ok,
            "tipo": "arquivo",
        }
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp)
            with self.assertRaises(ValueError):
                afe_modelos.baixar_e_verificar_modelo(
                    spec, destino, fetcher=lambda _url: b"corrompido"
                )
            self.assertFalse((destino / "silero_vad.onnx").exists())
            self.assertFalse((destino / "silero_vad.onnx.tmp").exists())

            saida = afe_modelos.baixar_e_verificar_modelo(
                spec, destino, fetcher=lambda _url: payload
            )
            self.assertTrue(saida.is_file())
            self.assertEqual(saida.read_bytes(), payload)

    def test_baixar_e_verificar_zip_rejeita_path_traversal(self):
        import tempfile
        import afe_modelos

        zip_malicioso = _zip_em_memoria({"../../fora.txt": b"x"})
        spec = {
            "id": "vosk_pt",
            "arquivo": "vosk-model-small-pt-0.3",
            "url": "https://example.com/vosk.zip",
            "sha256": hashlib.sha256(zip_malicioso).hexdigest(),
            "tipo": "zip",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                afe_modelos.baixar_e_verificar_modelo(
                    spec, Path(tmp), fetcher=lambda _url: zip_malicioso
                )

    def test_garantir_modelos_em_segundo_plano_executa_async_e_notifica(self):
        import tempfile
        import afe_modelos

        onnx1 = b"vad-data"
        onnx2 = b"gtcrn-data"
        zip_vosk = _zip_em_memoria({"vosk-model-small-pt-0.3/conf/mfcc.conf": b"ok"})
        specs_fake = {
            "silero_vad": {
                "id": "silero_vad",
                "arquivo": "silero_vad.onnx",
                "url": "https://example.com/silero_vad.onnx",
                "sha256": hashlib.sha256(onnx1).hexdigest(),
                "tipo": "arquivo",
            },
            "gtcrn": {
                "id": "gtcrn",
                "arquivo": "gtcrn_simple.onnx",
                "url": "https://example.com/gtcrn_simple.onnx",
                "sha256": hashlib.sha256(onnx2).hexdigest(),
                "tipo": "arquivo",
            },
            "vosk_pt": {
                "id": "vosk_pt",
                "arquivo": "vosk-model-small-pt-0.3",
                "url": "https://example.com/vosk.zip",
                "sha256": hashlib.sha256(zip_vosk).hexdigest(),
                "tipo": "zip",
            },
        }
        respostas = {
            "https://example.com/silero_vad.onnx": onnx1,
            "https://example.com/gtcrn_simple.onnx": onnx2,
            "https://example.com/vosk.zip": zip_vosk,
        }
        evento = threading.Event()
        concluido = {}

        def on_done(estado):
            concluido.update(estado)
            evento.set()

        with tempfile.TemporaryDirectory() as tmp:
            th = afe_modelos.garantir_modelos_em_segundo_plano(
                base_dir=Path(tmp),
                ao_concluir=on_done,
                especificacoes=specs_fake,
                fetcher=lambda url: respostas[url],
            )
            self.assertIsNotNone(th)
            self.assertTrue(evento.wait(timeout=3.0))
            self.assertTrue(concluido.get("pronto"))
            self.assertEqual(concluido.get("faltando"), [])

    def test_especificacoes_padrao_possuem_sha256_valido(self):
        import re
        import afe_modelos

        for nome, spec in afe_modelos.ESPECIFICACOES_MODELOS.items():
            sha = str(spec.get("sha256") or "")
            self.assertRegex(
                sha,
                r"^[0-9a-f]{64}$",
                f"modelo {nome} precisa de hash SHA-256 de 64 hex chars",
            )


if __name__ == "__main__":
    unittest.main()
