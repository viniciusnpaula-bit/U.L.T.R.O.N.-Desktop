import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cofre
import config
import mobile_pairing
import seguranca


class MobilePairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raiz = Path(self.temp.name)
        self.pairing_file = raiz / "mobile_pairing.json"
        self.key_file = raiz / ".cofre.chave"
        p1 = patch.object(config, "ARQUIVO_MOBILE_PAIRING", self.pairing_file)
        p2 = patch.object(cofre, "ARQUIVO_CHAVE", self.key_file)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.addCleanup(lambda: setattr(seguranca, "SEGREDOS_MOBILE", ()))

    def test_gerar_segredo_alta_entropia_e_sem_repeticao(self):
        s1 = mobile_pairing.gerar_segredo()
        s2 = mobile_pairing.gerar_segredo()
        self.assertGreaterEqual(len(s1), 32)
        self.assertNotEqual(s1, s2)
        self.assertEqual(mobile_pairing.validar_segredo(s1), s1)

    def test_rejeita_segredos_proibidos_ou_fracos(self):
        for invalido in ("ULTRON_LAN_GUARD", "ultron_lan_guard", "changeme", "secret", "password", "curto", "a b c" * 6):
            with self.assertRaises(ValueError):
                mobile_pairing.validar_segredo(invalido)

    def test_rejeita_device_id_invalido_ou_traversal(self):
        self.assertEqual(mobile_pairing.validar_device_id("galaxy-a34"), "galaxy-a34")
        for invalido in ("", " ", "../evil", "a/b", "a\\b", "com espaco"):
            with self.assertRaises(ValueError):
                mobile_pairing.validar_device_id(invalido)

    def test_persistencia_cifrada_e_sem_segredo_em_texto_claro(self):
        criado = mobile_pairing.criar_ou_rotacionar(device_id="galaxy-a34")
        segredo = criado["shared_secret"]
        self.assertEqual(criado["device_id"], "galaxy-a34")
        self.assertEqual(criado["killswitch_secret"], segredo)
        self.assertFalse(criado["killswitch_separado"])

        texto_disco = self.pairing_file.read_text(encoding="utf-8")
        self.assertNotIn(segredo, texto_disco)
        bruto = json.loads(texto_disco)
        self.assertTrue(bruto["devices"]["galaxy-a34"]["secret_enc"].startswith("v1:"))

        self.assertEqual(mobile_pairing.obter_segredo_dispositivo("galaxy-a34"), segredo)
        self.assertEqual(mobile_pairing.obter_segredos_killswitch(), [("galaxy-a34", segredo)])
        self.assertTrue(mobile_pairing.tem_pareamento_ativo())

    def test_segredo_killswitch_dedicado(self):
        criado = mobile_pairing.criar_ou_rotacionar(
            device_id="pixel-9",
            killswitch_separado=True,
        )
        self.assertTrue(criado["killswitch_separado"])
        self.assertNotEqual(criado["shared_secret"], criado["killswitch_secret"])
        texto_disco = self.pairing_file.read_text(encoding="utf-8")
        self.assertNotIn(criado["shared_secret"], texto_disco)
        self.assertNotIn(criado["killswitch_secret"], texto_disco)

        candidatos = mobile_pairing.obter_segredos_killswitch()
        self.assertIn(("killswitch", criado["killswitch_secret"]), candidatos)
        self.assertIn(("pixel-9", criado["shared_secret"]), candidatos)

    def test_status_publico_nunca_expoe_segredos(self):
        criado = mobile_pairing.criar_ou_rotacionar(device_id="galaxy-a34", killswitch_separado=True)
        st = mobile_pairing.status_publico()
        serializado = json.dumps(st)
        self.assertTrue(st["configured"])
        self.assertTrue(st["killswitch_dedicated"])
        self.assertNotIn(criado["shared_secret"], serializado)
        self.assertNotIn(criado["killswitch_secret"], serializado)
        self.assertEqual(st["devices"][0]["device_id"], "galaxy-a34")

    def test_revogar_dispositivo_e_revogar_tudo(self):
        mobile_pairing.criar_ou_rotacionar(device_id="dev-1")
        mobile_pairing.criar_ou_rotacionar(device_id="dev-2")
        res1 = mobile_pairing.revogar("dev-1")
        self.assertEqual(res1["removed_count"], 1)
        self.assertTrue(res1["configured"])
        self.assertEqual(mobile_pairing.obter_segredo_dispositivo("dev-1"), "")
        self.assertNotEqual(mobile_pairing.obter_segredo_dispositivo("dev-2"), "")

        res_all = mobile_pairing.revogar()
        self.assertFalse(res_all["configured"])
        self.assertFalse(mobile_pairing.tem_pareamento_ativo())
        self.assertEqual(mobile_pairing.obter_segredos_killswitch(), [])

    def test_redacao_de_segredos_nos_logs(self):
        criado = mobile_pairing.criar_ou_rotacionar(device_id="galaxy-a34", killswitch_separado=True)
        texto = f"falha com {criado['shared_secret']} e {criado['killswitch_secret']}"
        redigido = seguranca.redigir(texto)
        self.assertNotIn(criado["shared_secret"], redigido)
        self.assertNotIn(criado["killswitch_secret"], redigido)
        self.assertIn("***", redigido)

    def test_fail_closed_sem_chave_do_cofre(self):
        self.assertFalse(mobile_pairing.tem_pareamento_ativo())
        self.assertFalse(self.key_file.exists())
        self.assertEqual(mobile_pairing.obter_segredo_dispositivo("galaxy-a34"), "")
        # Ler nunca cria .cofre.chave
        self.assertFalse(self.key_file.exists())

    def test_qr_code_linkavel_decodifica_uri_exata_com_hmac(self):
        import base64
        import cv2
        import numpy as np
        import mobile_qr
        from urllib.parse import parse_qs, urlsplit

        criado = mobile_pairing.criar_ou_rotacionar(device_id="galaxy-a34")
        uri = criado["pairing_uri"]
        qr_uri = criado["qr_data_uri"]
        self.assertTrue(uri.startswith("ultron://pair?"))
        self.assertTrue(qr_uri.startswith("data:image/svg+xml;base64,"))

        parsed = urlsplit(uri)
        params = parse_qs(parsed.query)
        self.assertEqual(params["url"][0], criado["lan_url"])
        self.assertEqual(params["device"][0], "galaxy-a34")
        self.assertEqual(params["secret"][0], criado["shared_secret"])
        self.assertEqual(params["ks"][0], "same")

        svg_text = base64.b64decode(qr_uri.split(",", 1)[1]).decode("utf-8")
        self.assertIn("<svg", svg_text)

        mat = mobile_qr.encode_matrix(uri)
        n = len(mat)
        scale, quiet = 8, 4
        img = np.full(((n + 2 * quiet) * scale, (n + 2 * quiet) * scale), 255, dtype=np.uint8)
        for r in range(n):
            for c in range(n):
                if mat[r][c]:
                    img[(r + quiet) * scale:(r + quiet + 1) * scale, (c + quiet) * scale:(c + quiet + 1) * scale] = 0
        decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        self.assertEqual(decoded, uri)
