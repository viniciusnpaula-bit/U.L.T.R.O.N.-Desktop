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

    def test_minhas_playlists_lista_e_normaliza(self):
        corpo = {
            "items": [
                {
                    "id": "pl_1",
                    "name": "Treino Pesado",
                    "uri": "spotify:playlist:pl_1",
                    "public": False,
                    "collaborative": False,
                    "owner": {"display_name": "Pedro"},
                    "tracks": {"total": 42},
                },
                None,
            ]
        }
        with mock.patch("spotify._pedir", return_value=(200, corpo)):
            pls = spotify.minhas_playlists()
        self.assertEqual(len(pls), 1)
        self.assertEqual(pls[0]["id"], "pl_1")
        self.assertEqual(pls[0]["nome"], "Treino Pesado")
        self.assertEqual(pls[0]["total_faixas"], 42)

    def test_adicionar_musica_tocando_a_playlist_por_nome_aproximado(self):
        estado_atual = {
            "tocando": True,
            "id": "trk_99",
            "uri": "spotify:track:trk_99",
            "faixa": "Harder, Better, Faster, Stronger",
            "artista": "Daft Punk",
            "dispositivo": "PC",
        }
        playlists_fake = [
            {"id": "pl_rock", "nome": "Rock Clássico", "uri": "spotify:playlist:pl_rock", "total_faixas": 10},
            {"id": "pl_treino", "nome": "Meu Treino 2026", "uri": "spotify:playlist:pl_treino", "total_faixas": 25},
        ]
        with mock.patch("spotify.estado", return_value=estado_atual), \
             mock.patch("spotify.minhas_playlists", return_value=playlists_fake), \
             mock.patch("spotify._playlist_ja_contem_faixa", return_value=False), \
             mock.patch("spotify._pedir", return_value=(201, {"snapshot_id": "snap_1"})) as mk_pedir:
            saida = ferramentas.executar(
                "spotify_adicionar_playlist",
                {"playlist": "treino"},
                lambda *_: True,
                "teste",
            )
        mk_pedir.assert_called_once_with(
            "POST",
            "/playlists/pl_treino/items",
            json={"uris": ["spotify:track:trk_99"]},
        )
        self.assertEqual(
            saida,
            "Adicionei Harder, Better, Faster, Stronger — Daft Punk à playlist Meu Treino 2026 no Spotify.",
        )

    def test_adicionar_musica_evita_duplicata_na_playlist(self):
        estado_atual = {
            "tocando": True,
            "id": "trk_1",
            "uri": "spotify:track:trk_1",
            "faixa": "One More Time",
            "artista": "Daft Punk",
            "dispositivo": "PC",
        }
        playlists_fake = [{"id": "pl_1", "nome": "Favoritas", "uri": "spotify:playlist:pl_1", "total_faixas": 5}]
        with mock.patch("spotify.estado", return_value=estado_atual), \
             mock.patch("spotify.minhas_playlists", return_value=playlists_fake), \
             mock.patch("spotify._playlist_ja_contem_faixa", return_value=True), \
             mock.patch("spotify._pedir") as mk_pedir:
            saida = spotify.adicionar_a_playlist("Favoritas")
        mk_pedir.assert_not_called()
        self.assertIn("já está na playlist Favoritas", saida)

    def test_adicionar_musica_as_curtidas(self):
        estado_atual = {
            "tocando": True,
            "id": "trk_77",
            "uri": "spotify:track:trk_77",
            "faixa": "Instant Crush",
            "artista": "Daft Punk",
            "dispositivo": "PC",
        }
        with mock.patch("spotify.estado", return_value=estado_atual), \
             mock.patch("spotify.minhas_playlists", return_value=[]), \
             mock.patch("spotify._pedir", return_value=(200, {})) as mk_pedir:
            saida = spotify.adicionar_a_playlist("curtidas")
        mk_pedir.assert_called_once_with("PUT", "/me/library", params={"uris": "spotify:track:trk_77"})
        self.assertIn("Músicas Curtidas", saida)

    def test_adicionar_quando_nada_tocando_avisa_claramente(self):
        with mock.patch("spotify.estado", return_value={"tocando": False}):
            saida = spotify.adicionar_a_playlist("Treino")
        self.assertIn("Nenhuma música está tocando", saida)

    def test_listar_playlists_ferramenta_marca_dados_externos(self):
        with mock.patch("spotify.minhas_playlists", return_value=[
            {"id": "1", "nome": "Foco", "uri": "u1", "total_faixas": 12}
        ]):
            saida = ferramentas.executar("spotify_listar_playlists", {}, lambda *_: True, "teste")
        self.assertIn("DADOS EXTERNOS", saida)
        self.assertIn("Foco (12 faixas)", saida)


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

    def test_acao_rapida_midia_continuar_pausar_proxima_anterior(self):
        import cerebro
        self.assertEqual(cerebro._acao_rapida("continue a musica"), "midia:continuar")
        self.assertEqual(cerebro._acao_rapida("continua a música no Spotify"), "midia:continuar")
        self.assertEqual(cerebro._acao_rapida("pause a música"), "midia:pausar")
        self.assertEqual(cerebro._acao_rapida("próxima música"), "midia:proxima")
        self.assertEqual(cerebro._acao_rapida("música anterior"), "midia:anterior")
        self.assertEqual(cerebro._acao_rapida("toca Daft Punk no Spotify"), "spotify_tocar:Daft Punk")
        self.assertIsNone(cerebro._acao_rapida("toca uma música no Spotify"))
        self.assertEqual(
            cerebro._acao_rapida("adiciona essa música na minha playlist Treino"),
            "spotify_playlist:Treino",
        )
        self.assertEqual(
            cerebro._acao_rapida("coloca a música que está tocando na playlist de Rock no Spotify"),
            "spotify_playlist:Rock",
        )
        self.assertEqual(
            cerebro._acao_rapida("curte essa música no Spotify"),
            "spotify_playlist:curtidas",
        )

    def test_executar_acao_rapida_midia_aciona_controlar_midia(self):
        import cerebro
        chamadas = []

        def executar(nome, argumentos, confirmar, origem):
            chamadas.append((nome, argumentos, origem))
            return "Feito."

        with mock.patch.object(cerebro, "_rastrear"):
            res_cont = cerebro._executar_acao_rapida("midia:continuar", executar, lambda *_: True, "teste")
            res_pausa = cerebro._executar_acao_rapida("midia:pausar", executar, lambda *_: True, "teste")
            res_prox = cerebro._executar_acao_rapida("midia:proxima", executar, lambda *_: True, "teste")
            res_ant = cerebro._executar_acao_rapida("midia:anterior", executar, lambda *_: True, "teste")

        self.assertEqual(res_cont, "Reprodução retomada.")
        self.assertEqual(res_pausa, "Música pausada.")
        self.assertEqual(res_prox, "Pulando para a próxima faixa.")
        self.assertEqual(res_ant, "Voltando para a faixa anterior.")
        self.assertEqual(chamadas, [
            ("controlar_midia", {"acao": "continuar"}, "teste"),
            ("controlar_midia", {"acao": "pausar"}, "teste"),
            ("controlar_midia", {"acao": "proxima"}, "teste"),
            ("controlar_midia", {"acao": "anterior"}, "teste"),
        ])

    def test_spotify_tocar_usa_fallback_local_quando_sem_dispositivo_ativo(self):
        with mock.patch("spotify.configurado", return_value=True), \
             mock.patch("spotify.tocar", return_value="Abra o Spotify e toque algo para ativar um dispositivo; aí eu troco a faixa."), \
             mock.patch("spotify.ativar_e_tocar_local", return_value="Tocando One More Time — Daft Punk no Spotify.") as mk_local:
            saida = ferramentas.executar("spotify_tocar", {"consulta": "daft punk"}, lambda *_: True, "teste")
        mk_local.assert_called_once_with("daft punk", "Abra o Spotify e toque algo para ativar um dispositivo; aí eu troco a faixa.")
        self.assertEqual(saida, "Tocando One More Time — Daft Punk no Spotify.")

    def test_recordar_ignora_mensagens_antigas_de_erro_do_spotify(self):
        import time
        import memoria
        agora = time.time()
        linhas_fake = [
            (301, agora - 10, "assistant", "Lamento, senhor. O Spotify não está respondendo como esperado. Recomendo que abra o aplicativo e toque em qualquer música para ativar o dispositivo."),
            (300, agora - 20, "assistant", "Abra o Spotify e toque algo para ativar um dispositivo; aí eu troco a faixa."),
            (299, agora - 30, "user", "quero ouvir musica no computador"),
        ]
        with mock.patch("memoria._x", return_value=linhas_fake), \
             mock.patch("memoria._texto", side_effect=lambda _t, _i, v: v):
            lembradas = memoria.recordar("continue a musica", limite=4)
        textos = [item["texto"] for item in lembradas]
        self.assertEqual(textos, ["quero ouvir musica no computador"])

    def test_spotify_controlar_player_nao_pausa_quando_ja_esta_tocando(self):
        with mock.patch("spotify.configurado", return_value=True), \
             mock.patch("spotify.estado", return_value={"tocando": True, "faixa": "Idol", "artista": "YOASOBI"}):
            res = spotify.controlar_player("continuar")
        self.assertIn("já está tocando", res)

    def test_spotify_ativar_e_tocar_local_usa_startfile(self):
        with mock.patch("spotify.configurado", return_value=True), \
             mock.patch("spotify.os.name", "nt"), \
             mock.patch("spotify.os.startfile", create=True) as mk_start, \
             mock.patch("spotify.time.sleep"), \
             mock.patch("spotify.buscar", return_value={"faixas": [
                 {"nome": "One More Time", "artista": "Daft Punk", "uri": "spotify:track:1"}]}), \
             mock.patch("spotify._pedir", side_effect=[
                 (200, {"devices": [{"id": "pc", "is_active": False, "type": "Computer"}]}),
                 (204, {}),
                 (200, {"is_playing": True, "item": {"uri": "spotify:track:1"}})]):
            res = spotify.ativar_e_tocar_local("daft punk")
        mk_start.assert_called_once_with("spotify:track:1")
        self.assertEqual(res, "Tocando One More Time — Daft Punk no Spotify.")


if __name__ == "__main__":
    unittest.main()
