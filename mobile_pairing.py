"""Gerenciamento criptografado de pareamento e chaves HMAC para U.L.T.R.O.N. Mobile."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path
from urllib.parse import quote

import cofre
import config
import mobile_qr

MIN_SECRET_LEN = 16
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FORBIDDEN_SECRETS = frozenset({"ultron_lan_guard", "changeme", "secret", "password"})
_trava = threading.Lock()


def arquivo_pareamento() -> Path:
    """Caminho do arquivo de pareamento Mobile conforme diretórios ativos."""
    return Path(
        getattr(
            config,
            "ARQUIVO_MOBILE_PAIRING",
            getattr(config, "DIR_DADOS", config.BASE / "dados") / "mobile_pairing.json",
        )
    )


def gerar_segredo() -> str:
    """Gera um segredo HMAC criptograficamente aleatório (zero segredos hardcoded)."""
    return secrets.token_urlsafe(32)


def gerar_device_id(prefixo: str = "ultron-mobile") -> str:
    """Gera um identificador seguro de dispositivo pareado."""
    limpo = re.sub(r"[^A-Za-z0-9._-]+", "-", str(prefixo or "ultron-mobile")).strip(".-_")
    base = (limpo or "ultron-mobile")[:50]
    candidato = f"{base}-{secrets.token_hex(4)}"
    return validar_device_id(candidato)


def validar_device_id(device_id: str) -> str:
    """Valida e normaliza o identificador do dispositivo pareado."""
    if not isinstance(device_id, str):
        raise ValueError("Device ID inválido.")
    limpo = device_id.strip()
    if not DEVICE_ID_RE.fullmatch(limpo):
        raise ValueError("Device ID inválido: use apenas letras, números, '.', '_' ou '-' (1..64).")
    return limpo


def validar_segredo(segredo: str) -> str:
    """Valida entropia mínima e rejeita segredos proibidos/inseguros."""
    if not isinstance(segredo, str):
        raise ValueError("Segredo HMAC inválido.")
    limpo = segredo.strip()
    if not limpo or len(limpo) < MIN_SECRET_LEN:
        raise ValueError(f"Segredo HMAC deve ter pelo menos {MIN_SECRET_LEN} caracteres.")
    if any(ch.isspace() for ch in limpo):
        raise ValueError("Segredo HMAC não pode conter espaços em branco.")
    if limpo.lower() in _FORBIDDEN_SECRETS:
        raise ValueError("Segredo HMAC inseguro ou proibido.")
    return limpo


def _segredo_valido_em_leitura(segredo: str) -> str:
    try:
        return validar_segredo(segredo)
    except ValueError:
        return ""


def _ip_privado_lan(texto_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(texto_ip).strip())
    except ValueError:
        return False
    if ip.version != 4:
        return False
    return (
        ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_unspecified
        and not ip.is_multicast
    )


def descobrir_ip_lan() -> str:
    """Descobre o IPv4 da interface LAN ativa (ou 127.0.0.1 em ambiente isolado)."""
    for alvo in (("192.0.2.1", 80), ("8.8.8.8", 80)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.2)
            sock.connect(alvo)
            candidato = sock.getsockname()[0]
            if _ip_privado_lan(candidato):
                return candidato
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidato = info[4][0]
            if _ip_privado_lan(candidato):
                return candidato
    except OSError:
        pass
    return "127.0.0.1"


def _ler_raw() -> dict:
    caminho = arquivo_pareamento()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            return dados
    except (OSError, ValueError):
        pass
    return {"version": 1, "devices": {}}


def _gravar_raw(dados: dict) -> None:
    caminho = arquivo_pareamento()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + f".{secrets.token_hex(4)}.tmp")
    payload = json.dumps(dados, ensure_ascii=False, indent=2)
    try:
        tmp.write_text(payload, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, caminho)
        try:
            os.chmod(caminho, 0o600)
        except OSError:
            pass
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _decifrar_opcional(pacote) -> str:
    if not isinstance(pacote, str) or not cofre.parece_cifrado(pacote):
        return ""
    try:
        valor = cofre.decifrar_dados(pacote)
    except Exception:
        return ""
    return _segredo_valido_em_leitura(valor)


def criar_ou_rotacionar(
    device_id: str | None = None,
    shared_secret: str | None = None,
    killswitch_secret: str | None = None,
    killswitch_separado: bool = False,
) -> dict:
    """Cria ou rotaciona pareamento Mobile persistido cifrado em disco."""
    dev_id = validar_device_id(device_id) if device_id is not None else gerar_device_id()
    segredo = validar_segredo(shared_secret) if shared_secret is not None else gerar_segredo()

    if killswitch_secret is not None:
        ks_segredo = validar_segredo(killswitch_secret)
        ks_dedicado = True
    elif killswitch_separado:
        ks_segredo = gerar_segredo()
        ks_dedicado = True
    else:
        ks_segredo = ""
        ks_dedicado = False

    agora = time.time()
    with _trava:
        dados = _ler_raw()
        devices = dados.get("devices")
        if not isinstance(devices, dict):
            devices = {}
        anterior = devices.get(dev_id) if isinstance(devices.get(dev_id), dict) else None
        criado_em = float(anterior.get("created_at", agora)) if anterior else agora
        devices[dev_id] = {
            "secret_enc": cofre.cifrar_dados(segredo),
            "hint": cofre.mascarar(segredo),
            "created_at": criado_em,
            "rotated_at": agora,
        }
        dados["version"] = 1
        dados["devices"] = devices
        if ks_dedicado:
            dados["killswitch_secret_enc"] = cofre.cifrar_dados(ks_segredo)
            dados["killswitch_hint"] = cofre.mascarar(ks_segredo)
        else:
            dados.pop("killswitch_secret_enc", None)
            dados.pop("killswitch_hint", None)
        _gravar_raw(dados)

    registrar_redacao()
    porta = int(getattr(config, "MOBILE_PORT", 8765))
    lan_ip = descobrir_ip_lan()
    lan_url = f"http://{lan_ip}:{porta}"
    ks_effective = ks_segredo if ks_dedicado else segredo
    pairing_uri = gerar_pairing_uri(
        lan_url=lan_url,
        device_id=dev_id,
        shared_secret=segredo,
        killswitch_secret=ks_segredo if ks_dedicado else None,
    )
    return {
        "device_id": dev_id,
        "shared_secret": segredo,
        "killswitch_secret": ks_effective,
        "killswitch_separado": ks_dedicado,
        "lan_ip": lan_ip,
        "port": porta,
        "lan_url": lan_url,
        "killswitch_url": f"{lan_url}/killswitch",
        "pairing_uri": pairing_uri,
        "qr_data_uri": mobile_qr.render_svg_data_uri(pairing_uri),
    }


def gerar_pairing_uri(
    *,
    lan_url: str,
    device_id: str,
    shared_secret: str,
    killswitch_secret: str | None = None,
) -> str:
    """Gera URI linkável ultron://pair com parâmetros seguros codificados para QR Code."""
    ks_param = quote(killswitch_secret, safe="") if killswitch_secret else "same"
    return (
        "ultron://pair"
        f"?url={quote(lan_url, safe='')}"
        f"&device={quote(device_id, safe='')}"
        f"&secret={quote(shared_secret, safe='')}"
        f"&ks={ks_param}"
    )


def obter_segredo_dispositivo(device_id: str) -> str:
    """Retorna o segredo compartilhado em claro para validação HMAC interna (ou '' se ausente)."""
    try:
        dev_id = validar_device_id(device_id)
    except ValueError:
        return ""
    with _trava:
        dados = _ler_raw()
    devices = dados.get("devices")
    if not isinstance(devices, dict):
        return ""
    item = devices.get(dev_id)
    if not isinstance(item, dict):
        return ""
    return _decifrar_opcional(item.get("secret_enc"))


def obter_segredos_killswitch() -> list[tuple[str, str]]:
    """Lista (identificador, segredo) válidos aceitos pelo endpoint /killswitch."""
    with _trava:
        dados = _ler_raw()
    candidatos: list[tuple[str, str]] = []
    ks = _decifrar_opcional(dados.get("killswitch_secret_enc"))
    if ks:
        candidatos.append(("killswitch", ks))
    devices = dados.get("devices")
    if isinstance(devices, dict):
        for dev_id in sorted(devices):
            item = devices.get(dev_id)
            if not isinstance(item, dict):
                continue
            seg = _decifrar_opcional(item.get("secret_enc"))
            if seg:
                candidatos.append((str(dev_id), seg))
    return candidatos


def tem_pareamento_ativo() -> bool:
    """True apenas quando há pelo menos um segredo ativo e válido (fail-closed)."""
    return bool(obter_segredos_killswitch())


def revogar(device_id: str | None = None) -> dict:
    """Remove um dispositivo específico ou limpa todo o pareamento Mobile."""
    with _trava:
        dados = _ler_raw()
        devices = dados.get("devices") if isinstance(dados.get("devices"), dict) else {}
        if device_id is None:
            removidos = len(devices) + (1 if dados.get("killswitch_secret_enc") else 0)
            dados = {"version": 1, "devices": {}}
        else:
            dev_id = validar_device_id(device_id)
            removidos = 1 if dev_id in devices else 0
            devices.pop(dev_id, None)
            dados["devices"] = devices
            if not devices:
                dados.pop("killswitch_secret_enc", None)
                dados.pop("killswitch_hint", None)
        _gravar_raw(dados)
    registrar_redacao()
    return {"revoked": True, "removed_count": removidos, "configured": tem_pareamento_ativo()}


def status_publico(port: int | None = None) -> dict:
    """Resumo seguro (sem segredos) para exibição em CLI/UI."""
    with _trava:
        dados = _ler_raw()
    devices_raw = dados.get("devices") if isinstance(dados.get("devices"), dict) else {}
    devices = []
    for dev_id in sorted(devices_raw):
        item = devices_raw.get(dev_id)
        if not isinstance(item, dict):
            continue
        if not _decifrar_opcional(item.get("secret_enc")):
            continue
        devices.append({
            "device_id": dev_id,
            "hint": str(item.get("hint") or ""),
            "created_at": item.get("created_at"),
            "rotated_at": item.get("rotated_at"),
        })
    ks_valido = bool(_decifrar_opcional(dados.get("killswitch_secret_enc")))
    porta = int(port if port is not None else getattr(config, "MOBILE_PORT", 8765))
    lan_ip = descobrir_ip_lan()
    lan_url = f"http://{lan_ip}:{porta}"
    return {
        "configured": bool(devices or ks_valido),
        "devices": devices,
        "killswitch_dedicated": ks_valido,
        "killswitch_hint": str(dados.get("killswitch_hint") or "") if ks_valido else "",
        "lan_ip": lan_ip,
        "port": porta,
        "lan_url": lan_url,
        "killswitch_url": f"{lan_url}/killswitch",
    }


def registrar_redacao() -> None:
    """Registra todos os segredos Mobile ativos no redator de logs de seguranca.py."""
    try:
        import seguranca
        segredos = []
        vistos = set()
        for _label, seg in obter_segredos_killswitch():
            if seg and seg not in vistos:
                vistos.add(seg)
                segredos.append(seg)
        seguranca.SEGREDOS_MOBILE = tuple(segredos)
    except Exception:
        pass
