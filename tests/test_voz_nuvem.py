"""Voz clonada na nuvem: usa o Fish quando configurado e sempre cai no Edge se falhar."""
import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import voz


class _Communicate:
    """Edge TTS falso: grava um marcador para provar qual motor falou."""

    def __init__(self, texto, voz, **kwargs):
        pass

    async def save(self, arquivo):
        Path(arquivo).write_bytes(b"edge")


def _edge_falso():
    return patch.dict(sys.modules, {"edge_tts": types.SimpleNamespace(Communicate=_Communicate)})


class VozNuvemTests(unittest.TestCase):
    def test_com_chave_e_id_fala_pela_nuvem(self):
        def nuvem(texto, arquivo):
            Path(arquivo).write_bytes(b"nuvem")

        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / "a.mp3"
            with patch.object(config, "VOZ_NUVEM_CHAVE", "chave"), \
                 patch.object(config, "VOZ_NUVEM_ID", "voz-1"), \
                 patch.object(voz, "_sintetizar_nuvem", nuvem), _edge_falso():
                asyncio.run(voz._sintetizar("olá", alvo))
            self.assertEqual(alvo.read_bytes(), b"nuvem")

    def test_sem_credenciais_usa_edge(self):
        def nuvem(*_a, **_k):
            raise AssertionError("não deveria chamar a nuvem sem credenciais")

        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / "a.mp3"
            with patch.object(config, "VOZ_NUVEM_CHAVE", ""), \
                 patch.object(config, "VOZ_NUVEM_ID", ""), \
                 patch.object(voz, "_sintetizar_nuvem", nuvem), _edge_falso():
                asyncio.run(voz._sintetizar("olá", alvo))
            self.assertEqual(alvo.read_bytes(), b"edge")

    def test_falha_da_nuvem_cai_no_edge(self):
        def nuvem(*_a, **_k):
            raise RuntimeError("sem rede")

        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / "a.mp3"
            with patch.object(config, "VOZ_NUVEM_CHAVE", "chave"), \
                 patch.object(config, "VOZ_NUVEM_ID", "voz-1"), \
                 patch.object(voz, "_sintetizar_nuvem", nuvem), _edge_falso():
                asyncio.run(voz._sintetizar("olá", alvo))
            self.assertEqual(alvo.read_bytes(), b"edge")

    def test_resposta_vazia_cai_no_edge(self):
        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / "a.mp3"
            with patch.object(config, "VOZ_NUVEM_CHAVE", "chave"), \
                 patch.object(config, "VOZ_NUVEM_ID", "voz-1"), \
                 patch("requests.post") as post, _edge_falso():
                post.return_value.content = b""
                asyncio.run(voz._sintetizar("olá", alvo))
            self.assertEqual(alvo.read_bytes(), b"edge")

    def test_requisicao_leva_modelo_e_voz(self):
        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / "a.mp3"
            with patch.object(config, "VOZ_NUVEM_CHAVE", "chave"), \
                 patch.object(config, "VOZ_NUVEM_ID", "voz-1"), \
                 patch.object(config, "VOZ_NUVEM_MODELO", "s2.1-pro-free"), \
                 patch("requests.post") as post:
                post.return_value.content = b"mp3"
                voz._sintetizar_nuvem("olá", alvo)

            self.assertEqual(post.call_args.args[0], voz._URL_VOZ_NUVEM)
            headers = post.call_args.kwargs["headers"]
            self.assertEqual(headers["Authorization"], "Bearer chave")
            self.assertEqual(headers["model"], "s2.1-pro-free")
            self.assertEqual(post.call_args.kwargs["json"],
                             {"text": "olá", "reference_id": "voz-1", "format": "mp3"})
            self.assertEqual(alvo.read_bytes(), b"mp3")


if __name__ == "__main__":
    unittest.main()
