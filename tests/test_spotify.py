import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import ferramentas
import spotify


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        spotify._token, spotify._expira = "", 0.0
        for nome, valor in (("SPOTIFY_CLIENT_ID", "id"), ("SPOTIFY_CLIENT_SECRET", "secret"),
                            ("SPOTIFY_REFRESH", "refresh")):
            patch = mock.patch.object(config, nome, valor, create=True)
            patch.start()
            self.addCleanup(patch.stop)

    def test_token_e_cacheado(self):
        with mock.patch("spotify.requests.post") as post:
            post.return_value.ok = True
            post.return_value.json.return_value = {"access_token": "t", "expires_in": 3600}
            self.assertEqual(spotify._token_valido(), "t")
            self.assertEqual(spotify._token_valido(), "t")
            self.assertEqual(post.call_count, 1)

    def test_sem_dispositivo_nao_mente(self):
        with mock.patch("spotify.buscar", return_value={"faixas": [
                {"nome": "One More Time", "artista": "Daft Punk", "uri": "spotify:track:1"}]}), \
             mock.patch("spotify._pedir", side_effect=[
                (404, {"reason": "NO_ACTIVE_DEVICE"}), (200, {"devices": []})]):
            self.assertIn("Abra o Spotify", spotify.tocar("daft punk"))

    def test_conta_sem_premium_e_reportada(self):
        with mock.patch("spotify.buscar", return_value={"faixas": [
                {"nome": "x", "artista": "y", "uri": "spotify:track:2"}]}), \
             mock.patch("spotify._pedir", return_value=(403, {"reason": "PREMIUM_REQUIRED"})):
            self.assertIn("Premium", spotify.tocar("x"))

    def test_tocar_confirma_antes_de_dizer_que_toca(self):
        with mock.patch("spotify.buscar", return_value={"faixas": [
                {"nome": "One More Time", "artista": "Daft Punk", "uri": "spotify:track:1"}]}), \
             mock.patch("spotify._pedir", side_effect=[
                (204, {}), (200, {"is_playing": True, "item": {"uri": "spotify:track:1"}})]):
            self.assertEqual(spotify.tocar("daft punk"), "Tocando One More Time — Daft Punk.")

    def test_tocar_nao_mente_quando_o_204_nao_inicia(self):
        with mock.patch("spotify.buscar", return_value={"faixas": [
                {"nome": "x", "artista": "y", "uri": "spotify:track:2"}]}), \
             mock.patch("spotify._pedir", return_value=(204, {"is_playing": False, "item": None})), \
             mock.patch("spotify.time.sleep"):
            saida = spotify.tocar("x")
        self.assertIn("não confirmei", saida)
        self.assertNotIn("Tocando", saida)

    def test_buscar_devolve_faixas_e_artistas(self):
        corpo = {"tracks": {"items": [{"name": "One More Time", "uri": "spotify:track:1",
                                       "artists": [{"name": "Daft Punk"}]}]},
                 "artists": {"items": [{"name": "Daft Punk", "uri": "spotify:artist:1"}]},
                 "playlists": {"items": []}}
        with mock.patch("spotify._pedir", return_value=(200, corpo)):
            resultado = spotify.buscar("daft punk")
        self.assertEqual(resultado["faixas"], [{"nome": "One More Time", "artista": "Daft Punk",
                                                "uri": "spotify:track:1"}])
        self.assertEqual(resultado["artistas"][0]["nome"], "Daft Punk")

    def test_buscar_ignora_itens_nulos(self):
        corpo = {"tracks": {"items": [None, {"name": "x", "uri": "u", "artists": None}]},
                 "artists": {"items": [None]},
                 "playlists": {"items": [None, {"name": "p", "uri": "pu"}]}}
        with mock.patch("spotify._pedir", return_value=(200, corpo)):
            resultado = spotify.buscar("x")
        self.assertEqual([f["nome"] for f in resultado["faixas"]], ["x"])
        self.assertEqual(resultado["artistas"], [])
        self.assertEqual([p["nome"] for p in resultado["playlists"]], ["p"])

    def test_estado_sem_reproducao(self):
        with mock.patch("spotify._pedir", return_value=(204, {})):
            self.assertFalse(spotify.estado()["tocando"])

    def test_tocar_sem_configuracao_explica(self):
        with mock.patch("spotify.configurado", return_value=False):
            saida = ferramentas.executar("spotify_tocar", {"consulta": "x"}, lambda *_: True, "teste")
        self.assertIn("não está configurado", saida)

    def test_buscar_marca_dado_externo(self):
        with mock.patch("spotify.buscar", return_value={
                "faixas": [{"nome": "n", "artista": "a", "uri": "u"}],
                "artistas": [], "playlists": []}):
            saida = ferramentas.executar("spotify_buscar", {"consulta": "x"}, lambda *_: True, "teste")
        self.assertIn("DADOS EXTERNOS", saida)
        self.assertIn("n — a", saida)

    def test_tocar_e_baixo_risco(self):
        self.assertEqual(ferramentas.FERRAMENTAS["spotify_tocar"]["risco"], "BAIXO")


class IntencaoSpotifyTests(unittest.TestCase):
    def test_pedido_com_conteudo_vai_para_o_nucleo(self):
        import cerebro
        for texto in ("toca Daft Punk no Spotify", "toque Daft Punk no Spotify",
                      "toca uma música no Spotify", "abra o Spotify e toque Daft Punk"):
            self.assertFalse(cerebro._pedido_abrir_spotify(texto), texto)

    def test_abrir_o_app_continua_no_atalho(self):
        import cerebro
        for texto in ("abre o Spotify", "Ultron, abra o Spotify", "toque Spotify",
                      "inicie o spotify"):
            self.assertTrue(cerebro._pedido_abrir_spotify(texto), texto)


if __name__ == "__main__":
    unittest.main()
