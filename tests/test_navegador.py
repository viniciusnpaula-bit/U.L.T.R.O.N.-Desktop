import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import navegador


class UrlTests(unittest.TestCase):
    def test_aceita_http_e_completa_https(self):
        with patch.object(navegador, "_resolver_publico", return_value=True):
            self.assertEqual(navegador.validar_url("https://example.com/a"), "https://example.com/a")
            self.assertEqual(navegador.validar_url("example.com"), "https://example.com")

    def test_recusa_esquemas_perigosos(self):
        for url in ("file:///C:/Windows/win.ini", "javascript:alert(1)", "data:text/html,oi", "ftp://example.com"):
            with self.assertRaises(navegador.NavegadorErro):
                navegador.validar_url(url)

    def test_recusa_rede_local(self):
        for url in ("http://localhost:8000", "http://127.0.0.1", "http://192.168.0.10",
                    "http://10.0.0.5", "http://[::1]/", "http://pc.local"):
            with self.assertRaises(navegador.NavegadorErro):
                navegador.validar_url(url)

    def test_recusa_usuario_e_senha_na_url(self):
        with patch.object(navegador, "_resolver_publico", return_value=True):
            with self.assertRaises(navegador.NavegadorErro):
                navegador.validar_url("https://user:senha@example.com")

    def test_recusa_quando_o_dns_aponta_para_rede_privada(self):
        with patch.object(navegador, "_resolver_publico", return_value=False):
            with self.assertRaises(navegador.NavegadorErro):
                navegador.validar_url("https://aponta-para-dentro.example")

    def test_vazio_e_endereco_sem_host(self):
        for url in ("", "   ", "https:///caminho"):
            with self.assertRaises(navegador.NavegadorErro):
                navegador.validar_url(url)


class DisponibilidadeTests(unittest.TestCase):
    def test_disponivel_devolve_booleano_sem_importar_o_playwright(self):
        self.assertIsInstance(navegador.disponivel(), bool)


if __name__ == "__main__":
    unittest.main()
