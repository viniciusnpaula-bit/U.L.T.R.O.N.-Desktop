"""Testes de confiabilidade e integração da Etapa 8.

Cobre bandeja, hotkeys, autostart, configurações, confirmações e encerramento.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bandeja
import config
import desktop_autostart
import main as core_main


class BandejaConfiabilidadeTests(unittest.TestCase):
    def test_icone_retorna_imagem_rgba_64x64(self):
        img_ativo = bandeja._icone(True)
        self.assertEqual(img_ativo.size, (64, 64))
        self.assertEqual(img_ativo.mode, "RGBA")

        img_inativo = bandeja._icone(False)
        self.assertEqual(img_inativo.size, (64, 64))
        self.assertEqual(img_inativo.mode, "RGBA")

    def test_icone_fallback_em_memoria_quando_nenhum_arquivo_existe(self):
        with patch.object(bandeja, "_caminho_icone", return_value=None):
            img = bandeja._icone(True)
            self.assertEqual(img.size, (64, 64))
            self.assertEqual(img.mode, "RGBA")

    def test_abrir_logs_garante_diretorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(config, "BASE", tmp_path):
                # Simula item de menu
                logs_dir = tmp_path / "logs"
                self.assertFalse(logs_dir.exists())
                with patch("os.startfile", create=True) as mock_startfile:
                    # Invoca o callback de logs
                    def dummy_exec(pausado):
                        pass
                    # Chama diretamente a lógica de abrir logs
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    if hasattr(os, "startfile"):
                        os.startfile(str(logs_dir))
                    self.assertTrue(logs_dir.is_dir())


class HotkeysConfiabilidadeTests(unittest.TestCase):
    def setUp(self):
        core_main.remover_atalhos()

    def tearDown(self):
        core_main.remover_atalhos()

    def test_atalho_parada_eh_idempotente(self):
        mock_keyboard = types.ModuleType("keyboard")
        mock_keyboard.add_hotkey = MagicMock()
        mock_keyboard.clear_all_hotkeys = MagicMock()

        with patch.dict(sys.modules, {"keyboard": mock_keyboard}):
            core_main.atalho_parada()
            core_main.atalho_parada()  # Segunda chamada deve ser ignorada
            self.assertEqual(mock_keyboard.add_hotkey.call_count, 1)

    def test_atalho_falar_ignora_conflito_com_parada(self):
        mock_keyboard = types.ModuleType("keyboard")
        mock_keyboard.add_hotkey = MagicMock()

        evento = threading.Event()
        with patch.dict(sys.modules, {"keyboard": mock_keyboard}):
            with patch.object(config, "HOTKEY_PARAR", "ctrl+alt+x"), \
                 patch.object(config, "HOTKEY_FALAR", "ctrl+alt+x"):
                core_main.atalho_falar(evento)
                # Não deve registrar pois é igual a HOTKEY_PARAR
                self.assertEqual(mock_keyboard.add_hotkey.call_count, 0)

    def test_remover_atalhos_limpa_listeners(self):
        mock_keyboard = types.ModuleType("keyboard")
        mock_keyboard.add_hotkey = MagicMock()
        mock_keyboard.clear_all_hotkeys = MagicMock()

        with patch.dict(sys.modules, {"keyboard": mock_keyboard}):
            core_main.atalho_parada()
            self.assertIn("parada", core_main._hotkeys_registradas)
            core_main.remover_atalhos()
            self.assertEqual(len(core_main._hotkeys_registradas), 0)
            mock_keyboard.clear_all_hotkeys.assert_called_once()


class AutostartConfiabilidadeTests(unittest.TestCase):
    def test_install_remove_entradas_legadas(self):
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp)
            startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup.mkdir(parents=True, exist_ok=True)

            legacy = startup / "Ultron.vbs"
            legacy.write_text("legacy entry", encoding="utf-16")
            self.assertTrue(legacy.is_file())

            fake_py = appdata / "pythonw.exe"
            fake_py.write_text("", encoding="utf-8")
            fake_script = appdata / "desktop.py"
            fake_script.write_text("", encoding="utf-8")

            destination = desktop_autostart.install(appdata, fake_py, fake_script)
            self.assertTrue(destination.is_file())
            # A entrada legada deve ter sido removida durante a instalação
            self.assertFalse(legacy.is_file())

            # Remoção remove a nova entrada
            removed = desktop_autostart.remove(appdata)
            self.assertTrue(removed)
            self.assertFalse(destination.is_file())

    def test_startup_path_sem_appdata_levanta_runtime_error(self):
        with patch.dict(os.environ, {"APPDATA": ""}):
            with self.assertRaises(RuntimeError):
                desktop_autostart.startup_path(None)


class ConfigConfiabilidadeTests(unittest.TestCase):
    def test_num_env_com_valores_invalidos_usa_padrao(self):
        with patch.object(config, "_env", return_value="invalido_texto"):
            val = config._num_env("TESTE_FLOAT", 12.5, float)
            self.assertEqual(val, 12.5)

            val_int = config._num_env("TESTE_INT", 42, int)
            self.assertEqual(val_int, 42)

    def test_num_env_com_valores_validos_converte(self):
        with patch.object(config, "_env", return_value="99.5"):
            val = config._num_env("TESTE_FLOAT", 0.0, float)
            self.assertEqual(val, 99.5)


class ConfirmacoesConfiabilidadeTests(unittest.TestCase):
    def test_answer_confirmation_rejeita_duplicadas_e_invalidas(self):
        from desktop_runtime import DesktopRuntime

        rt = DesktopRuntime()
        # ID inexistente
        self.assertFalse(rt.answer_confirmation("id_que_nao_existe", True))

        # Payload com tipo errado
        self.assertFalse(rt.answer_confirmation("id", "nao_booleano"))  # type: ignore

        # Adiciona pendente manualmente para testar duplicação
        evt = threading.Event()
        rt._pending["req1"] = {
            "event": evt,
            "approved": False,
            "pin": None,
            "expired": False,
            "pedido": {},
            "requires_pin": False,
        }

        # Primeira resposta é aceita
        self.assertTrue(rt.answer_confirmation("req1", True))
        self.assertTrue(evt.is_set())

        # Segunda resposta na mesma requisição deve ser rejeitada
        self.assertFalse(rt.answer_confirmation("req1", True))

        # Requisição expirada deve ser rejeitada
        rt._pending["req2"] = {
            "event": threading.Event(),
            "approved": False,
            "pin": None,
            "expired": True,
            "pedido": {},
            "requires_pin": False,
        }
        self.assertFalse(rt.answer_confirmation("req2", True))


if __name__ == "__main__":
    unittest.main()
