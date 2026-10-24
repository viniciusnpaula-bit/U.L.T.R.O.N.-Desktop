import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import atualizacao


def release_fake(tag="v9.9.9", nome_zip="ULTRON-Desktop-v9.9.9.zip", com_checksums=True, com_assinatura=True):
    assets = [{"name": nome_zip, "size": 1024, "browser_download_url": "https://github.com/x/y/releases/a.zip"}]
    if com_checksums:
        assets.append({"name": "SHA256SUMS.txt", "size": 80,
                       "browser_download_url": "https://github.com/x/y/releases/SHA256SUMS.txt"})
    if com_assinatura:
        assets.append({"name": "SHA256SUMS.txt.sig", "size": 64,
                       "browser_download_url": "https://github.com/x/y/releases/SHA256SUMS.txt.sig"})
    return json.dumps({"tag_name": tag, "body": "novidades", "assets": assets,
                       "html_url": "https://github.com/x/y/releases"}).encode()


def zip_valido(versao="9.9.9"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("electron/package.json", json.dumps({"version": versao}))
        archive.writestr("electron/site/index.html", "<html></html>")
        archive.writestr("cerebro.py", "print('oi')")
        archive.writestr("dados/ultron.db", b"nao pode entrar")
        archive.writestr(".env", "GEMINI_API_KEY=nao pode entrar")
        archive.writestr("notas.exe", b"MZ")
        archive.writestr("ULTRON.exe", b"MZnovo")
    return buffer.getvalue()


def par_de_chaves():
    """Par Ed25519 descartável, gerado no próprio teste."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    chave = Ed25519PrivateKey.generate()
    publica = chave.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    import base64
    return chave, base64.b64encode(publica).decode("ascii")


class UpdateManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "ultron"
        (self.root / "electron").mkdir(parents=True)
        (self.root / "electron" / "package.json").write_text(json.dumps({"version": "1.9.4"}), encoding="utf-8")
        (self.root / "ULTRON.exe").write_bytes(b"MZ")
        os.environ["LOCALAPPDATA"] = str(Path(self.temp.name) / "AppData")
        self.manager = atualizacao.UpdateManager(self.root)

    def tearDown(self):
        os.environ.pop("ULTRON_UPDATE_ALLOW_HTTP", None)
        os.environ.pop("LOCALAPPDATA", None)
        self.temp.cleanup()

    def test_version_compare_only_offers_newer_releases(self):
        self.assertGreater(atualizacao._version_tuple("1.9.10"), atualizacao._version_tuple("1.9.9"))
        self.assertFalse(atualizacao._version_tuple("1.9.4") > atualizacao._version_tuple("1.9.4"))

    def test_check_reports_update_available(self):
        with patch.object(atualizacao, "_request", return_value=release_fake()):
            info = self.manager.check()
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["current_version"], "1.9.4")
        self.assertEqual(info["latest_version"], "9.9.9")
        self.assertTrue(info["update_available"])

    def test_check_without_release_is_not_an_error(self):
        import urllib.error
        erro = urllib.error.HTTPError("u", 404, "not found", {}, None)
        with patch.object(atualizacao, "_request", side_effect=erro):
            info = self.manager.check()
        self.assertEqual(info["status"], "sem_release")

    def test_hosts_outside_github_are_refused(self):
        with self.assertRaises(atualizacao.UpdateError):
            atualizacao._request("https://exemplo-malicioso.com/release.json")
        with self.assertRaises(atualizacao.UpdateError):
            atualizacao._request("http://api.github.com/repos/x/y")   # sem HTTPS
        with self.assertRaises(atualizacao.UpdateError):
            atualizacao._download("https://exemplo-malicioso.com/pacote.zip",
                                  Path(self.temp.name) / "x.zip", atualizacao.ALLOWED_HOSTS)

    def test_url_with_embedded_credentials_is_refused(self):
        with self.assertRaises(atualizacao.UpdateError):
            atualizacao._url_permitida("https://api.github.com@evil.example/x", atualizacao.ALLOWED_HOSTS)
        with self.assertRaises(atualizacao.UpdateError):
            atualizacao._url_permitida("https://evil.example/x", atualizacao.ALLOWED_HOSTS)

    def test_redirect_to_foreign_host_is_refused(self):
        handler = atualizacao._RedirectSeguro(atualizacao.ALLOWED_HOSTS)
        with self.assertRaises(atualizacao.UpdateError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/payload.zip")

    def test_public_key_cannot_be_overridden_by_environment(self):
        import inspect
        self.assertNotIn("ULTRON_UPDATE_PUBKEY", inspect.getsource(atualizacao))
        with patch.dict(os.environ, {"ULTRON_UPDATE_PUBKEY": "AAAA"}):
            self.assertNotEqual(atualizacao.CHAVE_PUBLICA_ATUALIZACAO, "AAAA")

    def test_pre_apply_backup_allows_rollback_and_skips_protected_dirs(self):
        (self.root / "cerebro.py").write_text("antigo", encoding="utf-8")
        staging = Path(self.temp.name) / "staging"
        (staging / ".venv" / "Lib").mkdir(parents=True)
        (staging / ".venv" / "Lib" / "evil.py").write_text("x", encoding="utf-8")
        (staging / "cerebro.py").write_text("novo", encoding="utf-8")

        aplicados, pendentes, backup = self.manager._apply_now(staging)

        self.assertIn("cerebro.py", aplicados)
        self.assertEqual(pendentes, [])
        self.assertEqual((self.root / "cerebro.py").read_text(encoding="utf-8"), "novo")
        self.assertFalse((self.root / ".venv").exists())
        self.assertEqual((backup / "cerebro.py").read_text(encoding="utf-8"), "antigo")

        self.manager._save_state(pending_backup=str(backup))
        self.assertTrue(self.manager.rollback())
        self.assertEqual((self.root / "cerebro.py").read_text(encoding="utf-8"), "antigo")

    def _aplicar(self, conteudo, checksums_top="sha256-ok", assinatura="valida", adulterar_sums=False):
        pacote = zip_valido()
        digest = hashlib.sha256(pacote).hexdigest()
        destino = Path(self.temp.name) / "pacote.zip"
        destino.write_bytes(pacote)

        def download(_url, alvo, _hosts):
            alvo.write_bytes(pacote)
            return len(pacote), digest

        privada, publica = par_de_chaves()
        texto = f"{digest if checksums_top == 'sha256-ok' else '0'*64}  ULTRON-Desktop-v9.9.9.zip\n"
        assinado = texto.encode()
        if adulterar_sums:
            # o SUMS muda depois de assinado (ataque clássico)
            assinado = assinado + b"0000000000000000000000000000000000000000000000000000000000000000  outro.zip\n"
        if assinatura == "valida":
            assinatura_bytes = privada.sign(texto.encode())
        elif assinatura == "invalida":
            assinatura_bytes = par_de_chaves()[0].sign(texto.encode())   # outra chave
        else:
            assinatura_bytes = b""

        def request(url, **_kwargs):
            if "sig" in str(url) or str(url).endswith(".sig"):
                if assinatura == "ausente":
                    raise atualizacao.UpdateError("sem assinatura")
                return assinatura_bytes
            if "releases/latest" in str(url) or str(url).endswith("/releases"):
                return release_fake(com_assinatura=assinatura != "ausente")
            return assinado

        with patch.object(atualizacao, "CHAVE_PUBLICA_ATUALIZACAO", publica), \
             patch.object(atualizacao, "_request", side_effect=request), \
             patch.object(atualizacao, "_download", side_effect=download):
            self.manager.apply()
            for _ in range(100):
                if self.manager._job["status"] in {"pronto", "erro", "atualizado"}:
                    break
                import time
                time.sleep(0.02)
        return self.manager._job

    def test_apply_rejects_wrong_hash(self):
        job = self._aplicar(zip_valido(), checksums_top="sha256-errado")
        self.assertEqual(job["status"], "erro")
        self.assertIn("SHA-256", job["message"])

    def test_apply_applies_what_it_can_and_never_touches_user_data(self):
        job = self._aplicar(zip_valido())
        self.assertEqual(job["status"], "pronto", job.get("message"))
        # código novo já está no disco: sem reinício, a próxima execução usa a versão nova
        self.assertTrue((self.root / "cerebro.py").is_file())
        self.assertEqual((self.root / "cerebro.py").read_text(encoding="utf-8"), "print('oi')")
        # dados do usuário nunca são copiados do pacote
        self.assertFalse((self.root / "dados" / "ultron.db").exists())
        self.assertFalse((self.root / ".env").exists())
        self.assertIn("applied", job)
        if job.get("needs_restart"):
            # quando sobra arquivo em uso, existe o script que termina o serviço
            script = Path(job["script"]).read_text(encoding="utf-8")
            self.assertIn("tasklist", script)
            self.assertIn("start", script)
            for pasta in ("venv", ".venv", "node_modules", "__pycache__", "dados", "logs", ".git", "build"):
                self.assertIn(pasta, script)

    def test_restart_is_only_requested_when_a_file_is_locked(self):
        # ULTRON.exe está em uso (simulado com um erro de permissão): precisa reiniciar
        def copia_bloqueada(origem, destino, *_a, **_k):
            if str(destino).endswith("ULTRON.exe"):
                raise PermissionError("em uso")
            return None
        with patch.object(atualizacao.shutil, "copy2", side_effect=copia_bloqueada):
            job = self._aplicar(zip_valido())
        self.assertEqual(job["status"], "pronto")
        self.assertTrue(job["needs_restart"])
        self.assertTrue(job.get("script"))

    def test_signed_sums_is_required(self):
        job = self._aplicar(zip_valido(), assinatura="ausente")
        self.assertEqual(job["status"], "erro")
        self.assertIn("Assinatura", job["message"])

    def test_wrong_signature_is_refused(self):
        job = self._aplicar(zip_valido(), assinatura="invalida")
        self.assertEqual(job["status"], "erro")
        self.assertIn("Assinatura", job["message"])

    def test_tampered_sums_is_refused(self):
        job = self._aplicar(zip_valido(), adulterar_sums=True)
        self.assertEqual(job["status"], "erro")
        self.assertIn("Assinatura", job["message"])

    def test_app_without_public_key_refuses_everything(self):
        # sem chave embutida não há como provar autenticidade: recusa antes de tudo
        def request(url, **_kwargs):
            if str(url).endswith(".sig"):
                raise atualizacao.UpdateError("sem assinatura")
            if "releases" in str(url):
                return release_fake()
            return b""

        with patch.object(atualizacao, "CHAVE_PUBLICA_ATUALIZACAO", ""), \
             patch.object(atualizacao, "_request", side_effect=request), \
             patch.object(atualizacao, "_download", side_effect=lambda _u, alvo, _h: (alvo.write_bytes(b"x"), (1, "0" * 64))[1]):
            self.manager.apply()
            for _ in range(200):
                if self.manager._job["status"] in {"pronto", "erro", "atualizado"}:
                    break
                import time
                time.sleep(0.02)
        self.assertEqual(self.manager._job["status"], "erro")
        self.assertIn("Assinatura", self.manager._job["message"])

    def test_release_without_checksums_is_refused(self):
        with patch.object(atualizacao, "_request", return_value=release_fake(com_checksums=False)):
            self.manager.apply()
            for _ in range(100):
                if self.manager._job["status"] in {"pronto", "erro", "atualizado"}:
                    break
                import time
                time.sleep(0.02)
        self.assertEqual(self.manager._job["status"], "erro")
        self.assertIn("SHA256SUMS", self.manager._job["message"])


if __name__ == "__main__":
    unittest.main()
