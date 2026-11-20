"""Testes para controle isolado de volume por aplicativo (audio_apps + ferramentas)."""
from contextlib import contextmanager
from unittest import mock

import audio_apps
import autoconhecimento
import ferramentas


def _fake_sessao(pid, exe, volume=100, mudo=False, ativa=False, display="", sistema=False, log=None):
    estado = {"volume": volume, "mudo": mudo}

    def set_vol(novo):
        estado["volume"] = novo
        if log is not None:
            log.append((exe, "vol", novo))

    def set_mute(novo):
        estado["mudo"] = novo
        if log is not None:
            log.append((exe, "mute", novo))

    return audio_apps.SessaoAudio(
        pid=pid,
        executavel=exe,
        nome_exibicao=display,
        volume=volume,
        mudo=mudo,
        ativa=ativa,
        sistema=sistema,
        definir_volume=set_vol,
        definir_mudo=set_mute,
    ), estado


def _provedor_de(sessoes):
    @contextmanager
    def _ctx():
        yield sessoes
    return _ctx


def test_define_volume_google_e_spotify_isoladamente():
    chamadas = []
    c1, st_c1 = _fake_sessao(101, "chrome.exe", volume=100, ativa=True, log=chamadas)
    c2, st_c2 = _fake_sessao(102, "chrome.exe", volume=100, ativa=False, log=chamadas)
    sp, st_sp = _fake_sessao(201, "Spotify.exe", volume=100, ativa=True, log=chamadas)
    prov = _provedor_de([c1, c2, sp])

    r_chrome = audio_apps.controlar_volume_app("google", nivel=70, provedor=prov)
    r_spotify = audio_apps.controlar_volume_app("spotify", nivel=30, provedor=prov)

    assert "Google Chrome" in r_chrome and "70%" in r_chrome
    assert "Spotify" in r_spotify and "30%" in r_spotify
    assert st_c1["volume"] == 70
    assert st_c2["volume"] == 70
    assert st_sp["volume"] == 30


def test_definir_volume_positivo_desmuta_sessao_mutada():
    sp, st_sp = _fake_sessao(201, "Spotify.exe", volume=50, mudo=True, ativa=True)
    prov = _provedor_de([sp])

    resp = audio_apps.controlar_volume_app("spotify", nivel=45, provedor=prov)

    assert "45%" in resp and "desmutado" in resp
    assert st_sp["volume"] == 45
    assert st_sp["mudo"] is False


def test_acoes_relativas_mutar_desmutar_e_consultar():
    dc, st_dc = _fake_sessao(301, "Discord.exe", volume=60, mudo=False, ativa=True)
    prov = _provedor_de([dc])

    assert "60%" in audio_apps.controlar_volume_app("discord", acao="consultar", provedor=prov)

    r_up = audio_apps.controlar_volume_app("discord", nivel=20, acao="aumentar", provedor=prov)
    assert "80%" in r_up and st_dc["volume"] == 80
    dc.volume = 80

    r_down = audio_apps.controlar_volume_app("discord", nivel=30, acao="diminuir", provedor=prov)
    assert "50%" in r_down and st_dc["volume"] == 50
    dc.volume = 50

    r_mute = audio_apps.controlar_volume_app("discord", acao="mutar", provedor=prov)
    assert "mutado" in r_mute.lower() and st_dc["mudo"] is True
    dc.mudo = True

    r_toggle = audio_apps.controlar_volume_app("discord", acao="alternar_mudo", provedor=prov)
    assert "reativado" in r_toggle.lower() and st_dc["mudo"] is False


def test_correspondencia_parcial_fuzzy_e_sistema():
    hk, st_hk = _fake_sessao(401, "Hollow Knight Silksong.exe", volume=90, ativa=True)
    sp, st_sp = _fake_sessao(201, "Spotify.exe", volume=40, ativa=True)
    sys_s, st_sys = _fake_sessao(0, "System Sounds", volume=100, sistema=True, display="Sons do sistema")
    prov = _provedor_de([hk, sp, sys_s])

    r_hk = audio_apps.controlar_volume_app("silksong", nivel=55, provedor=prov)
    r_fuzzy = audio_apps.controlar_volume_app("spotfy", nivel=25, provedor=prov)
    r_sys = audio_apps.controlar_volume_app("sistema", nivel=10, provedor=prov)

    assert "55%" in r_hk and st_hk["volume"] == 55
    assert "Spotify" in r_fuzzy and st_sp["volume"] == 25
    assert "Sons do sistema" in r_sys and st_sys["volume"] == 10


def test_processo_sem_sessao_e_listagem():
    sp, _ = _fake_sessao(201, "Spotify.exe", volume=30, ativa=True)
    prov = _provedor_de([sp])

    lista = audio_apps.listar_volumes_apps(provedor=prov)
    assert "Spotify: 30% (tocando)" in lista

    aberto = audio_apps.controlar_volume_app(
        "google",
        nivel=70,
        provedor=prov,
        verificar_processo=lambda _: "chrome.exe",
    )
    assert "chrome.exe" in aberto
    assert "não iniciou nenhuma sessão de áudio" in aberto
    assert "Spotify: 30%" in aberto


def test_ferramentas_volume_app_passam_pelo_portao_sem_confirmacao():
    pedidos = []
    confirmar = lambda msg, pedido: pedidos.append(pedido) or False

    with mock.patch("audio_apps.controlar_volume_app", return_value="Volume de Spotify ajustado para 30%.") as mk_ctl:
        res = ferramentas.executar(
            "ajustar_volume_app",
            {"aplicativo": "spotify", "nivel": 30},
            confirmar,
            origem="desktop",
        )
    assert res == "Volume de Spotify ajustado para 30%."
    assert pedidos == []
    mk_ctl.assert_called_once_with(aplicativo="spotify", nivel=30, acao="definir")

    with mock.patch("audio_apps.listar_volumes_apps", return_value="Apps com áudio no Windows: Spotify: 30%.") as mk_lst:
        res_lst = ferramentas.executar("listar_volumes_apps", {}, confirmar, origem="desktop")
    assert "Spotify: 30%" in res_lst
    assert pedidos == []
    mk_lst.assert_called_once_with()

    assert "ajustar_volume_app" in autoconhecimento._GRUPOS["mídia e palco"]
    assert "listar_volumes_apps" in autoconhecimento._GRUPOS["mídia e palco"]
