"""Controle isolado de volume e mudo por aplicativo no Windows via Core Audio (WASAPI)."""
from __future__ import annotations

import ctypes
import difflib
import os
import re
import sys
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

_COINIT_APARTMENTTHREADED = 0x2
_E_RENDER = 0
_DEVICE_STATE_ACTIVE = 1
_AUDIO_SESSION_EXPIRED = 2
_PASSO_PADRAO = 15

_APELIDOS: dict[str, tuple[str, ...]] = {
    "google": ("chrome", "googlechrome"),
    "googlechrome": ("chrome", "googlechrome"),
    "chrome": ("chrome", "googlechrome"),
    "edge": ("msedge", "microsoftedge"),
    "microsoftedge": ("msedge", "microsoftedge"),
    "firefox": ("firefox", "mozillafirefox"),
    "mozilla": ("firefox", "mozillafirefox"),
    "navegador": ("chrome", "msedge", "firefox", "brave", "opera", "operagx", "vivaldi"),
    "browser": ("chrome", "msedge", "firefox", "brave", "opera", "operagx", "vivaldi"),
    "spotify": ("spotify",),
    "discord": ("discord", "discordptb", "discordcanary"),
    "whatsapp": ("whatsapp", "whatsappdesktop", "whatsapproot"),
    "zap": ("whatsapp", "whatsappdesktop", "whatsapproot"),
    "telegram": ("telegram", "telegramdesktop"),
    "steam": ("steam", "steamwebhelper"),
    "teams": ("msteams", "teams"),
    "vlc": ("vlc",),
    "youtube": ("youtube", "youtubemusic", "youtubemusicdesktopapp"),
    "sistema": ("systemsounds", "sonsdosistema"),
    "sonsdosistema": ("systemsounds", "sonsdosistema"),
    "windows": ("systemsounds", "sonsdosistema"),
}

_NOMES_AMIGAVEIS: dict[str, str] = {
    "chrome": "Google Chrome",
    "googlechrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "operagx": "Opera GX",
    "vivaldi": "Vivaldi",
    "spotify": "Spotify",
    "discord": "Discord",
    "discordptb": "Discord PTB",
    "discordcanary": "Discord Canary",
    "whatsapp": "WhatsApp",
    "whatsappdesktop": "WhatsApp",
    "telegram": "Telegram",
    "steam": "Steam",
    "steamwebhelper": "Steam",
    "msteams": "Microsoft Teams",
    "teams": "Microsoft Teams",
    "vlc": "VLC",
    "systemsounds": "Sons do sistema",
    "sonsdosistema": "Sons do sistema",
}

_ACOES = {
    "definir": "definir",
    "set": "definir",
    "colocar": "definir",
    "ajustar": "definir",
    "deixar": "definir",
    "aumentar": "aumentar",
    "subir": "aumentar",
    "mais": "aumentar",
    "up": "aumentar",
    "diminuir": "diminuir",
    "abaixar": "diminuir",
    "baixar": "diminuir",
    "menos": "diminuir",
    "down": "diminuir",
    "mutar": "mutar",
    "mute": "mutar",
    "silenciar": "mutar",
    "mudo": "mutar",
    "desmutar": "desmutar",
    "unmute": "desmutar",
    "dessilenciar": "desmutar",
    "ativar_som": "desmutar",
    "ativarsom": "desmutar",
    "alternar_mudo": "alternar_mudo",
    "alternarmudo": "alternar_mudo",
    "toggle": "alternar_mudo",
    "consultar": "consultar",
    "ver": "consultar",
    "ler": "consultar",
    "status": "consultar",
    "get": "consultar",
}


@dataclass
class SessaoAudio:
    """Representa uma sessão de áudio WASAPI vinculada a um processo."""

    pid: int
    executavel: str
    nome_exibicao: str
    volume: int
    mudo: bool
    ativa: bool = False
    sistema: bool = False
    definir_volume: Callable[[int], None] | None = None
    definir_mudo: Callable[[bool], None] | None = None


def normalizar_nome(texto: str) -> str:
    """Remove acentos, extensão .exe e pontuação para comparar nomes de apps."""
    bruto = unicodedata.normalize("NFD", str(texto or "").strip().lower())
    sem_acento = "".join(c for c in bruto if unicodedata.category(c) != "Mn")
    if sem_acento.endswith(".exe"):
        sem_acento = sem_acento[:-4]
    return re.sub(r"[^a-z0-9]", "", sem_acento)


def _chave_canonica(sessao: SessaoAudio) -> str:
    if sessao.sistema or sessao.pid == 0:
        return "systemsounds"
    exe_norm = normalizar_nome(sessao.executavel)
    if exe_norm:
        return exe_norm
    return normalizar_nome(sessao.nome_exibicao) or f"pid{sessao.pid}"


def _nome_amigavel(sessao: SessaoAudio) -> str:
    chave = _chave_canonica(sessao)
    if chave in _NOMES_AMIGAVEIS:
        return _NOMES_AMIGAVEIS[chave]
    if sessao.nome_exibicao and not sessao.nome_exibicao.startswith("@"):
        return sessao.nome_exibicao
    exe = os.path.basename(sessao.executavel or "").strip()
    if exe.lower().endswith(".exe"):
        exe = exe[:-4]
    return exe or f"PID {sessao.pid}"


def _ler_bstr_com(fn_chamada) -> str:
    ptr = ctypes.c_void_p()
    try:
        fn_chamada(ctypes.byref(ptr))
    except Exception:
        return ""
    if not ptr.value:
        return ""
    try:
        texto = ctypes.wstring_at(ptr.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ptr.value)
    return "" if texto.startswith("@") else texto.strip()


def _construir_interfaces_wasapi():
    """Define sob demanda as interfaces COM do Core Audio via comtypes."""
    from ctypes import HRESULT, POINTER, c_float, c_int, c_uint, c_void_p, c_wchar_p
    from ctypes.wintypes import BOOL
    from comtypes import COMMETHOD, GUID, IUnknown

    class IAudioSessionControl(IUnknown):
        _iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_int), "pRetVal")),
            COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(c_void_p), "pRetVal")),
            COMMETHOD([], HRESULT, "SetDisplayName", (["in"], c_wchar_p, "Value"),
                      (["in"], POINTER(GUID), "EventContext")),
            COMMETHOD([], HRESULT, "GetIconPath", (["out"], POINTER(c_void_p), "pRetVal")),
            COMMETHOD([], HRESULT, "SetIconPath", (["in"], c_wchar_p, "Value"),
                      (["in"], POINTER(GUID), "EventContext")),
            COMMETHOD([], HRESULT, "GetGroupingParam", (["out"], POINTER(GUID), "pRetVal")),
            COMMETHOD([], HRESULT, "SetGroupingParam", (["in"], POINTER(GUID), "Override"),
                      (["in"], POINTER(GUID), "EventContext")),
            COMMETHOD([], HRESULT, "RegisterAudioSessionNotification", (["in"], c_void_p, "NewNotifications")),
            COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification", (["in"], c_void_p, "NewNotifications")),
        ]

    class IAudioSessionControl2(IAudioSessionControl):
        _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetSessionIdentifier", (["out"], POINTER(c_void_p), "pRetVal")),
            COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier", (["out"], POINTER(c_void_p), "pRetVal")),
            COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(c_uint), "pRetVal")),
            COMMETHOD([], HRESULT, "IsSystemSoundsSession"),
            COMMETHOD([], HRESULT, "SetDuckingPreference", (["in"], BOOL, "optOut")),
        ]

    class ISimpleAudioVolume(IUnknown):
        _iid_ = GUID("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")
        _methods_ = [
            COMMETHOD([], HRESULT, "SetMasterVolume", (["in"], c_float, "fLevel"),
                      (["in"], POINTER(GUID), "EventContext")),
            COMMETHOD([], HRESULT, "GetMasterVolume", (["out"], POINTER(c_float), "pfLevel")),
            COMMETHOD([], HRESULT, "SetMute", (["in"], BOOL, "bMute"),
                      (["in"], POINTER(GUID), "EventContext")),
            COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "pbMute")),
        ]

    class IAudioSessionEnumerator(IUnknown):
        _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_int), "SessionCount")),
            COMMETHOD([], HRESULT, "GetSession", (["in"], c_int, "SessionCount"),
                      (["out"], POINTER(POINTER(IAudioSessionControl)), "Session")),
        ]

    class IAudioSessionManager2(IUnknown):
        _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetAudioSessionControl", (["in"], POINTER(GUID), "AudioSessionGuid"),
                      (["in"], c_uint, "StreamFlags"),
                      (["out"], POINTER(POINTER(IAudioSessionControl)), "SessionControl")),
            COMMETHOD([], HRESULT, "GetSimpleAudioVolume", (["in"], POINTER(GUID), "AudioSessionGuid"),
                      (["in"], c_uint, "StreamFlags"),
                      (["out"], POINTER(POINTER(ISimpleAudioVolume)), "AudioVolume")),
            COMMETHOD([], HRESULT, "GetSessionEnumerator",
                      (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "SessionEnum")),
            COMMETHOD([], HRESULT, "RegisterSessionNotification", (["in"], c_void_p, "SessionNotification")),
            COMMETHOD([], HRESULT, "UnregisterSessionNotification", (["in"], c_void_p, "SessionNotification")),
            COMMETHOD([], HRESULT, "RegisterDuckNotification", (["in"], c_wchar_p, "sessionID"),
                      (["in"], c_void_p, "duckNotification")),
            COMMETHOD([], HRESULT, "UnregisterDuckNotification", (["in"], c_void_p, "duckNotification")),
        ]

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], c_uint, "dwClsCtx"),
                      (["in"], c_void_p, "pActivationParams"), (["out"], POINTER(POINTER(IUnknown)), "ppInterface")),
            COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], c_uint, "stgmAccess"),
                      (["out"], POINTER(c_void_p), "ppProperties")),
            COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_void_p), "ppstrId")),
            COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_uint), "pdwState")),
        ]

    class IMMDeviceCollection(IUnknown):
        _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint), "pcDevices")),
            COMMETHOD([], HRESULT, "Item", (["in"], c_uint, "nDevice"),
                      (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
        ]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [
            COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_int, "dataFlow"),
                      (["in"], c_uint, "dwStateMask"),
                      (["out"], POINTER(POINTER(IMMDeviceCollection)), "ppDevices")),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_int, "dataFlow"),
                      (["in"], c_int, "role"), (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
            COMMETHOD([], HRESULT, "GetDevice", (["in"], c_wchar_p, "pwstrId"),
                      (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
            COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback", (["in"], c_void_p, "pClient")),
            COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback", (["in"], c_void_p, "pClient")),
        ]

    return (
        GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),
        IMMDeviceEnumerator,
        IAudioSessionManager2,
        IAudioSessionControl2,
        ISimpleAudioVolume,
    )


def _nome_processo(pid: int) -> str:
    if pid <= 0:
        return "System Sounds"
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return ""


@contextmanager
def _sessoes_wasapi():
    """Inicializa COM em escopo seguro, expõe sessões WASAPI ativas e limpa ponteiros antes de CoUninitialize."""
    if sys.platform != "win32":
        raise RuntimeError("Controle de volume por aplicativo disponível apenas no Windows.")

    import comtypes

    hr = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    precisa_uninit = hr in (0, 1)
    sessoes: list[SessaoAudio] = []
    com_refs: list[object] = []
    try:
        clsid_enum, imm_enum, mgr_cls, ctl2_cls, vol_cls = _construir_interfaces_wasapi()
        enumerador = comtypes.CoCreateInstance(clsid_enum, imm_enum, comtypes.CLSCTX_ALL)
        com_refs.append(enumerador)
        colecao = enumerador.EnumAudioEndpoints(_E_RENDER, _DEVICE_STATE_ACTIVE)
        com_refs.append(colecao)
        qtd_disp = colecao.GetCount()

        for i in range(qtd_disp):
            try:
                dispositivo = colecao.Item(i)
                com_refs.append(dispositivo)
                iface = dispositivo.Activate(mgr_cls._iid_, comtypes.CLSCTX_ALL, None)
                com_refs.append(iface)
                gerente = iface.QueryInterface(mgr_cls)
                com_refs.append(gerente)
                enum_sessoes = gerente.GetSessionEnumerator()
                com_refs.append(enum_sessoes)
                qtd_sessoes = enum_sessoes.GetCount()
            except Exception:
                continue

            for j in range(qtd_sessoes):
                try:
                    ctl = enum_sessoes.GetSession(j)
                    com_refs.append(ctl)
                    estado = int(ctl.GetState())
                    if estado == _AUDIO_SESSION_EXPIRED:
                        continue
                    ctl2 = ctl.QueryInterface(ctl2_cls)
                    vol_iface = ctl.QueryInterface(vol_cls)
                    com_refs.extend((ctl2, vol_iface))
                    pid = int(ctl2.GetProcessId())
                    display = _ler_bstr_com(ctl.GetDisplayName)
                    exe = _nome_processo(pid)
                    sistema = pid == 0
                    if not sistema and not exe and not display:
                        continue
                    nivel = max(0, min(100, int(round(float(vol_iface.GetMasterVolume()) * 100))))
                    mudo = bool(vol_iface.GetMute())

                    def _set_vol(novo_pct: int, _v=vol_iface) -> None:
                        alvo = max(0.0, min(1.0, float(novo_pct) / 100.0))
                        _v.SetMasterVolume(alvo, None)

                    def _set_mute(estado_mudo: bool, _v=vol_iface) -> None:
                        _v.SetMute(bool(estado_mudo), None)

                    sessoes.append(
                        SessaoAudio(
                            pid=pid,
                            executavel=exe,
                            nome_exibicao=display or ("Sons do sistema" if sistema else ""),
                            volume=nivel,
                            mudo=mudo,
                            ativa=(estado == 1),
                            sistema=sistema,
                            definir_volume=_set_vol,
                            definir_mudo=_set_mute,
                        )
                    )
                except Exception:
                    continue

        yield sessoes
    finally:
        # Libera referências COM antes de CoUninitialize para evitar access violation.
        sessoes.clear()
        com_refs.clear()
        if precisa_uninit:
            ctypes.windll.ole32.CoUninitialize()


def _filtrar_por_alvos(sessoes: list[SessaoAudio], alvos: tuple[str, ...]) -> list[SessaoAudio]:
    conjunto = set(alvos)
    return [
        s for s in sessoes
        if _chave_canonica(s) in conjunto or normalizar_nome(s.nome_exibicao) in conjunto
    ]


def resolver_sessoes(sessoes: list[SessaoAudio], aplicativo: str) -> list[SessaoAudio]:
    """Encontra todas as sessões de áudio pertencentes ao aplicativo pedido."""
    consulta = normalizar_nome(aplicativo)
    if not consulta or not sessoes:
        return []

    # 1. Correspondência exata pelo executável ou nome exibido
    exatas = [
        s for s in sessoes
        if _chave_canonica(s) == consulta or normalizar_nome(s.nome_exibicao) == consulta
    ]
    if exatas:
        return exatas

    # 2. Apelidos conhecidos (ex.: "google" -> Google Chrome)
    alvos_apelido = _APELIDOS.get(consulta)
    if alvos_apelido:
        por_apelido = _filtrar_por_alvos(sessoes, alvos_apelido)
        if por_apelido:
            return por_apelido

    # 3. Substring em executável ou nome de exibição (ex.: "silksong" -> Hollow Knight Silksong)
    if len(consulta) >= 3:
        parciais = [
            s for s in sessoes
            if consulta in _chave_canonica(s) or consulta in normalizar_nome(s.nome_exibicao)
        ]
        if parciais:
            chaves = {_chave_canonica(s) for s in parciais}
            if len(chaves) == 1:
                return parciais
            ativas = [s for s in parciais if s.ativa]
            if ativas and len({_chave_canonica(s) for s in ativas}) == 1:
                return ativas
            return parciais

    # 4. Correspondência aproximada para variações de voz / digitação
    if len(consulta) >= 3:
        mapa_candidatos: dict[str, set[str]] = {}
        for s in sessoes:
            for cand in (_chave_canonica(s), normalizar_nome(s.nome_exibicao)):
                if cand:
                    mapa_candidatos.setdefault(cand, set()).add(_chave_canonica(s))
        proximos = difflib.get_close_matches(consulta, list(mapa_candidatos.keys()), n=1, cutoff=0.72)
        if proximos:
            chaves = tuple(mapa_candidatos[proximos[0]])
            return _filtrar_por_alvos(sessoes, chaves)

    return []


def _resumo_sessoes(sessoes: list[SessaoAudio]) -> str:
    """Agrupa múltiplas sessões do mesmo app em um resumo legível."""
    agrupado: dict[str, list[SessaoAudio]] = {}
    for s in sessoes:
        agrupado.setdefault(_chave_canonica(s), []).append(s)

    partes = []
    for grupo in agrupado.values():
        rep = next((s for s in grupo if s.ativa), grupo[0])
        etiqueta = f"{_nome_amigavel(rep)}: {rep.volume}%"
        if rep.mudo:
            etiqueta += " (mutado)"
        elif any(s.ativa for s in grupo):
            etiqueta += " (tocando)"
        partes.append(etiqueta)
    return "; ".join(partes)


def _processo_aberto_sem_audio(aplicativo: str) -> str:
    """Verifica se o processo está aberto no Windows mesmo sem sessão de áudio criada."""
    consulta = normalizar_nome(aplicativo)
    if not consulta:
        return ""
    alvos = {consulta, *_APELIDOS.get(consulta, ())}
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            nome = proc.info.get("name") or ""
            norm = normalizar_nome(nome)
            if not norm:
                continue
            if norm in alvos or (len(consulta) >= 4 and consulta in norm):
                return nome
    except Exception:
        return ""
    return ""


def listar_volumes_apps(provedor=_sessoes_wasapi) -> str:
    """Lista todos os aplicativos com sessão de áudio ativa/pausada e seus volumes."""
    try:
        with provedor() as sessoes:
            relevantes = [s for s in sessoes if not s.sistema] or list(sessoes)
            if not relevantes:
                return "Não há nenhum aplicativo com sessão de áudio aberta no momento."
            return f"Apps com áudio no Windows: {_resumo_sessoes(relevantes)}."
    except Exception as e:
        return f"Não consegui ler as sessões de áudio do Windows: {e}"


def _interpretar_acao(acao: str, nivel: int) -> tuple[str, int]:
    bruto = unicodedata.normalize("NFD", str(acao or "").strip().lower())
    sem_acento = "".join(c for c in bruto if unicodedata.category(c) != "Mn")
    chave = re.sub(r"[^a-z0-9_]+", "_", sem_acento).strip("_")
    norm = _ACOES.get(chave) or _ACOES.get(normalizar_nome(acao), "definir")
    return norm, int(nivel)


def _aplicar_em_sessoes(sessoes: list[SessaoAudio], volume: int | None, mudo: bool | None) -> None:
    for s in sessoes:
        if volume is not None and s.definir_volume:
            s.definir_volume(volume)
        if mudo is not None and s.definir_mudo:
            s.definir_mudo(mudo)


def controlar_volume_app(
    aplicativo: str,
    nivel: int = -1,
    acao: str = "definir",
    provedor=_sessoes_wasapi,
    verificar_processo: Callable[[str], str] | None = _processo_aberto_sem_audio,
) -> str:
    """Ajusta, consulta ou silencia o volume de um aplicativo específico sem afetar os outros."""
    nome_app = str(aplicativo or "").strip()
    if not nome_app:
        return "Qual aplicativo você quer ajustar? " + listar_volumes_apps(provedor=provedor)

    try:
        acao_norm, nivel_int = _interpretar_acao(acao, nivel)
    except (TypeError, ValueError):
        return "O nível de volume precisa ser um número inteiro de 0 a 100."

    try:
        with provedor() as sessoes:
            alvos = resolver_sessoes(sessoes, nome_app)
            if not alvos:
                sem_audio = verificar_processo(nome_app) if verificar_processo else ""
                disponiveis = _resumo_sessoes([s for s in sessoes if not s.sistema] or sessoes)
                sufixo = f" Sessões disponíveis: {disponiveis}." if disponiveis else " Nenhuma sessão de áudio está aberta."
                if sem_audio:
                    return (
                        f"O aplicativo '{sem_audio}' está aberto, mas ainda não iniciou nenhuma sessão "
                        f"de áudio no Windows (reproduza um som nele primeiro).{sufixo}"
                    )
                return f"Não encontrei sessão de áudio para '{nome_app}'.{sufixo}"

            rep = next((s for s in alvos if s.ativa), alvos[0])
            nome_final = _nome_amigavel(rep)

            if acao_norm == "consultar":
                estado_mudo = " (mutado)" if rep.mudo else ""
                return f"Volume de {nome_final}: {rep.volume}%{estado_mudo}."

            if acao_norm == "mutar":
                _aplicar_em_sessoes(alvos, None, True)
                return f"{nome_final} mutado."

            if acao_norm == "desmutar":
                _aplicar_em_sessoes(alvos, None, False)
                return f"Som de {nome_final} reativado em {rep.volume}%."

            if acao_norm == "alternar_mudo":
                novo_mudo = not rep.mudo
                _aplicar_em_sessoes(alvos, None, novo_mudo)
                return f"{nome_final} mutado." if novo_mudo else f"Som de {nome_final} reativado em {rep.volume}%."

            if acao_norm == "aumentar":
                passo = nivel_int if 0 < nivel_int <= 100 else _PASSO_PADRAO
                novo = min(100, rep.volume + passo)
                desmutou = rep.mudo and novo > 0
                _aplicar_em_sessoes(alvos, novo, False if desmutou else None)
                extra = " e desmutado" if desmutou else ""
                return f"Volume de {nome_final} aumentado para {novo}%{extra}."

            if acao_norm == "diminuir":
                passo = nivel_int if 0 < nivel_int <= 100 else _PASSO_PADRAO
                novo = max(0, rep.volume - passo)
                _aplicar_em_sessoes(alvos, novo, None)
                return f"Volume de {nome_final} reduzido para {novo}%."

            if nivel_int < 0:
                estado_mudo = " (mutado)" if rep.mudo else ""
                return (
                    f"Volume atual de {nome_final}: {rep.volume}%{estado_mudo}. "
                    "Informe um nível de 0 a 100 ou uma ação (aumentar, diminuir, mutar, desmutar)."
                )

            novo = max(0, min(100, nivel_int))
            desmutou = rep.mudo and novo > 0
            _aplicar_em_sessoes(alvos, novo, False if desmutou else None)
            extra = " (desmutado)" if desmutou else ""
            return f"Volume de {nome_final} ajustado para {novo}%{extra}."
    except Exception as e:
        return f"Não consegui ajustar o volume de '{nome_app}': {e}"
