"""Testes dos módulos extraídos de ferramentas.py (`ferramentas_apps` e `ferramentas_sites`)."""
from unittest.mock import patch

import ferramentas
import ferramentas_apps
import ferramentas_sites


def test_ferramentas_sites_sanitiza_destino_e_escapa_html(tmp_path):
    destino = ferramentas_sites.montar_destino_site(tmp_path, "Minha Página!@")
    assert destino == (tmp_path / "Minha-P-gina.html").resolve()
    assert ferramentas_sites.montar_destino_site(tmp_path, "..") == (tmp_path / "site.html").resolve()

    html_out = ferramentas_sites.gerar_html_site("<script>x</script>", "A & B\n\nC < D")
    assert "&lt;script&gt;x&lt;/script&gt;" in html_out
    assert "<p>A &amp; B</p>" in html_out
    assert "<p>C &lt; D</p>" in html_out


def test_criar_site_em_ferramentas_usa_modulo_e_nao_sobrescreve(tmp_path):
    autorizar = patch.object(ferramentas, "_caminho", return_value=tmp_path)
    registrar = patch.object(ferramentas, "_desfazer_registrar")
    orig_auth = ferramentas._AUTORIZADO.set("criar_site")
    try:
        with autorizar, registrar as mock_undo:
            msg1 = ferramentas.criar_site(str(tmp_path), "painel", "Olá", "Linha 1")
            assert "Site criado em" in msg1
            alvo = tmp_path / "painel.html"
            assert alvo.exists()
            html_lido = alvo.read_text(encoding="utf-8")
            assert "<h1>Olá</h1>" in html_lido
            assert "<p>Linha 1</p>" in html_lido
            mock_undo.assert_called_once()

            msg2 = ferramentas.criar_site(str(tmp_path), "painel", "Novo", "Outro")
            assert msg2 == "Esse arquivo já existe; não vou sobrescrever."
    finally:
        ferramentas._AUTORIZADO.reset(orig_auth)


def test_resolver_app_em_ferramentas_respeita_monkeypatch_em_catalogo():
    catalogo_falso = {
        "visualstudiocode": ("Visual Studio Code", "arquivo", r"C:\Apps\Code.exe"),
        "notepad": ("Notepad++", "arquivo", r"C:\Apps\notepad++.exe"),
    }
    with patch.object(ferramentas, "_catalogo", return_value=catalogo_falso) as mock_cat:
        item, score = ferramentas._resolver_app("Visual Studio")
        mock_cat.assert_called_once()
        assert item == ("Visual Studio Code", "arquivo", r"C:\Apps\Code.exe")
        assert score == 0.9


def test_ferramentas_apps_normalizacao_e_busca():
    assert ferramentas_apps._norm("São Paulo 2!") == "saopaulo2"
    dados = {
        "calcpro": ("Calc Pro", "appid", "calc"),
        "outro": ("Outro", "arquivo", "x"),
    }
    item, score = ferramentas_apps._buscar(dados, "calc")
    assert item == ("Calc Pro", "appid", "calc")
    assert score == 0.9
