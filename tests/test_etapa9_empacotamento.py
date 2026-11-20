"""Testes de integridade de empacotamento, distribuição e atualização segura (Etapa 9 e 9.1)."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class TestEtapa9Empacotamento(unittest.TestCase):
    def test_electron_build_files_contains_all_core_assets(self):
        """Valida se o manifesto do Electron empacota todos os componentes do frontend."""
        pkg_path = ROOT / "electron" / "package.json"
        self.assertTrue(pkg_path.is_file(), "electron/package.json não encontrado")
        pkg_data = json.loads(pkg_path.read_text(encoding="utf-8"))
        files = pkg_data.get("build", {}).get("files", [])

        expected_files = [
            "main.js",
            "preload.js",
            "api.js",
            "site/index.html",
            "site/app.js",
            "site/src/orb.js",
            "site/src/real.js",
            "site/src/skills.js",
            "site/src/unlock.js",
            "assets/ULTRON.ico",
        ]
        for expected in expected_files:
            self.assertIn(expected, files, f"Arquivo obrigatório ausente em build.files: {expected}")

    def test_ultron_setup_required_files_includes_core_architecture(self):
        """Valida se o instalador console verifica a presença de todos os módulos vitais."""
        from installer import ultron_setup

        required = set(ultron_setup.REQUIRED_FILES)
        core_modules = {
            "desktop.py",
            "desktop_api.py",
            "desktop_runtime.py",
            "cerebro.py",
            "ferramentas.py",
            "seguranca.py",
            "agendador.py",
            "fluxos.py",
            "skills.py",
            "memoria.py",
            "cofre.py",
            "bandeja.py",
            "requirements.txt",
            "electron/package.json",
            "electron/main.js",
            "electron/site/app.js",
        }
        missing = core_modules - required
        self.assertFalse(missing, f"installer/ultron_setup.py não verifica os módulos essenciais: {missing}")

    def test_build_zip_excludes_sensitive_and_development_artifacts(self):
        """Valida se build_zip não empacota arquivos de ambiente, logs, bancos ou locks."""
        import importlib.util
        builder_path = ROOT / "tools" / "build_setup.py"
        spec = importlib.util.spec_from_file_location("build_setup_module", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_out = Path(tmpdir) / "test_dist.zip"
            fake_env = ROOT / ".env"
            fake_created = not fake_env.exists()
            if fake_created:
                fake_env.write_text("SENSITIVE_KEY=supersecret123\n", encoding="utf-8")
            try:
                archive = builder.build_zip(zip_out)
                self.assertTrue(archive.is_file())
                with zipfile.ZipFile(archive) as z:
                    names = z.namelist()
                    for name in names:
                        self.assertFalse(name == ".env" or name.endswith("/.env"), f".env vazou no pacote: {name}")
                        self.assertFalse(name.endswith((".db", ".sqlite", ".sqlite3")), f"Banco de dados vazou no pacote: {name}")
                        self.assertFalse(name.startswith("venv/") or name.startswith(".venv/"), f"Venv vazou no pacote: {name}")
                        self.assertFalse(name.startswith("node_modules/") or "electron/node_modules" in name, f"node_modules vazou no pacote: {name}")
                        self.assertFalse(name.endswith(".log"), f"Arquivo de log vazou no pacote: {name}")
            finally:
                if fake_created:
                    fake_env.unlink(missing_ok=True)

    def test_atualizacao_apply_now_preserves_user_data_and_supports_rollback(self):
        """Valida se _apply_now protege arquivos sensíveis (.env, dados) e suporta rollback fiel."""
        import atualizacao

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "ultron"
            root.mkdir()
            (root / "electron").mkdir(parents=True)
            (root / "electron" / "package.json").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
            (root / "cerebro.py").write_text("# versao original", encoding="utf-8")
            (root / ".env").write_text("API_KEY=minha-chave-secreta\n", encoding="utf-8")
            (root / "dados").mkdir(parents=True)
            (root / "dados" / "memoria.db").write_text("banco de dados do usuario", encoding="utf-8")

            mgr = atualizacao.UpdateManager(root)

            # Prepara staging com nova versão de código e tentativa de sobrescrita de .env e dados
            staging = Path(tmpdir) / "staging"
            staging.mkdir()
            (staging / "cerebro.py").write_text("# versao atualizada 2.1.1", encoding="utf-8")
            (staging / ".env").write_text("API_KEY=tentativa-de-sobrescrever\n", encoding="utf-8")
            (staging / "dados").mkdir(parents=True)
            (staging / "dados" / "memoria.db").write_text("tentativa-banco-falso", encoding="utf-8")

            aplicados, pendentes, backup = mgr._apply_now(staging)

            # Verifica que cerebro.py foi atualizado
            self.assertIn("cerebro.py", aplicados)
            self.assertEqual((root / "cerebro.py").read_text(encoding="utf-8"), "# versao atualizada 2.1.1")

            # Verifica que .env e dados NUNCA foram sobrescritos
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), "API_KEY=minha-chave-secreta\n")
            self.assertEqual((root / "dados" / "memoria.db").read_text(encoding="utf-8"), "banco de dados do usuario")

            # Executa rollback e verifica restauração da versão original
            mgr._save_state(pending_backup=str(backup))
            sucesso_rollback = mgr.rollback()
            self.assertTrue(sucesso_rollback)
            self.assertEqual((root / "cerebro.py").read_text(encoding="utf-8"), "# versao original")
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), "API_KEY=minha-chave-secreta\n")

    def test_case_insensitive_ntfs_protection(self):
        """Valida se tentativas de sobrescrever arquivos protegidos com variações de maiúsculas falham (NTFS)."""
        import atualizacao

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "ultron"
            root.mkdir()
            (root / "electron").mkdir(parents=True)
            (root / "electron" / "package.json").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
            (root / ".env").write_text("SEGREDO=real\n", encoding="utf-8")
            (root / "dados").mkdir(parents=True)
            (root / "dados" / "memoria.db").write_text("db real", encoding="utf-8")

            mgr = atualizacao.UpdateManager(root)
            staging = Path(tmpdir) / "staging"
            staging.mkdir()
            # Tenta injetar .ENV e DADOS/ com maiúsculas
            (staging / ".ENV").write_text("SEGREDO=falso\n", encoding="utf-8")
            (staging / "DADOS").mkdir(parents=True)
            (staging / "DADOS" / "memoria.db").write_text("db falso", encoding="utf-8")

            aplicados, pendentes, backup = mgr._apply_now(staging)
            self.assertNotIn(".ENV", aplicados)
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), "SEGREDO=real\n")

    def test_apply_script_excludes_environment_and_state(self):
        """Valida se o script de reinício (.bat) do robocopy exclui estritamente .env e .ultron-state.json."""
        import atualizacao

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "ultron"
            root.mkdir()
            (root / "electron").mkdir(parents=True)
            (root / "electron" / "package.json").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
            mgr = atualizacao.UpdateManager(root)

            staging = Path(tmpdir) / "staging"
            staging.mkdir()
            backup = Path(tmpdir) / "backup"
            backup.mkdir()

            script_path = mgr._write_apply_script(staging, backup)
            self.assertTrue(script_path.is_file())
            conteudo = script_path.read_text(encoding="utf-8")
            self.assertIn("/XF *.log .env .ultron-state.json", conteudo)

    def test_installer_clean_windows_dependency_detection(self):
        """Valida que o instalador ultron_setup exige dependências externas e falha claramente na ausência."""
        from installer import ultron_setup

        console = ultron_setup.Console(ROOT)
        with patch.object(ultron_setup, "command_path", return_value=None):
            with patch.dict(os.environ, {"PATH": ""}, clear=True):
                # Sem node no PATH
                with self.assertRaises(ultron_setup.SetupError) as ctx_node:
                    ultron_setup.find_node(console)
                self.assertIn("Node.js não encontrado", str(ctx_node.exception))

    def test_step_doctor_returns_nonzero_on_critical_failure(self):
        """step_doctor retorna 1 quando falha item crítico e 0 quando só avisos falham."""
        from installer import ultron_setup

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_root = Path(tmpdir)
            console = ultron_setup.Console(fake_root)
            fake_py = fake_root / "python.exe"
            with patch.object(ultron_setup, "run", return_value=type("R", (), {"returncode": 1})()), \
                 patch.object(ultron_setup.urllib.request, "urlopen", side_effect=OSError("offline")):
                code_fail = ultron_setup.step_doctor(fake_root, console, fake_py, False)
            self.assertEqual(code_fail, 1)

            for rel in ultron_setup.REQUIRED_FILES:
                p = fake_root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# stub", encoding="utf-8")
            electron_exe = fake_root / "electron" / "node_modules" / "electron" / "dist" / "electron.exe"
            electron_exe.parent.mkdir(parents=True, exist_ok=True)
            electron_exe.write_bytes(b"MZ")
            with patch.object(ultron_setup, "run", return_value=type("R", (), {"returncode": 0})()), \
                 patch.object(ultron_setup.urllib.request, "urlopen", side_effect=OSError("offline")):
                code_ok = ultron_setup.step_doctor(fake_root, console, fake_py, False)
            self.assertEqual(code_ok, 0)


if __name__ == "__main__":
    unittest.main()
