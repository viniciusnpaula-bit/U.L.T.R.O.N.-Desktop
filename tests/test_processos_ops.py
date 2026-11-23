"""Testes unitários para processos_ops.py (Bloco 2: Processos e RAM)."""
import os
import pytest
from unittest.mock import MagicMock, patch

import processos_ops


def test_eh_processo_protegido():
    # PID 0 e 4 (System) e o próprio processo devem estar sempre protegidos
    assert processos_ops.eh_processo_protegido(0) is True
    assert processos_ops.eh_processo_protegido(4) is True
    assert processos_ops.eh_processo_protegido(os.getpid()) is True
    assert processos_ops.eh_processo_protegido(999999, "csrss.exe") is True
    assert processos_ops.eh_processo_protegido(999999, "explorer.exe") is True
    assert processos_ops.eh_processo_protegido(999999, "lsass.exe") is True
    # Processo de usuário comum não deve estar protegido
    assert processos_ops.eh_processo_protegido(88888, "notepad.exe") is False
    assert processos_ops.eh_processo_protegido(88888, "chrome.exe") is False


def test_suspender_abas_pesadas_simulacao():
    # Mocking psutil.process_iter com renderers de teste
    mock_p1 = MagicMock()
    mock_p1.pid = 10101
    mock_p1.name.return_value = "chrome.exe"
    mock_p1.cmdline.return_value = ["chrome.exe", "--type=renderer", "--lang=pt-BR"]
    mock_p1.memory_info.return_value = MagicMock(rss=600 * 1024 * 1024)  # 600 MB

    mock_p2 = MagicMock()
    mock_p2.pid = 10102
    mock_p2.name.return_value = "msedge.exe"
    mock_p2.cmdline.return_value = ["msedge.exe", "--type=renderer"]
    mock_p2.memory_info.return_value = MagicMock(rss=300 * 1024 * 1024)  # 300 MB (abaixo)

    with patch("processos_ops.psutil.process_iter", return_value=[mock_p1, mock_p2]), \
         patch("processos_ops._esta_reproduzindo_audio", return_value=False), \
         patch("processos_ops._obter_pid_janela_ativa", return_value=9999):
        
        res = processos_ops.suspender_abas_pesadas(limite_mb=500, simular=True)
        assert res["candidatos"] == 1
        assert res["suspensos"] == 1
        assert res["detalhes"][0]["pid"] == 10101
        assert res["mb_economizados"] >= 600


def test_suspender_abas_pesadas_ignora_audio():
    mock_p = MagicMock()
    mock_p.pid = 20202
    mock_p.name.return_value = "chrome.exe"
    mock_p.cmdline.return_value = ["chrome.exe", "--type=renderer"]
    mock_p.memory_info.return_value = MagicMock(rss=700 * 1024 * 1024)

    with patch("processos_ops.psutil.process_iter", return_value=[mock_p]), \
         patch("processos_ops._esta_reproduzindo_audio", return_value=True), \
         patch("processos_ops._obter_pid_janela_ativa", return_value=9999):
        
        res = processos_ops.suspender_abas_pesadas(limite_mb=500, simular=True)
        assert res["candidatos"] == 0
        assert res["suspensos"] == 0


def test_encerrar_processos_travados_bloqueia_processos_do_sistema():
    # Janela do Explorer travada não pode ser morta
    with patch("processos_ops._listar_janelas_travadas", return_value=[
        {"hwnd": 1234, "pid": 4321, "titulo": "Windows Explorer", "exe": "explorer.exe"},
        {"hwnd": 5678, "pid": 8765, "titulo": "App Travado", "exe": "badapp.exe"}
    ]), patch("processos_ops._encerrar_pid", return_value=True) as mock_kill:
        
        res = processos_ops.encerrar_processos_travados(matar=True)
        assert res["encontrados"] == 2
        assert res["encerrados"] == 1  # Apenas badapp.exe
        assert res["ignorados_protegidos"] == 1
        mock_kill.assert_called_once_with(8765)


def test_otimizar_janela_ativa():
    with patch("processos_ops._obter_pid_janela_ativa", return_value=12345), \
         patch("processos_ops._obter_nome_processo", return_value="code.exe"), \
         patch("processos_ops._definir_prioridade_e_afinidade", return_value=True) as mock_set:
        
        res = processos_ops.otimizar_janela_ativa(aplicar=True)
        assert res["sucesso"] is True
        assert res["pid_ativo"] == 12345
        assert res["exe"] == "code.exe"
        mock_set.assert_called_once()


def test_limpar_ram_ociosa():
    mock_mem_antes = MagicMock(available=2 * 1024 * 1024 * 1024)
    mock_mem_depois = MagicMock(available=2.5 * 1024 * 1024 * 1024)

    mock_proc = MagicMock()
    mock_proc.pid = 55555
    mock_proc.name.return_value = "slack.exe"

    with patch("processos_ops.psutil.virtual_memory", side_effect=[mock_mem_antes, mock_mem_depois]), \
         patch("processos_ops.psutil.process_iter", return_value=[mock_proc]), \
         patch("processos_ops._esvaziar_working_set", return_value=True) as mock_empty:
        
        res = processos_ops.limpar_ram_ociosa(agressivo=False)
        assert res["sucesso"] is True
        assert res["processos_limpos"] == 1
        assert res["mb_liberados"] >= 500
        mock_empty.assert_called_once_with(55555)


def test_gerenciar_plano_energia_auto_compilacao():
    with patch("processos_ops.carregar_estado_bloco2", return_value={}), \
         patch("processos_ops.salvar_estado_bloco2"), \
         patch("processos_ops._obter_plano_energia_ativo", return_value=processos_ops.GUID_EQUILIBRADO), \
         patch("processos_ops._detectar_processos_pesados", return_value=["msbuild.exe"]), \
         patch("processos_ops._aplicar_plano_energia", return_value=True) as mock_apply:
        
        res = processos_ops.gerenciar_plano_energia(modo="auto")
        assert res["sucesso"] is True
        assert res["modo"] == "desempenho"
        assert "msbuild.exe" in res["gatilhos"]
        mock_apply.assert_called_once()


def test_gerenciar_plano_energia_silencioso_leitura():
    with patch("processos_ops._detectar_processos_pesados", return_value=[]), \
         patch("processos_ops._detectar_modo_leitura", return_value=True), \
         patch("processos_ops._aplicar_plano_energia", return_value=True) as mock_apply:
        
        res = processos_ops.gerenciar_plano_energia(modo="auto")
        assert res["sucesso"] is True
        assert res["modo"] == "silencioso"
        mock_apply.assert_called_once()


def test_otimizar_cpu_foco_em_reuniao():
    mock_indexer = MagicMock()
    mock_indexer.pid = 7777
    mock_indexer.name.return_value = "SearchIndexer.exe"

    with patch("processos_ops._esta_em_reuniao_ou_jogo", return_value=True), \
         patch("processos_ops.psutil.process_iter", return_value=[mock_indexer]), \
         patch("processos_ops._definir_prioridade_e_afinidade", return_value=True) as mock_set:
        
        res = processos_ops.otimizar_cpu_foco(em_reuniao_ou_jogo=None, aplicar=True)
        assert res["sucesso"] is True
        assert res["em_reuniao_ou_jogo"] is True
        assert res["processos_otimizados"] == 1
        mock_set.assert_called_once()


def test_proteger_temperatura_risco_throttling():
    mock_proc = MagicMock()
    mock_proc.pid = 8888
    mock_proc.name.return_value = "background_miner.exe"
    mock_proc.cpu_percent.return_value = 45.0

    with patch("processos_ops._obter_temperatura_cpu", return_value=89.5), \
         patch("processos_ops.psutil.process_iter", return_value=[mock_proc]), \
         patch("processos_ops._obter_pid_janela_ativa", return_value=1234), \
         patch("processos_ops._definir_prioridade_e_afinidade", return_value=True) as mock_set:
        
        res = processos_ops.proteger_temperatura(limite_celsius=82, simular=False)
        assert res["sucesso"] is True
        assert res["temperatura"] == 89.5
        assert res["risco_throttling"] is True
        assert res["processos_limitados"] == 1
        mock_set.assert_called_once()


def test_guardiao_startup_auditar_novo_item(tmp_path):
    mock_itens = [
        {"nome": "Discord", "comando": "C:\\Discord.exe", "local": "HKCU_Run"},
        {"nome": "SuspiciousApp", "comando": "C:\\Temp\\evil.exe", "local": "HKLM_Run"},
    ]
    with patch("processos_ops._listar_itens_startup", return_value=mock_itens), \
         patch("processos_ops.ARQUIVO_STARTUP", tmp_path / "bloco2_startup.json"):
        
        # Primeira auditoria: ambos são novos
        res = processos_ops.guardiao_startup(acao="auditar")
        assert res["sucesso"] is True
        assert len(res["itens"]) == 2
        assert res["novos_infiltrados"] == 2


def test_guardiao_startup_aprovar_item(tmp_path):
    mock_itens = [{"nome": "Discord", "comando": "C:\\Discord.exe", "local": "HKCU_Run"}]
    with patch("processos_ops._listar_itens_startup", return_value=mock_itens), \
         patch("processos_ops.ARQUIVO_STARTUP", tmp_path / "bloco2_startup.json"):
        
        processos_ops.guardiao_startup(acao="auditar")
        res_aprov = processos_ops.guardiao_startup(acao="aprovar", item="Discord")
        assert res_aprov["sucesso"] is True
        assert "Discord" in res_aprov["aprovados"]

        # Segunda auditoria: agora novos_infiltrados deve ser 0
        res2 = processos_ops.guardiao_startup(acao="auditar")
        assert res2["novos_infiltrados"] == 0


def test_ajustar_display_auto():
    with patch("processos_ops._definir_brilho", return_value=True) as mock_brilho, \
         patch("processos_ops._definir_temperatura_gama", return_value=True) as mock_gama, \
         patch("processos_ops._definir_taxa_atualizacao", return_value=True):
        
        res = processos_ops.ajustar_display(modo="auto")
        assert res["sucesso"] is True
        assert res["brilho"] >= 20
        assert res["temperatura_k"] >= 2700
        mock_brilho.assert_called_once()
        mock_gama.assert_called_once()


def test_desconectar_bluetooth_ocioso():
    mock_dispositivos = [
        {"id": "DEV_01", "nome": "Headset BT", "conectado": True, "minutos_sem_audio": 12},
        {"id": "DEV_02", "nome": "Mouse BT", "conectado": True, "minutos_sem_audio": 0},
    ]
    with patch("processos_ops._listar_dispositivos_bluetooth", return_value=mock_dispositivos), \
         patch("processos_ops._desconectar_dispositivo_bt", return_value=True) as mock_disc:
        
        res = processos_ops.desconectar_bluetooth_ocioso(minutos_ocioso=5, executar=True)
        assert res["sucesso"] is True
        assert res["ociosos_desconectados"] == 1
        assert res["detalhes"][0]["id"] == "DEV_01"
        mock_disc.assert_called_once_with("DEV_01")


def test_config_bloco2_carregar_salvar(tmp_path):
    with patch("processos_ops.ARQUIVO_CONFIG", tmp_path / "bloco2.json"):
        cfg = processos_ops.carregar_config_bloco2()
        assert cfg["suspensao_abas_ativo"] is True
        assert cfg["suspensao_abas_limite_mb"] == 500

        nova = processos_ops.salvar_config_bloco2({"suspensao_abas_limite_mb": 750})
        assert nova["suspensao_abas_limite_mb"] == 750
        assert processos_ops.carregar_config_bloco2()["suspensao_abas_limite_mb"] == 750


def test_esta_reproduzindo_audio_nao_retorna_falso_por_primeira_amostra_zero():
    proc = MagicMock()
    proc.pid = 42424
    proc.create_time.return_value = 12345.0
    proc.cpu_percent.side_effect = [0.0, 22.5]

    processos_ops._CPU_PROCS.clear()
    with patch("processos_ops.psutil.Process", return_value=proc), \
         patch("processos_ops.time.sleep", return_value=None):
        assert processos_ops._esta_reproduzindo_audio(42424) is True


def test_listar_bluetooth_nao_fabrica_inatividade_para_desconectar_ativos():
    fake_proc = MagicMock(returncode=0, stdout='[{"InstanceId": "BTH\\\\DEV_1", "FriendlyName": "Teclado BT"}]')
    with patch("os.name", "nt"), \
         patch("subprocess.run", return_value=fake_proc):
        dispositivos = processos_ops._listar_dispositivos_bluetooth()
    assert len(dispositivos) == 1
    assert dispositivos[0]["minutos_sem_audio"] == 0
    assert dispositivos[0]["idle_medido"] is False

    with patch("processos_ops._listar_dispositivos_bluetooth", return_value=dispositivos), \
         patch("processos_ops._desconectar_dispositivo_bt") as mock_disc:
        res = processos_ops.desconectar_bluetooth_ocioso(minutos_ocioso=0, executar=True)
    assert res["ociosos_desconectados"] == 0
    mock_disc.assert_not_called()


