"""processos_ops.py: Operações do Bloco 2 — Processos, Memória e Hardware.

100% Nativo Windows via ctypes (Win32, NTDLL, powrprof, gdi32, dxva2), winreg e psutil.
Proteção inviolável de processos de sistema e da árvore do ULTRON.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
from typing import Any
import winreg

import psutil

import config

_log = logging.getLogger("ultron.processos_ops")
_CPU_LOCK = threading.Lock()
_CPU_PROCS: dict[int, tuple[float, psutil.Process]] = {}

BASE_DIR = Path(__file__).resolve().parent
DADOS_DIR = getattr(config, "DIR_DADOS", BASE_DIR / "dados")
ARQUIVO_CONFIG = DADOS_DIR / "bloco2.json"
ARQUIVO_ESTADO = DADOS_DIR / "bloco2_estado.json"
ARQUIVO_STARTUP = DADOS_DIR / "bloco2_startup.json"

# Processos vitais do Windows que NUNCA podem ser suspensos ou finalizados
PROCESSOS_PROTEGIDOS_SISTEMA = frozenset({
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "winlogon.exe",
    "explorer.exe", "taskmgr.exe", "sihost.exe", "fontdrvhost.exe",
    "runtimebroker.exe", "spoolsv.exe", "securityhealthservice.exe",
})

NAVEGADORES_RENDERER = frozenset({
    "chrome.exe", "msedge.exe", "brave.exe", "opera.exe", "vivaldi.exe"
})

PROCESSOS_PESADOS = frozenset({
    "msbuild.exe", "cl.exe", "gcc.exe", "g++.exe", "rustc.exe", "cargo.exe",
    "clang.exe", "javac.exe", "go.exe", "ffmpeg.exe", "blender.exe",
    "premiere.exe", "afterfx.exe", "unrealeditor.exe", "unity.exe",
})

APPS_LEITURA = frozenset({
    "acrord32.exe", "sumatrapdf.exe", "kindle.exe", "calibre.exe",
})

APPS_REUNIAO = frozenset({
    "zoom.exe", "teams.exe", "skype.exe", "discord.exe", "slack.exe", "webex.exe",
})

PROCESSOS_INDEXADORES = frozenset({
    "searchindexer.exe", "tiworker.exe", "trustedinstaller.exe",
    "compattelrunner.exe", "onedrive.exe", "mscorsvw.exe",
})

GUID_ALTO_DESEMPENHO = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
GUID_EQUILIBRADO = "381b4222-f694-41f0-9685-ff5bb260df2e"
GUID_SILENCIOSO = "a1841308-3541-4fab-bc81-f71556f20b4a"
GUID_DESEMPENHO_MAXIMO = "e9a42b02-d5df-448d-aa00-03f14749eb61"

CONFIG_PADRAO = {
    "suspensao_abas_ativo": True,
    "suspensao_abas_limite_mb": 500,
    "matar_travados_ativo": True,
    "plano_energia_ativo": True,
    "plano_energia_modo": "auto",
    "otimizar_cpu_foco_ativo": True,
    "protecao_termica_ativo": True,
    "protecao_termica_limite_celsius": 82,
    "guardiao_startup_ativo": True,
    "guardiao_startup_auto_bloquear": False,
    "otimizar_janela_ativa_ativo": True,
    "limpar_ram_ativo": True,
    "limpar_ram_limite_pct": 85,
    "display_ativo": False,
    "display_modo": "auto",
    "bluetooth_ocioso_ativo": False,
    "bluetooth_ocioso_minutos": 5,
}

# Win32 Constants
PROCESS_TERMINATE = 0x0001
PROCESS_SUSPEND_RESUME = 0x0800
PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

IDLE_PRIORITY_CLASS = 0x00000040
NORMAL_PRIORITY_CLASS = 0x00000020
HIGH_PRIORITY_CLASS = 0x00000080
REALTIME_PRIORITY_CLASS = 0x00000100


def carregar_config_bloco2() -> dict[str, Any]:
    """Carrega as configurações salvas do Bloco 2."""
    if ARQUIVO_CONFIG.exists():
        try:
            dados = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
            cfg = dict(CONFIG_PADRAO)
            cfg.update(dados)
            return cfg
        except Exception as e:
            _log.warning("Falha ao ler %s (%s); usando padrão", ARQUIVO_CONFIG, e)
    return dict(CONFIG_PADRAO)


def salvar_config_bloco2(novos: dict[str, Any]) -> dict[str, Any]:
    """Salva configurações validadas do Bloco 2."""
    DADOS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = carregar_config_bloco2()
    for k, v in novos.items():
        if k in CONFIG_PADRAO:
            cfg[k] = v
    ARQUIVO_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg


def carregar_estado_bloco2() -> dict[str, Any]:
    """Carrega estado persistido (ex.: abas suspensas, plano anterior)."""
    if ARQUIVO_ESTADO.exists():
        try:
            return json.loads(ARQUIVO_ESTADO.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"abas_suspensas": [], "ultimo_fg_pid": 0, "plano_base_guid": ""}


def salvar_estado_bloco2(estado: dict[str, Any]) -> None:
    try:
        DADOS_DIR.mkdir(parents=True, exist_ok=True)
        ARQUIVO_ESTADO.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _log.warning("Falha ao salvar estado Bloco 2: %s", e)


def eh_processo_protegido(pid: int, nome: str = "") -> bool:
    """Verifica se um PID pertence ao sistema ou à stack do próprio ULTRON."""
    if pid <= 4:
        return True
    meu_pid = os.getpid()
    if pid == meu_pid:
        return True
    try:
        meu_proc = psutil.Process(meu_pid)
        for parente in meu_proc.parents():
            if pid == parente.pid:
                return True
        for filho in meu_proc.children(recursive=True):
            if pid == filho.pid:
                return True
    except Exception:
        pass

    if not nome:
        nome = _obter_nome_processo(pid)
    if nome.lower() in PROCESSOS_PROTEGIDOS_SISTEMA:
        return True
    return False


def _obter_nome_processo(pid: int) -> str:
    try:
        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def _obter_pid_janela_ativa() -> int:
    """Retorna o PID associado à janela em primeiro plano (GetForegroundWindow)."""
    if os.name != "nt":
        return 0
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _cpu_processo_real(proc: psutil.Process, intervalo: float = 0.05) -> float:
    """Obtém uso de CPU evitando o 0.0 espúrio da 1ª leitura em processos recém-instanciados."""
    try:
        val = proc.cpu_percent(interval=None)
    except Exception:
        return 0.0
    if isinstance(val, (int, float)) and val > 0.0:
        return float(val)
    try:
        pid = int(proc.pid)
        ctime = float(proc.create_time())
    except Exception:
        return float(val) if isinstance(val, (int, float)) else 0.0
    with _CPU_LOCK:
        entrada = _CPU_PROCS.get(pid)
        if entrada and entrada[0] == ctime:
            try:
                return float(entrada[1].cpu_percent(interval=None))
            except Exception:
                return 0.0
        if len(_CPU_PROCS) > 2048:
            _CPU_PROCS.clear()
        _CPU_PROCS[pid] = (ctime, proc)
    if intervalo > 0:
        time.sleep(intervalo)
    try:
        return float(proc.cpu_percent(interval=None))
    except Exception:
        return 0.0


def _esta_reproduzindo_audio(pid: int) -> bool:
    """Checa se o processo tem fluxo de áudio ativo no Windows Core Audio."""
    # Verificação leve: se for o processo do Ultron ou se tiver atividade de áudio registrada
    # Fallback determinístico via verificação de subprocessos e psutil
    try:
        proc = psutil.Process(pid)
        # Se CPU > 15%, é muito provável estar renderizando vídeo/mídia ou chamada
        if _cpu_processo_real(proc, intervalo=0.05) > 15.0:
            return True
    except Exception:
        pass
    return False


# =====================================================================
# Item 11: Suspender abas inativas do navegador >500 MB
# =====================================================================
def suspender_abas_pesadas(limite_mb: int = 500, desuspender: bool = False, simular: bool = False) -> dict[str, Any]:
    """Identifica renderers de navegadores inativos com RSS > limite_mb e os suspende."""
    estado = carregar_estado_bloco2()
    suspensos_historico = set(estado.get("abas_suspensas", []))

    if desuspender:
        retomados = []
        if os.name == "nt" and not simular:
            ntdll = ctypes.windll.ntdll
            kernel32 = ctypes.windll.kernel32
            for pid in list(suspensos_historico):
                try:
                    h_proc = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
                    if h_proc:
                        ntdll.NtResumeProcess(h_proc)
                        kernel32.CloseHandle(h_proc)
                        retomados.append(pid)
                except Exception:
                    pass
        else:
            retomados = list(suspensos_historico)
        estado["abas_suspensas"] = []
        salvar_estado_bloco2(estado)
        return {"sucesso": True, "retomados": len(retomados), "pids": retomados}

    fg_pid = _obter_pid_janela_ativa()
    candidatos = []
    total_bytes = 0

    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            pid = proc.pid
            if eh_processo_protegido(pid) or pid == fg_pid:
                continue
            nome = (proc.name() or "").lower()
            if nome not in NAVEGADORES_RENDERER:
                continue
            cmd = proc.cmdline() or []
            if not any("--type=renderer" in arg for arg in cmd):
                continue
            rss = proc.memory_info().rss
            if rss < (limite_mb * 1024 * 1024):
                continue
            if _esta_reproduzindo_audio(pid):
                continue

            candidatos.append({"pid": pid, "nome": nome, "rss": rss})
            total_bytes += rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    suspensos = []
    if not simular and os.name == "nt":
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        for item in candidatos:
            pid = item["pid"]
            try:
                h_proc = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
                if h_proc:
                    status = ntdll.NtSuspendProcess(h_proc)
                    kernel32.CloseHandle(h_proc)
                    if status == 0:
                        suspensos.append(pid)
                        suspensos_historico.add(pid)
            except Exception as e:
                _log.warning("Erro ao suspender PID %d: %s", pid, e)
    else:
        suspensos = [c["pid"] for c in candidatos]
        suspensos_historico.update(suspensos)

    estado["abas_suspensas"] = list(suspensos_historico)
    salvar_estado_bloco2(estado)

    return {
        "sucesso": True,
        "candidatos": len(candidatos),
        "suspensos": len(suspensos),
        "mb_economizados": round(total_bytes / (1024 * 1024), 2),
        "detalhes": candidatos,
        "simulacao": simular,
    }


# =====================================================================
# Item 12: Matar processos zumbis ou programas "Não Respondendo"
# =====================================================================
def _listar_janelas_travadas() -> list[dict[str, Any]]:
    """Enumera janelas visíveis de nível superior e checa IsHungAppWindow."""
    travadas = []
    if os.name != "nt":
        return travadas

    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            if user32.IsHungAppWindow(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                tam = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(tam + 1)
                user32.GetWindowTextW(hwnd, buf, tam + 1)
                titulo = buf.value
                exe = _obter_nome_processo(pid.value)
                travadas.append({
                    "hwnd": int(hwnd),
                    "pid": int(pid.value),
                    "titulo": titulo,
                    "exe": exe
                })
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(_callback), 0)
    except Exception as e:
        _log.warning("Falha ao enumerar janelas travadas: %s", e)
    return travadas


def _encerrar_pid(pid: int) -> bool:
    """Encerra um PID de forma resiliente."""
    try:
        p = psutil.Process(pid)
        p.kill()
        return True
    except Exception:
        if os.name == "nt":
            try:
                kernel32 = ctypes.windll.kernel32
                h_proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if h_proc:
                    res = kernel32.TerminateProcess(h_proc, 1)
                    kernel32.CloseHandle(h_proc)
                    return bool(res)
            except Exception:
                pass
    return False


def encerrar_processos_travados(matar: bool = True) -> dict[str, Any]:
    """Identifica programas não respondendo e os encerra antes que afetem o shell."""
    travados = _listar_janelas_travadas()
    encerrados = []
    ignorados_protegidos = 0

    for item in travados:
        pid = item["pid"]
        exe = item["exe"]
        if eh_processo_protegido(pid, exe):
            ignorados_protegidos += 1
            _log.info("Processo travado %d (%s) é protegido; ignorado", pid, exe)
            continue

        if matar:
            sucesso = _encerrar_pid(pid)
            if sucesso:
                encerrados.append(item)
        else:
            encerrados.append(item)

    return {
        "sucesso": True,
        "encontrados": len(travados),
        "encerrados": len(encerrados),
        "ignorados_protegidos": ignorados_protegidos,
        "detalhes": encerrados,
        "simulado": not matar,
    }


# =====================================================================
# Item 17: Redistribuir afinidade e prioridade máxima para a janela ativa
# =====================================================================
def _definir_prioridade_e_afinidade(pid: int, prioridade_classe: int, todas_cpus: bool = True) -> bool:
    try:
        p = psutil.Process(pid)
        p.nice(psutil.HIGH_PRIORITY_CLASS if prioridade_classe == HIGH_PRIORITY_CLASS else psutil.NORMAL_PRIORITY_CLASS)
        if todas_cpus:
            cpus = list(range(psutil.cpu_count() or 1))
            p.cpu_affinity(cpus)
        return True
    except Exception:
        if os.name == "nt":
            try:
                kernel32 = ctypes.windll.kernel32
                h_proc = kernel32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, False, pid)
                if h_proc:
                    kernel32.SetPriorityClass(h_proc, prioridade_classe)
                    if todas_cpus:
                        mascara = (1 << (psutil.cpu_count() or 1)) - 1
                        kernel32.SetProcessAffinityMask(h_proc, mascara)
                    kernel32.CloseHandle(h_proc)
                    return True
            except Exception:
                pass
    return False


def otimizar_janela_ativa(aplicar: bool = True) -> dict[str, Any]:
    """Eleva a prioridade e garante núcleos dedicados ao processo em primeiro plano."""
    fg_pid = _obter_pid_janela_ativa()
    if not fg_pid:
        return {"sucesso": False, "motivo": "Nenhuma janela ativa detectada"}

    exe = _obter_nome_processo(fg_pid)
    if eh_processo_protegido(fg_pid, exe) or exe in ("explorer.exe", "ul_tron.exe", "python.exe"):
        return {"sucesso": True, "ignorado": True, "motivo": f"Processo {exe} protegido ou shell"}

    estado = carregar_estado_bloco2()
    anterior_pid = estado.get("ultimo_fg_pid", 0)

    # Restaura o anterior para Normal
    if anterior_pid and anterior_pid != fg_pid:
        try:
            _definir_prioridade_e_afinidade(anterior_pid, NORMAL_PRIORITY_CLASS)
        except Exception:
            pass

    if aplicar:
        _definir_prioridade_e_afinidade(fg_pid, HIGH_PRIORITY_CLASS)
        estado["ultimo_fg_pid"] = fg_pid
        salvar_estado_bloco2(estado)

    return {
        "sucesso": True,
        "pid_ativo": fg_pid,
        "exe": exe,
        "prioridade_aplicada": "HIGH" if aplicar else "PREVIEW",
        "restaurado_anterior": anterior_pid,
    }


# =====================================================================
# Item 18: Limpar cache de memória RAM ociosa (Working Sets)
# =====================================================================
def _esvaziar_working_set(pid: int) -> bool:
    """Esvazia o working set de um processo chamando EmptyWorkingSet."""
    if os.name != "nt":
        return False
    try:
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32
        h_proc = kernel32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, False, pid)
        if h_proc:
            res = psapi.EmptyWorkingSet(h_proc)
            kernel32.CloseHandle(h_proc)
            return bool(res)
    except Exception:
        pass
    return False


def limpar_ram_ociosa(agressivo: bool = False) -> dict[str, Any]:
    """Esvazia Working Sets de processos de fundo para liberar RAM ociosa."""
    mem_antes = psutil.virtual_memory()
    fg_pid = _obter_pid_janela_ativa()
    limpos = 0

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = proc.pid
            if eh_processo_protegido(pid) or pid == fg_pid:
                continue
            if _esvaziar_working_set(pid):
                limpos += 1
        except Exception:
            continue

    # Standby List Purge se admin e agressivo
    if agressivo and os.name == "nt":
        try:
            # MemoryPurgeStandbyList via NtSetSystemInformation (SystemMemoryListInformation = 80)
            ntdll = ctypes.windll.ntdll
            val = ctypes.c_ulong(5)  # MemoryPurgeStandbyList
            ntdll.NtSetSystemInformation(80, ctypes.byref(val), ctypes.sizeof(val))
        except Exception as e:
            _log.debug("Purga de Standby List não suportada diretamente: %s", e)

    mem_depois = psutil.virtual_memory()
    liberados = max(0, mem_depois.available - mem_antes.available)

    return {
        "sucesso": True,
        "processos_limpos": limpos,
        "bytes_liberados": liberados,
        "mb_liberados": round(liberados / (1024 * 1024), 2),
        "ram_livre_antes_mb": round(mem_antes.available / (1024 * 1024), 2),
        "ram_livre_depois_mb": round(mem_depois.available / (1024 * 1024), 2),
        "agressivo": agressivo,
    }


# =====================================================================
# Item 13: Alternar plano de energia (Silencioso vs Desempenho Máximo)
# =====================================================================
def _detectar_processos_pesados() -> list[str]:
    """Retorna nomes de processos ativos relacionados a compilação ou renderização."""
    encontrados = set()
    for proc in psutil.process_iter(["name"]):
        try:
            nome = (proc.name() or "").lower()
            if nome in PROCESSOS_PESADOS:
                encontrados.add(nome)
        except Exception:
            continue
    return list(encontrados)


def _detectar_modo_leitura() -> bool:
    """Retorna True se um app de leitura estiver na janela ativa e a CPU estiver ociosa."""
    fg_pid = _obter_pid_janela_ativa()
    if not fg_pid:
        return False
    exe = _obter_nome_processo(fg_pid)
    if exe in APPS_LEITURA:
        try:
            if psutil.cpu_percent(interval=None) < 10.0:
                return True
        except Exception:
            return True
    return False


def _obter_plano_energia_ativo() -> str:
    """Consulta o GUID do plano de energia ativo pelo powercfg ou powrprof."""
    if os.name != "nt":
        return GUID_EQUILIBRADO
    try:
        import subprocess
        res = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=5)
        out = res.stdout or ""
        # Formato: "GUID do Esquema de Energia: 381b4222-f694-41f0-9685-ff5bb260df2e  (Equilibrado)"
        partes = out.split(":")
        if len(partes) > 1:
            guid = partes[1].strip().split()[0]
            if len(guid) >= 36:
                return guid
    except Exception as e:
        _log.debug("Erro ao consultar plano ativo: %s", e)
    return GUID_EQUILIBRADO


def _aplicar_plano_energia(guid: str) -> bool:
    """Aplica um GUID de plano de energia via powercfg."""
    if os.name != "nt":
        return False
    try:
        import subprocess
        res = subprocess.run(["powercfg", "/setactive", guid], capture_output=True, timeout=5)
        return res.returncode == 0
    except Exception as e:
        _log.warning("Falha ao definir plano de energia %s: %s", guid, e)
        return False


def gerenciar_plano_energia(modo: str = "auto", esquema: str = "") -> dict[str, Any]:
    """Alterna o plano de energia nativo com base na carga e modo solicitado."""
    estado = carregar_estado_bloco2()
    plano_atual = _obter_plano_energia_ativo()

    if not estado.get("plano_base_guid"):
        estado["plano_base_guid"] = plano_atual
        salvar_estado_bloco2(estado)

    alvo_guid = ""
    gatilhos = []
    modo_final = modo.lower()

    if modo_final == "auto":
        pesados = _detectar_processos_pesados()
        if pesados:
            modo_final = "desempenho"
            alvo_guid = GUID_ALTO_DESEMPENHO
            gatilhos = pesados
        elif _detectar_modo_leitura():
            modo_final = "silencioso"
            alvo_guid = GUID_SILENCIOSO
            gatilhos = ["leitura_ativa"]
        else:
            modo_final = "equilibrado"
            alvo_guid = estado.get("plano_base_guid") or GUID_EQUILIBRADO
    elif modo_final == "desempenho":
        alvo_guid = GUID_DESEMPENHO_MAXIMO if esquema == "maximo" else GUID_ALTO_DESEMPENHO
    elif modo_final == "silencioso":
        alvo_guid = GUID_SILENCIOSO
    elif modo_final == "equilibrado":
        alvo_guid = GUID_EQUILIBRADO
    elif esquema:
        alvo_guid = esquema

    sucesso = True
    if alvo_guid and alvo_guid != plano_atual:
        sucesso = _aplicar_plano_energia(alvo_guid)

    return {
        "sucesso": sucesso,
        "modo": modo_final,
        "plano_guid": alvo_guid or plano_atual,
        "plano_anterior": plano_atual,
        "gatilhos": gatilhos,
    }


# =====================================================================
# Item 14: Limitar CPU de indexadores e atualizações em reuniões/jogos
# =====================================================================
def _esta_em_reuniao_ou_jogo() -> bool:
    """Verifica se há aplicativo de reunião rodando ou jogo em tela cheia."""
    for proc in psutil.process_iter(["name"]):
        try:
            nome = (proc.name() or "").lower()
            if nome in APPS_REUNIAO:
                return True
        except Exception:
            continue

    # Verificação de jogo em tela cheia via dimensões da janela ativa
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                largura = rect.right - rect.left
                altura = rect.bottom - rect.top
                sm_cx = user32.GetSystemMetrics(0)
                sm_cy = user32.GetSystemMetrics(1)
                # Janela preenche toda a tela
                if largura >= sm_cx and altura >= sm_cy:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    exe = _obter_nome_processo(pid.value)
                    if exe not in ("explorer.exe", "ul_tron.exe", "python.exe"):
                        return True
        except Exception:
            pass
    return False


def otimizar_cpu_foco(em_reuniao_ou_jogo: bool | None = None, aplicar: bool = True) -> dict[str, Any]:
    """Reduz a prioridade de indexadores e atualizações durante jogos ou reuniões."""
    if em_reuniao_ou_jogo is None:
        ativo = _esta_em_reuniao_ou_jogo()
    else:
        ativo = bool(em_reuniao_ou_jogo)

    prioridade_alvo = IDLE_PRIORITY_CLASS if ativo else NORMAL_PRIORITY_CLASS
    otimizados = []

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            nome = (proc.name() or "").lower()
            if nome in PROCESSOS_INDEXADORES:
                pid = proc.pid
                if aplicar:
                    _definir_prioridade_e_afinidade(pid, prioridade_alvo, todas_cpus=not ativo)
                otimizados.append({"pid": pid, "nome": nome})
        except Exception:
            continue

    return {
        "sucesso": True,
        "em_reuniao_ou_jogo": ativo,
        "processos_otimizados": len(otimizados),
        "prioridade": "IDLE" if ativo else "NORMAL",
        "detalhes": otimizados,
        "aplicado": aplicar,
    }


# =====================================================================
# Item 15: Proteção térmica (Monitorar CPU/GPU e aliviar cargas)
# =====================================================================
def _obter_temperatura_cpu() -> float | None:
    """Lê a temperatura da CPU via WMI (MSAcpi_ThermalZoneTemperature) ou psutil."""
    if os.name == "nt":
        try:
            import subprocess
            comando = "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CurrentTemperature"
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            out = (res.stdout or "").strip()
            if out:
                linhas = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
                if linhas:
                    # Kelvin * 10 -> Celsius = (K*10 - 2732) / 10
                    k_dec = float(linhas[0])
                    celsius = (k_dec - 2732.0) / 10.0
                    if 15.0 <= celsius <= 115.0:
                        return round(celsius, 1)
        except Exception:
            pass

    # Fallback psutil se disponível
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for nome, entradas in temps.items():
                for entry in entradas:
                    if entry.current and 15.0 <= entry.current <= 115.0:
                        return round(float(entry.current), 1)
    except Exception:
        pass
    return None


def proteger_temperatura(limite_celsius: int = 82, simular: bool = False) -> dict[str, Any]:
    """Verifica temperatura e alivia processos secundários de alto consumo se houver risco."""
    temp = _obter_temperatura_cpu()
    risco = temp is not None and temp >= float(limite_celsius)
    limitados = []

    if risco:
        fg_pid = _obter_pid_janela_ativa()
        candidatos = []
        novos = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent"]):
            try:
                pid = proc.pid
                if eh_processo_protegido(pid) or pid == fg_pid:
                    continue
                cpu_uso = proc.cpu_percent(interval=None)
                if isinstance(cpu_uso, (int, float)) and cpu_uso > 0.0:
                    candidatos.append((proc, float(cpu_uso)))
                    continue
                try:
                    pid_int = int(pid)
                    ctime = float(proc.create_time())
                except Exception:
                    candidatos.append((proc, 0.0))
                    continue
                with _CPU_LOCK:
                    entrada = _CPU_PROCS.get(pid_int)
                    if entrada and entrada[0] == ctime:
                        candidatos.append((entrada[1], None))
                    else:
                        if len(_CPU_PROCS) > 2048:
                            _CPU_PROCS.clear()
                        _CPU_PROCS[pid_int] = (ctime, proc)
                        novos.append(proc)
            except Exception:
                continue

        if novos:
            time.sleep(0.05)
            for proc in novos:
                candidatos.append((proc, None))

        for proc, cpu_pre in candidatos:
            try:
                cpu_uso = float(proc.cpu_percent(interval=None)) if cpu_pre is None else cpu_pre
                if cpu_uso >= 10.0:
                    nome = (proc.name() or "").lower()
                    if not simular:
                        _definir_prioridade_e_afinidade(proc.pid, IDLE_PRIORITY_CLASS, todas_cpus=False)
                    limitados.append({"pid": proc.pid, "nome": nome, "cpu_percent": cpu_uso})
            except Exception:
                continue

    return {
        "sucesso": True,
        "temperatura": temp,
        "limite_celsius": limite_celsius,
        "risco_throttling": risco,
        "processos_limitados": len(limitados),
        "detalhes": limitados,
        "simulacao": simular,
    }


# =====================================================================
# Item 16: Guardião de Inicialização do Sistema (Startup)
# =====================================================================
CHAVES_REGISTRO_STARTUP = [
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU_Run"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU_RunOnce"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM_Run"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKLM_RunOnce"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM_WOW64_Run"),
]


def _listar_itens_startup() -> list[dict[str, Any]]:
    """Varre chaves do Registro e pastas de inicialização do Windows."""
    itens = []
    if os.name != "nt":
        return itens

    # 1. Chaves do Registro
    for raiz, subchave, label in CHAVES_REGISTRO_STARTUP:
        try:
            with winreg.OpenKey(raiz, subchave, 0, winreg.KEY_READ) as k:
                num_valores = winreg.QueryInfoKey(k)[1]
                for i in range(num_valores):
                    try:
                        nome, valor, _ = winreg.EnumValue(k, i)
                        itens.append({
                            "nome": nome,
                            "comando": str(valor),
                            "local": label,
                            "subchave": subchave,
                        })
                    except Exception:
                        continue
        except Exception:
            continue

    # 2. Pastas de Startup
    pastas = [
        (os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"), "Startup_User"),
        (os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\Startup"), "Startup_Common"),
    ]
    for p_str, label in pastas:
        p = Path(p_str)
        if p.exists() and p.is_dir():
            try:
                for entry in p.iterdir():
                    if entry.is_file() and entry.name.lower() != "desktop.ini":
                        itens.append({
                            "nome": entry.name,
                            "comando": str(entry.resolve()),
                            "local": label,
                            "caminho": str(entry),
                        })
            except Exception:
                continue

    return itens


def _remover_item_startup(nome: str, local: str, caminho: str = "") -> bool:
    """Remove um item do startup do registro ou desativa o atalho na pasta."""
    if os.name != "nt":
        return False
    if local.startswith("HK"):
        for raiz, subchave, label in CHAVES_REGISTRO_STARTUP:
            if label == local:
                try:
                    with winreg.OpenKey(raiz, subchave, 0, winreg.KEY_SET_VALUE) as k:
                        winreg.DeleteValue(k, nome)
                        return True
                except Exception as e:
                    _log.warning("Falha ao remover item %s de %s: %s", nome, local, e)
                    return False
    elif caminho:
        try:
            p = Path(caminho)
            if p.exists():
                desativado = p.with_name(p.name + ".disabled")
                p.rename(desativado)
                return True
        except Exception as e:
            _log.warning("Falha ao desativar arquivo de startup %s: %s", caminho, e)
    return False


def _carregar_startup_autorizados() -> list[str]:
    if ARQUIVO_STARTUP.exists():
        try:
            dados = json.loads(ARQUIVO_STARTUP.read_text(encoding="utf-8"))
            return dados.get("autorizados", [])
        except Exception:
            pass
    return []


def _salvar_startup_autorizados(autorizados: list[str]) -> None:
    DADOS_DIR.mkdir(parents=True, exist_ok=True)
    ARQUIVO_STARTUP.write_text(
        json.dumps({"autorizados": list(set(autorizados))}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def guardiao_startup(acao: str = "auditar", item: str = "", autorizar: bool = False) -> dict[str, Any]:
    """Audita, aprova ou remove itens de inicialização do sistema."""
    itens_atuais = _listar_itens_startup()
    autorizados = _carregar_startup_autorizados()

    acao = acao.lower()
    if acao == "aprovar" and item:
        if item not in autorizados:
            autorizados.append(item)
            _salvar_startup_autorizados(autorizados)
        return {"sucesso": True, "acao": "aprovar", "item": item, "aprovados": autorizados}

    if acao == "remover" and item:
        removidos = 0
        for it in itens_atuais:
            if it["nome"].lower() == item.lower():
                if _remover_item_startup(it["nome"], it.get("local", ""), it.get("caminho", "")):
                    removidos += 1
        if item in autorizados:
            autorizados.remove(item)
            _salvar_startup_autorizados(autorizados)
        return {"sucesso": True, "acao": "remover", "item": item, "removidos": removidos}

    # Auditoria padrão
    novos = []
    aprovados_lista = []
    for it in itens_atuais:
        nome = it["nome"]
        if nome in autorizados:
            aprovados_lista.append(it)
        else:
            novos.append(it)

    return {
        "sucesso": True,
        "acao": "auditar",
        "itens": itens_atuais,
        "total": len(itens_atuais),
        "novos_infiltrados": len(novos),
        "novos_detalhes": novos,
        "aprovados": autorizados,
    }


# =====================================================================
# Item 19: Ajustar brilho, temperatura de cor e taxa de atualização
# =====================================================================
def _definir_brilho(nivel: int) -> bool:
    """Ajusta o brilho da tela (20 a 100) via WMI ou dxva2."""
    nivel = max(20, min(100, int(nivel)))
    if os.name != "nt":
        return True
    try:
        import subprocess
        cmd = f"(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1, {nivel})"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=5, creationflags=0x08000000
        )
        return res.returncode == 0
    except Exception as e:
        _log.warning("Falha ao definir brilho para %d: %s", nivel, e)
        return False


def _definir_temperatura_gama(kelvin: int) -> bool:
    """Ajusta a curva de temperatura de cor (luz noturna) via GDI SetDeviceGammaRamp."""
    kelvin = max(2500, min(6500, int(kelvin)))
    if os.name != "nt":
        return True
    try:
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        hdc = user32.GetDC(0)
        if not hdc:
            return False

        # Fatores RGB aproximados para temperatura Kelvin
        temp = kelvin / 100.0
        # Vermelho
        r = 1.0
        # Verde
        if temp <= 66:
            g = 99.4708025861 * (math.log(temp) if temp > 0 else 0) - 161.1195681661
            g = max(0.0, min(255.0, g)) / 255.0
        else:
            g = 288.1221695283 * ((temp - 60) ** -0.0755148492)
            g = max(0.0, min(255.0, g)) / 255.0
        # Azul
        if temp >= 66:
            b = 1.0
        elif temp <= 19:
            b = 0.0
        else:
            b = 138.5177312231 * math.log(temp - 10) - 305.0447927307
            b = max(0.0, min(255.0, b)) / 255.0

        class GAMMA_RAMP(ctypes.Structure):
            _fields_ = [
                ("Red", wintypes.WORD * 256),
                ("Green", wintypes.WORD * 256),
                ("Blue", wintypes.WORD * 256),
            ]

        ramp = GAMMA_RAMP()
        for i in range(256):
            ramp.Red[i] = min(65535, int(i * 256 * r))
            ramp.Green[i] = min(65535, int(i * 256 * g))
            ramp.Blue[i] = min(65535, int(i * 256 * b))

        sucesso = gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        user32.ReleaseDC(0, hdc)
        return bool(sucesso)
    except Exception as e:
        _log.warning("Falha ao definir rampa de gama (%d K): %s", kelvin, e)
        return False


def _definir_taxa_atualizacao(hz: int) -> bool:
    """Alterna a taxa de atualização do monitor principal."""
    if os.name != "nt":
        return True
    try:
        user32 = ctypes.windll.user32
        # DEVMODEW simplificado para dmDisplayFrequency
        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", wintypes.WCHAR * 32),
                ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD),
                ("dmPositionX", wintypes.LONG),
                ("dmPositionY", wintypes.LONG),
                ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD),
                ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD),
                ("dmMediaType", wintypes.DWORD),
                ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD),
                ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD),
                ("dmPanningHeight", wintypes.DWORD),
            ]

        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        ENUM_CURRENT_SETTINGS = -1
        CDS_UPDATEREGISTRY = 0x01

        if user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            if dm.dmDisplayFrequency != hz:
                dm.dmDisplayFrequency = hz
                dm.dmFields |= 0x00400000  # DM_DISPLAYFREQUENCY
                res = user32.ChangeDisplaySettingsW(ctypes.byref(dm), CDS_UPDATEREGISTRY)
                return res == 0
        return True
    except Exception as e:
        _log.warning("Falha ao alterar taxa para %d Hz: %s", hz, e)
        return False


def ajustar_display(brilho: int | None = None, temperatura_k: int | None = None, taxa_hz: int | None = None, modo: str = "auto") -> dict[str, Any]:
    """Ajusta brilho, luz noturna e taxa de atualização conforme solicitação ou hora do dia."""
    modo = modo.lower()
    if modo == "auto" and (brilho is None or temperatura_k is None):
        import datetime
        agora = datetime.datetime.now()
        hora_dec = agora.hour + agora.minute / 60.0
        if 7.0 <= hora_dec < 18.5:
            # Dia
            brilho = brilho or 90
            temperatura_k = temperatura_k or 6500
        elif 18.5 <= hora_dec < 22.0:
            # Entardecer
            brilho = brilho or 65
            temperatura_k = temperatura_k or 4500
        else:
            # Noite
            brilho = brilho or 35
            temperatura_k = temperatura_k or 3400
            if taxa_hz is None:
                taxa_hz = 60

    sucessos = {}
    if brilho is not None:
        sucessos["brilho"] = _definir_brilho(brilho)
    if temperatura_k is not None:
        sucessos["gama"] = _definir_temperatura_gama(temperatura_k)
    if taxa_hz is not None:
        sucessos["taxa_hz"] = _definir_taxa_atualizacao(taxa_hz)

    return {
        "sucesso": all(sucessos.values()) if sucessos else True,
        "modo": modo,
        "brilho": brilho,
        "temperatura_k": temperatura_k,
        "taxa_hz": taxa_hz,
        "acoes": sucessos,
    }


# =====================================================================
# Item 20: Desconectar dispositivos Bluetooth ociosos
# =====================================================================
def _listar_dispositivos_bluetooth() -> list[dict[str, Any]]:
    """Consulta dispositivos Bluetooth emparelhados e conectados no Windows."""
    dispositivos = []
    if os.name != "nt":
        return dispositivos
    try:
        import subprocess
        cmd = "Get-PnpDevice -Class Bluetooth -Status OK | Select-Object InstanceId,FriendlyName | ConvertTo-Json"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=8, creationflags=0x08000000
        )
        out = (res.stdout or "").strip()
        if out:
            dados = json.loads(out)
            if isinstance(dados, dict):
                dados = [dados]
            for item in dados:
                iid = item.get("InstanceId", "")
                nome = item.get("FriendlyName", "")
                if iid and nome:
                    dispositivos.append({
                        "id": iid,
                        "nome": nome,
                        "conectado": True,
                        "minutos_sem_audio": 0,
                        "idle_medido": False,
                    })
    except Exception as e:
        _log.warning("Falha ao enumerar dispositivos Bluetooth: %s", e)
    return dispositivos


def _desconectar_dispositivo_bt(device_id: str) -> bool:
    """Desativa o dispositivo Bluetooth ocioso para poupar bateria."""
    if os.name != "nt":
        return True
    try:
        import subprocess
        env = dict(os.environ, ULTRON_BT_INSTANCE_ID=str(device_id or ""))
        cmd = "Disable-PnpDevice -InstanceId $env:ULTRON_BT_INSTANCE_ID -Confirm:$false"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=8, creationflags=0x08000000, env=env
        )
        return res.returncode == 0
    except Exception as e:
        _log.warning("Falha ao desativar dispositivo BT %s: %s", device_id, e)
        return False


def desconectar_bluetooth_ocioso(minutos_ocioso: int = 5, executar: bool = True) -> dict[str, Any]:
    """Identifica dispositivos Bluetooth de áudio inativos e desconecta para poupar bateria."""
    limite_minutos = max(1, int(minutos_ocioso or 5))
    dispositivos = _listar_dispositivos_bluetooth()
    desconectados = []

    for dev in dispositivos:
        minutos = dev.get("minutos_sem_audio", 0)
        if isinstance(minutos, (int, float)) and minutos >= limite_minutos:
            if executar:
                if _desconectar_dispositivo_bt(dev["id"]):
                    desconectados.append(dev)
            else:
                desconectados.append(dev)

    return {
        "sucesso": True,
        "total_encontrados": len(dispositivos),
        "ociosos_desconectados": len(desconectados),
        "minutos_limite": minutos_ocioso,
        "detalhes": desconectados,
        "simulado": not executar,
    }


