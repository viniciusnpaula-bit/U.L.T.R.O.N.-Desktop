import pytest
from unittest.mock import patch
import seguranca
import sessao


def test_eh_admin_returns_boolean():
    res = seguranca.eh_admin()
    assert isinstance(res, bool)


def test_modo_admin_ativo_requires_both_admin_and_unlocked_session():
    with patch("seguranca.eh_admin", return_value=True):
        sessao.bloquear()
        assert seguranca.modo_admin_ativo("desktop") is False
        sessao.desbloquear("pin")
        assert seguranca.modo_admin_ativo("desktop") is True
        assert seguranca.modo_admin_ativo("bloco1") is True
        assert seguranca.modo_admin_ativo("bloco2") is True
        assert seguranca.modo_admin_ativo("telegram") is False
        assert seguranca.modo_admin_ativo("desconhecida") is False
        assert seguranca.modo_admin_ativo("teste") is False


def test_autorizar_permits_local_admin_without_prompt():
    with patch("seguranca.eh_admin", return_value=True):
        sessao.desbloquear("pin")
        cls = seguranca.Classificacao(
            risco=seguranca.ALTO,
            operacao="arquivo.apagar",
            na_allowlist=False,
            negar="",
            resumo="apagar arquivo de teste"
        )
        decisao, motivo = seguranca.autorizar(cls, ferramenta="apagar_arquivo", origem="desktop")
        assert decisao == seguranca.ALLOW
        assert motivo == "admin_operational_mode"


def test_autorizar_still_denies_protected_paths_even_in_admin():
    with patch("seguranca.eh_admin", return_value=True):
        sessao.desbloquear("pin")
        cls = seguranca.Classificacao(
            risco=seguranca.CRITICO,
            operacao="arquivo.apagar",
            na_allowlist=False,
            negar="protected_path",
            resumo="apagar arquivo protegido"
        )
        decisao, motivo = seguranca.autorizar(cls, ferramenta="apagar_arquivo", origem="desktop")
        assert decisao == seguranca.DENY
        assert motivo == "protected_path"
