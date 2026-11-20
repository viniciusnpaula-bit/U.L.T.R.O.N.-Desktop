"""Testes dos endpoints da API REST do Bloco 2 em desktop_api.py."""
import http.client
import json
import threading
from unittest.mock import MagicMock, patch
import pytest

import desktop_api


@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt.obter_estado_bloco2.return_value = {
        "config": {"suspensao_abas_ativo": True},
        "status_monitores": {"ativo": True},
        "admin_mode": True,
    }
    rt.atualizar_config_bloco2.return_value = {
        "sucesso": True,
        "config": {"suspensao_abas_limite_mb": 600},
    }
    rt.executar_acao_bloco2.return_value = {
        "sucesso": True,
        "resultado": {"mb_liberados": 500},
    }
    return rt


@pytest.fixture
def api_server(mock_runtime):
    token = "test-token-bloco2-12345678901234567890"
    server, origin_url = desktop_api.create_server(mock_runtime, token, host="127.0.0.1", port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server.server_address, token
    server.shutdown()
    server.server_close()


def test_get_bloco2_sucesso(api_server):
    addr, token = api_server
    conn = http.client.HTTPConnection(addr[0], addr[1])
    conn.request("GET", "/api/v1/bloco2", headers={
        "X-ULTRON-Token": token,
        "Host": f"{addr[0]}:{addr[1]}",
    })
    resp = conn.getresponse()
    assert resp.status == 200
    dados = json.loads(resp.read().decode())
    assert dados["admin_mode"] is True
    assert dados["config"]["suspensao_abas_ativo"] is True
    conn.close()


def test_post_bloco2_config(api_server):
    addr, token = api_server
    conn = http.client.HTTPConnection(addr[0], addr[1])
    payload = json.dumps({"suspensao_abas_limite_mb": 600})
    conn.request("POST", "/api/v1/bloco2", body=payload, headers={
        "X-ULTRON-Token": token,
        "Host": f"{addr[0]}:{addr[1]}",
        "Content-Type": "application/json",
    })
    resp = conn.getresponse()
    assert resp.status == 200
    dados = json.loads(resp.read().decode())
    assert dados["sucesso"] is True
    assert dados["config"]["suspensao_abas_limite_mb"] == 600
    conn.close()


def test_post_bloco2_executar(api_server):
    addr, token = api_server
    conn = http.client.HTTPConnection(addr[0], addr[1])
    payload = json.dumps({"acao": "limpar_ram", "params": {"agressivo": False}})
    conn.request("POST", "/api/v1/bloco2/executar", body=payload, headers={
        "X-ULTRON-Token": token,
        "Host": f"{addr[0]}:{addr[1]}",
        "Content-Type": "application/json",
    })
    resp = conn.getresponse()
    assert resp.status == 200
    dados = json.loads(resp.read().decode())
    assert dados["sucesso"] is True
    assert dados["resultado"]["mb_liberados"] == 500
    conn.close()


def test_bloco2_integracao_com_runtime_real(tmp_path, monkeypatch):
    """Integração sem mock do runtime: desktop_api -> DesktopRuntime -> processos_ops."""
    import processos_ops
    from desktop_runtime import DesktopRuntime

    monkeypatch.setattr(processos_ops, "DADOS_DIR", tmp_path)
    monkeypatch.setattr(processos_ops, "ARQUIVO_CONFIG", tmp_path / "bloco2.json")

    rt = DesktopRuntime(start_voice=False)
    token = "test-token-bloco2-real-1234567890123456"
    server, _origin = desktop_api.create_server(rt, token, host="127.0.0.1", port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        addr = server.server_address
        conn = http.client.HTTPConnection(addr[0], addr[1])
        headers = {
            "X-ULTRON-Token": token,
            "Host": f"{addr[0]}:{addr[1]}",
            "Content-Type": "application/json",
        }
        conn.request("POST", "/api/v1/bloco2", body=json.dumps({"suspensao_abas_limite_mb": 640}), headers=headers)
        resp = conn.getresponse()
        assert resp.status == 200
        saved = json.loads(resp.read().decode())
        assert saved["sucesso"] is True
        assert saved["config"]["suspensao_abas_limite_mb"] == 640

        conn.request("GET", "/api/v1/bloco2", headers=headers)
        resp2 = conn.getresponse()
        assert resp2.status == 200
        loaded = json.loads(resp2.read().decode())
        assert loaded["config"]["suspensao_abas_limite_mb"] == 640
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
