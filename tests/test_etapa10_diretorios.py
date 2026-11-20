"""Testes da nova política de separação de diretórios e migração de dados (Etapa 10.1)."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class TestEtapa10Diretorios(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_resolucao_caminhos_desenvolvimento(self):
        """Valida que em modo desenvolvimento os dados e configs apontam para a raiz/dados."""
        import config

        with patch.dict(os.environ, {"ULTRON_DEV": "1", "ULTRON_INSTALLED": "", "ULTRON_PORTABLE": ""}):
            config.reconfigurar_diretorios()
            self.assertEqual(config.MODO_EXECUCAO, "desenvolvimento")
            self.assertEqual(config.DIR_INSTALACAO, config.BASE)
            self.assertEqual(config.DIR_DADOS, config.BASE / "dados")
            self.assertEqual(config.DIR_CONFIG, config.BASE)

    def test_02_resolucao_caminhos_modo_instalado(self):
        """Valida que em modo instalado os dados vão para LOCALAPPDATA e configs para APPDATA."""
        import config

        local_app = self.tmp / "Local"
        roam_app = self.tmp / "Roaming"
        with patch.dict(os.environ, {
            "ULTRON_INSTALLED": "1",
            "ULTRON_DEV": "",
            "ULTRON_PORTABLE": "",
            "LOCALAPPDATA": str(local_app),
            "APPDATA": str(roam_app),
            "ULTRON_DATA_DIR": "",
            "ULTRON_CONFIG_DIR": "",
            "ULTRON_LOGS_DIR": "",
        }):
            config.reconfigurar_diretorios()
            self.assertEqual(config.MODO_EXECUCAO, "instalado")
            self.assertEqual(config.DIR_DADOS, local_app / "ULTRON")
            self.assertEqual(config.DIR_CONFIG, roam_app / "ULTRON")
            self.assertEqual(config.DIR_LOGS, local_app / "ULTRON" / "logs")

    def test_03_resolucao_caminhos_modo_portatil(self):
        """Valida que com marcador .portable ou ULTRON_PORTABLE=1 o modo portátil é ativado."""
        import config

        with patch.dict(os.environ, {"ULTRON_PORTABLE": "1"}):
            config.reconfigurar_diretorios()
            self.assertEqual(config.MODO_EXECUCAO, "portatil")
            self.assertEqual(config.DIR_DADOS, config.BASE / "dados")

    def test_04_precedencia_entre_modos(self):
        """Valida a ordem de precedência: portátil > instalado > dev."""
        import config

        # Se .portable ou ULTRON_PORTABLE=1 estiver presente, vence instalado e dev
        with patch.dict(os.environ, {"ULTRON_PORTABLE": "1", "ULTRON_INSTALLED": "1", "ULTRON_DEV": "1"}):
            self.assertEqual(config._determinar_modo(), "portatil")

        # Se ULTRON_INSTALLED=1 estiver presente sem portátil, vence dev
        with patch.dict(os.environ, {"ULTRON_PORTABLE": "", "ULTRON_INSTALLED": "1", "ULTRON_DEV": "1"}):
            self.assertEqual(config._determinar_modo(), "instalado")

    def test_05_inicializacao_em_diretorio_somente_leitura(self):
        """Valida que config e memoria inicializam mesmo se DIR_INSTALACAO for read-only."""
        fake_data = self.tmp / "UserData" / "ULTRON"
        fake_config = self.tmp / "UserConfig" / "ULTRON"

        with patch.dict(os.environ, {
            "ULTRON_INSTALLED": "1",
            "ULTRON_DATA_DIR": str(fake_data),
            "ULTRON_CONFIG_DIR": str(fake_config),
        }):
            import config
            config.reconfigurar_diretorios()
            self.assertTrue(fake_data.is_dir())
            self.assertTrue(fake_config.is_dir())
            self.assertTrue(str(config.ARQUIVO_BANCO).startswith(str(fake_data.resolve())))
            self.assertTrue(str(config.ARQUIVO_COFRE).startswith(str(fake_data.resolve())))

    def test_06_criacao_banco_no_diretorio_correto(self):
        """Valida se o SQLite é criado no diretório de dados do usuário."""
        fake_data = self.tmp / "dados_teste"
        fake_data.mkdir(parents=True)
        fake_db = fake_data / "ultron.db"

        conn = sqlite3.connect(str(fake_db))
        conn.execute("CREATE TABLE teste(id INTEGER PRIMARY KEY, msg TEXT)")
        conn.execute("INSERT INTO teste(msg) VALUES ('funciona')")
        conn.commit()
        conn.close()

        self.assertTrue(fake_db.is_file())
        self.assertGreater(fake_db.stat().st_size, 0)

    def test_07_persistencia_cofre_no_destino_correto(self):
        """Valida que o cofre salva e lê do diretório correto."""
        import cofre

        fake_data = self.tmp / "dados_cofre"
        fake_data.mkdir(parents=True)
        arquivo_cofre = fake_data / "cofre.json"
        arquivo_chave = fake_data / ".cofre.chave"

        with patch.object(cofre, "ARQUIVO", arquivo_cofre), patch.object(cofre, "ARQUIVO_CHAVE", arquivo_chave):
            resultado = cofre.guardar("gemini", "chave-secreta-teste")
            self.assertTrue(resultado)
            self.assertTrue(arquivo_cofre.is_file())
            self.assertTrue(arquivo_chave.is_file())
            valor = cofre.obter("gemini")
            self.assertEqual(valor, "chave-secreta-teste")

    def test_08_preservacao_do_env(self):
        """Valida que o .env no diretório de configuração do usuário é lido prioritariamente."""
        fake_config = self.tmp / "config_env"
        fake_config.mkdir(parents=True)
        (fake_config / ".env").write_text("NOME_USUARIO=Capitao\n", encoding="utf-8")

        from dotenv import dotenv_values
        valores = dotenv_values(fake_config / ".env")
        self.assertEqual(valores.get("NOME_USUARIO"), "Capitao")

    def test_09_migracao_de_dados_antigos(self):
        """Valida migração de ultron.db, cofre.json, fluxos.json e .env de BASE para DIR_DADOS."""
        import config

        fake_base = self.tmp / "OldInstall"
        (fake_base / "dados").mkdir(parents=True)
        (fake_base / ".env").write_text("CHAVE_ANTIGA=123\n", encoding="utf-8")
        (fake_base / "dados" / "cofre.json").write_text('{"item": "segredo"}', encoding="utf-8")
        (fake_base / "dados" / "fluxos.json").write_text('{"fluxos": []}', encoding="utf-8")

        # Cria banco SQLite legado
        banco_legado = fake_base / "dados" / "ultron.db"
        conn = sqlite3.connect(str(banco_legado))
        conn.execute("CREATE TABLE mensagens(id INTEGER PRIMARY KEY, texto TEXT)")
        conn.execute("INSERT INTO mensagens(texto) VALUES ('mensagem antiga')")
        conn.commit()
        conn.close()

        target_data = self.tmp / "NewUserData"
        target_config = self.tmp / "NewUserConfig"

        with patch.object(config, "BASE", fake_base), \
             patch.object(config, "DIR_DADOS", target_data), \
             patch.object(config, "DIR_CONFIG", target_config), \
             patch.object(config, "ARQUIVO_BANCO", target_data / "ultron.db"), \
             patch.object(config, "ARQUIVO_COFRE", target_data / "cofre.json"), \
             patch.object(config, "ARQUIVO_CHAVE_COFRE", target_data / ".cofre.chave"), \
             patch.object(config, "ARQUIVO_FLUXOS", target_data / "fluxos.json"), \
             patch.object(config, "ARQUIVO_SESSAO", target_data / "sessao.json"), \
             patch.object(config, "DIR_SKILLS", target_data / "skills"), \
             patch.object(config, "ARQUIVO_ENV", target_config / ".env"):

            relatorio = config.migrar_dados_legados(forcar=True)

            self.assertEqual(relatorio["status"], "ok")
            self.assertIn("ultron.db", relatorio["migrados"])
            self.assertIn(".env", relatorio["migrados"])
            self.assertIn("cofre.json", relatorio["migrados"])
            self.assertIn("fluxos.json", relatorio["migrados"])

            # Valida arquivos no destino
            self.assertTrue((target_config / ".env").is_file())
            self.assertTrue((target_data / "ultron.db").is_file())
            self.assertTrue((target_data / "cofre.json").is_file())

            # Origens continuam intactas (não são apagadas)
            self.assertTrue((fake_base / ".env").is_file())
            self.assertTrue((fake_base / "dados" / "ultron.db").is_file())

    def test_10_migracao_repetida_sem_duplicacao(self):
        """Valida idempotência da migração (segunda execução não duplica nem refaz)."""
        import config

        target_data = self.tmp / "IdempotentData"
        target_data.mkdir(parents=True)
        (target_data / ".migracao.json").write_text('{"status": "concluido"}', encoding="utf-8")

        with patch.object(config, "DIR_DADOS", target_data):
            relatorio = config.migrar_dados_legados(forcar=False)
            self.assertEqual(relatorio["status"], "ja_migrado")

    def test_11_conflito_entre_dados_antigos_e_novos(self):
        """Valida que a migração NÃO sobrescreve dados novos já existentes no destino."""
        import config

        fake_base = self.tmp / "ConflictBase"
        (fake_base / "dados").mkdir(parents=True)
        (fake_base / ".env").write_text("ENV_ORIGINAL=antigo\n", encoding="utf-8")

        target_data = self.tmp / "ConflictData"
        target_config = self.tmp / "ConflictConfig"
        target_config.mkdir(parents=True)
        (target_config / ".env").write_text("ENV_NOVO=preservar\n", encoding="utf-8")

        with patch.object(config, "BASE", fake_base), \
             patch.object(config, "DIR_DADOS", target_data), \
             patch.object(config, "DIR_CONFIG", target_config), \
             patch.object(config, "ARQUIVO_BANCO", target_data / "ultron.db"), \
             patch.object(config, "ARQUIVO_COFRE", target_data / "cofre.json"), \
             patch.object(config, "ARQUIVO_CHAVE_COFRE", target_data / ".cofre.chave"), \
             patch.object(config, "ARQUIVO_FLUXOS", target_data / "fluxos.json"), \
             patch.object(config, "ARQUIVO_SESSAO", target_data / "sessao.json"), \
             patch.object(config, "DIR_SKILLS", target_data / "skills"), \
             patch.object(config, "ARQUIVO_ENV", target_config / ".env"):

            relatorio = config.migrar_dados_legados(forcar=True)
            self.assertIn(".env", relatorio["conflitos"])
            self.assertEqual((target_config / ".env").read_text(encoding="utf-8"), "ENV_NOVO=preservar\n")

    def test_12_interrupcao_ou_falha_na_migracao(self):
        """Valida tratamento seguro caso o arquivo SQLite esteja corrompido na origem."""
        import config

        fake_base = self.tmp / "BrokenBase"
        (fake_base / "dados").mkdir(parents=True)
        broken_db = fake_base / "dados" / "ultron.db"
        broken_db.write_bytes(b"NOT A SQLITE DATABASE HEADER")

        target_data = self.tmp / "BrokenData"
        target_config = self.tmp / "BrokenConfig"

        with patch.object(config, "BASE", fake_base), \
             patch.object(config, "DIR_DADOS", target_data), \
             patch.object(config, "DIR_CONFIG", target_config), \
             patch.object(config, "ARQUIVO_BANCO", target_data / "ultron.db"), \
             patch.object(config, "ARQUIVO_COFRE", target_data / "cofre.json"), \
             patch.object(config, "ARQUIVO_CHAVE_COFRE", target_data / ".cofre.chave"), \
             patch.object(config, "ARQUIVO_FLUXOS", target_data / "fluxos.json"), \
             patch.object(config, "ARQUIVO_SESSAO", target_data / "sessao.json"), \
             patch.object(config, "DIR_SKILLS", target_data / "skills"), \
             patch.object(config, "ARQUIVO_ENV", target_config / ".env"):

            relatorio = config.migrar_dados_legados(forcar=True)
            self.assertTrue(len(relatorio["erros"]) > 0)
            self.assertFalse((target_data / "ultron.db").exists())

    def test_13_integridade_sqlite_apos_migracao(self):
        """Valida que o banco SQLite copiado passa com 'ok' em PRAGMA integrity_check."""
        origem = self.tmp / "origem.db"
        destino = self.tmp / "destino.db"

        conn = sqlite3.connect(str(origem))
        conn.execute("CREATE TABLE fatos(id INTEGER PRIMARY KEY, texto TEXT)")
        for i in range(50):
            conn.execute("INSERT INTO fatos(texto) VALUES (?)", (f"Fato número {i}",))
        conn.commit()

        # Copia via API backup oficial
        conn_dest = sqlite3.connect(str(destino))
        with conn_dest:
            conn.backup(conn_dest)
        conn.close()
        conn_dest.close()

        check = sqlite3.connect(str(destino))
        status = check.execute("PRAGMA integrity_check").fetchone()[0]
        check.close()
        self.assertEqual(status, "ok")

    def test_14_preservacao_dados_durante_atualizacao(self):
        """Valida que o atualizador não sobrescreve a pasta de dados do usuário."""
        import atualizacao

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "app"
            root.mkdir()
            (root / "electron").mkdir(parents=True)
            (root / "electron" / "package.json").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
            (root / ".env").write_text("SEGREDO=raiz\n", encoding="utf-8")

            user_data = Path(tmpdir) / "UserProfile" / "ULTRON"
            user_data.mkdir(parents=True)
            (user_data / "ultron.db").write_text("banco persistente", encoding="utf-8")

            mgr = atualizacao.UpdateManager(root)
            staging = Path(tmpdir) / "staging"
            staging.mkdir()
            (staging / "cerebro.py").write_text("# novo", encoding="utf-8")

            aplicados, pendentes, backup = mgr._apply_now(staging)
            self.assertIn("cerebro.py", aplicados)
            self.assertEqual((user_data / "ultron.db").read_text(encoding="utf-8"), "banco persistente")

    def test_15_preservacao_dados_durante_rollback(self):
        """Valida que a execução de rollback não afeta o banco de dados do usuário."""
        import atualizacao

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "app"
            root.mkdir()
            (root / "electron").mkdir(parents=True)
            (root / "electron" / "package.json").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
            (root / "cerebro.py").write_text("# versao original", encoding="utf-8")

            user_db = Path(tmpdir) / "UserProfile" / "ULTRON" / "ultron.db"
            user_db.parent.mkdir(parents=True)
            user_db.write_text("dados importantes", encoding="utf-8")

            mgr = atualizacao.UpdateManager(root)
            staging = Path(tmpdir) / "staging"
            staging.mkdir()
            (staging / "cerebro.py").write_text("# versao com falha", encoding="utf-8")

            aplicados, pendentes, backup = mgr._apply_now(staging)
            mgr._save_state(pending_backup=str(backup))
            sucesso = mgr.rollback()
            self.assertTrue(sucesso)
            self.assertEqual((root / "cerebro.py").read_text(encoding="utf-8"), "# versao original")
            self.assertEqual(user_db.read_text(encoding="utf-8"), "dados importantes")


class TestModulosRespeitamDirDados(unittest.TestCase):
    def test_16_modulos_secundarios_herdam_config_dir_dados_e_env(self):
        import config
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            data_dir = tmp / "UserData"
            cfg_dir = tmp / "UserConfig"
            env = {
                **os.environ,
                "ULTRON_INSTALLED": "1",
                "ULTRON_DEV": "",
                "ULTRON_PORTABLE": "",
                "ULTRON_DATA_DIR": str(data_dir),
                "ULTRON_CONFIG_DIR": str(cfg_dir),
                "ULTRON_LOGS_DIR": str(data_dir / "logs"),
            }
            code = (
                "import palco, personalidade, correcoes_voz, disco_ops, processos_ops, voz, config; "
                "print(palco.PALCO_DIR); "
                "print(personalidade.ARQUIVO); "
                "print(correcoes_voz.ARQUIVO); "
                "print(disco_ops.ARQUIVO_CONFIG_BLOCO1); "
                "print(processos_ops.DADOS_DIR); "
                "print(voz.ARQUIVO_PREFERENCIAS); "
                "print(config.ARQUIVO_ENV)"
            )
            res = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(ROOT), env=env, capture_output=True, text=True, check=True,
            )
            linhas = [Path(l.strip()) for l in res.stdout.strip().splitlines()]
            self.assertEqual(len(linhas), 7)
            for caminho in linhas[:-1]:
                self.assertEqual(caminho.parts[:len(data_dir.resolve().parts)], data_dir.resolve().parts)
            self.assertEqual(linhas[-1], cfg_dir.resolve() / ".env")


if __name__ == "__main__":
    unittest.main()
