"""Cofre local para as chaves de API do ULTRON.

Por que existe: até aqui as chaves ficavam só no `.env` em texto puro. Este módulo
acrescenta um lugar seguro para colá-las pela interface, com estas regras:

  * cifradas com AES-GCM de 256 bits; a chave de criptografia é gerada pelo Windows
    (DPAPI do usuário) quando disponível e **nunca** sai da máquina;
  * gravadas em `dados/cofre.json` (fora do versionamento e fora do ZIP);
  * a interface **nunca** recebe a chave de volta: só o estado ("configurada",
    últimos 4 caracteres mascarados e de qual fonte veio);
  * o `.env` continua valendo. A ordem de precedência é
    `cofre → .env`, então quem já tem chave no `.env` não quebra nada;
  * a chave entra em memória só quando o provedor é usado, e todo log passa pelo
    `seguranca.redigir`, que mascara qualquer chave conhecida.

DPAPI é do próprio Windows (grátis, sem dependência): protege o arquivo contra
cópia para outro usuário/máquina. Se não estiver disponível (ex.: Linux/macOS ou
testes), o cofre cai para uma chave local em arquivo com permissão restrita e
**informa isso** no status — nunca finge que está protegido.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent
ARQUIVO = _RAIZ / "dados" / "cofre.json"
ARQUIVO_CHAVE = _RAIZ / "dados" / ".cofre.chave"
_trava = threading.Lock()

PROVEDORES = ("gemini", "groq", "nvidia", "openai", "openrouter", "mistral",
              "deepseek", "cerebras", "together", "xai")
OUTROS = ("telegram_token", "telegram_uid")
NOMES = {
    "gemini": "Gemini", "groq": "Groq", "nvidia": "NVIDIA Build",
    "openai": "OpenAI", "openrouter": "OpenRouter", "mistral": "Mistral",
    "deepseek": "DeepSeek", "cerebras": "Cerebras", "together": "Together AI",
    "xai": "xAI (Grok)",
    "telegram_token": "Telegram (token do bot)", "telegram_uid": "Telegram (seu ID)",
}
# Página oficial onde cada serviço mostra/cria a chave. O processo principal do
# Electron valida esta lista antes de abrir o navegador (nada de URL arbitrária).
LINKS = {
    "gemini": "https://aistudio.google.com/app/apikey",
    "groq": "https://console.groq.com/keys",
    "nvidia": "https://build.nvidia.com/settings/api-keys",
    "openai": "https://platform.openai.com/api-keys",
    "openrouter": "https://openrouter.ai/keys",
    "mistral": "https://console.mistral.ai/api-keys",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "cerebras": "https://cloud.cerebras.ai/",
    "together": "https://api.together.xyz/settings/api-keys",
    "xai": "https://console.x.ai/",
    "telegram_token": "https://t.me/BotFather",
    "telegram_uid": "https://t.me/userinfobot",
}
ENTROPIA_LABEL = b"ULTRON-Cofre-v1"


# --------------------------------------------------------------------- DPAPI
# CryptProtectData exige protótipos explícitos: sem eles o ctypes não encontra a
# função com ponteiros de 64 bits (foi por isso que a primeira versão caía sempre
# para o modo "arquivo").
_ENTROPIA_DESCRICAO = "ULTRON-Cofre-v1"


def _dpapi(dados: bytes, proteger: bool) -> bytes | None:
    """CryptProtectData / CryptUnprotectData (Windows). None se indisponível."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        prototipo = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        funcao = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
        funcao.restype = wintypes.BOOL
        funcao.argtypes = prototipo

        buffer = ctypes.create_string_buffer(dados, len(dados))
        entrada = DATA_BLOB(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        saida = DATA_BLOB()
        descricao = ctypes.c_wchar_p(_ENTROPIA_DESCRICAO) if proteger else None
        if not funcao(ctypes.byref(entrada), descricao, None, None, None, 0, ctypes.byref(saida)):
            return None
        try:
            return ctypes.string_at(saida.pbData, saida.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(saida.pbData, ctypes.c_void_p))
    except Exception:
        return None


def _chave_local() -> tuple[bytes, str]:
    """Chave de 32 bytes: via DPAPI (recomendado) ou arquivo restrito (reserva)."""
    cifrada = None
    try:
        cifrada = ARQUIVO_CHAVE.read_bytes()
    except FileNotFoundError:
        cifrada = None
    if cifrada:
        limpa = _dpapi(cifrada, proteger=False)
        if limpa and len(limpa) == 32:
            return limpa, "dpapi"
        if len(cifrada) == 32:          # modo reserva (sem DPAPI)
            return cifrada, "arquivo"
    nova = os.urandom(32)
    ARQUIVO_CHAVE.parent.mkdir(parents=True, exist_ok=True)
    protegida = _dpapi(nova, proteger=True)
    if protegida:
        ARQUIVO_CHAVE.write_bytes(protegida)
        modo = "dpapi"
    else:
        ARQUIVO_CHAVE.write_bytes(nova)
        try:
            os.chmod(ARQUIVO_CHAVE, 0o600)
        except OSError:
            pass
        modo = "arquivo"
    return nova, modo


# ------------------------------------------------------------------- cifra
def _aesgcm():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM


def _cifrar(texto: str) -> str:
    chave, _ = _chave_local()
    iv = os.urandom(12)
    dados = _aesgcm()(chave).encrypt(iv, texto.encode("utf-8"), b"ultron-cofre")
    return base64.b64encode(iv + dados).decode("ascii")


def _decifrar(pacote: str) -> str:
    chave, _ = _chave_local()
    cru = base64.b64decode(pacote.encode("ascii"))
    return _aesgcm()(chave).decrypt(cru[:12], cru[12:], b"ultron-cofre").decode("utf-8")


def _ler() -> dict:
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar(dados: dict) -> None:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(ARQUIVO, 0o600)
    except OSError:
        pass


# ------------------------------------------------------------------- API
def mascarar(valor: str) -> str:
    if not valor:
        return ""
    if len(valor) <= 4:
        return "•" * len(valor)
    return "•" * max(4, len(valor) - 4) + valor[-4:]


def _esquecer_cache() -> None:
    """A chave mudou: o próximo comando precisa criar clientes novos."""
    try:
        import cerebro
        cerebro.esquecer_clientes()
    except Exception:
        pass


def guardar(nome: str, valor: str) -> dict:
    """Guarda (ou substitui) uma credencial cifrada. Não devolve o valor."""
    if nome not in PROVEDORES + OUTROS:
        raise ValueError("Credencial desconhecida.")
    limpo = str(valor or "").strip()
    if not limpo:
        raise ValueError("A credencial está vazia.")
    if len(limpo) > 400:
        raise ValueError("Credencial longa demais.")
    if any(c.isspace() for c in limpo):
        raise ValueError("A credencial não pode conter espaços.")
    with _trava:
        dados = _ler()
        dados[nome] = {"valor": _cifrar(limpo), "em": time.time(), "dica": mascarar(limpo)}
        _gravar(dados)
    _esquecer_cache()
    return {"nome": nome, "dica": mascarar(limpo)}


def remover(nome: str) -> None:
    with _trava:
        dados = _ler()
        if nome in dados:
            dados.pop(nome, None)
            _gravar(dados)
            # a memória do processo também esquece
            if nome in PROVEDORES:
                import config
                config.CHAVES[nome] = ""
            elif nome == "telegram_token":
                import config
                config.TELEGRAM_TOKEN = ""
    _esquecer_cache()


def obter(nome: str) -> str:
    """Valor em claro — uso interno (provedor/telegram). Nunca expor por API."""
    dados = _ler().get(nome)
    if not isinstance(dados, dict) or "valor" not in dados:
        return ""
    try:
        return _decifrar(dados["valor"])
    except Exception:
        return ""


def status() -> dict:
    """O que a interface pode saber: configurado? de onde vem? qual o final?"""
    import config
    dados = _ler()
    _, modo = _chave_local()
    itens = []
    for nome in PROVEDORES + OUTROS:
        guardado = dados.get(nome) if isinstance(dados.get(nome), dict) else None
        if nome in PROVEDORES:
            do_env = bool(config.CHAVES.get(nome))
        elif nome == "telegram_token":
            do_env = bool(config.TELEGRAM_TOKEN)
        else:
            do_env = bool(getattr(config, "TELEGRAM_USER_ID", 0))
        fonte = "cofre" if guardado else ("env" if do_env else None)
        dica = guardado.get("dica") if guardado else (mascarar(getattr(config, "CHAVES", {}).get(nome, "")
                                                              or (config.TELEGRAM_TOKEN if nome == "telegram_token" else ""))
                                                      if do_env else "")
        itens.append({"nome": nome, "rotulo": NOMES[nome], "configurada": bool(fonte),
                      "fonte": fonte, "dica": dica, "link": LINKS.get(nome, ""),
                      "testavel": nome in PROVEDORES})
    return {
        "itens": itens,
        "protecao": ("Windows DPAPI + AES-256-GCM" if modo == "dpapi"
                     else "AES-256-GCM com chave local (sem DPAPI neste sistema)"),
        "modo": modo,
        "arquivo": (str(ARQUIVO.relative_to(_RAIZ)) if ARQUIVO.is_relative_to(_RAIZ)
                    else ARQUIVO.name),
        "precedencia": "cofre → .env",
    }


def aplicar_na_config() -> dict:
    """Passa as chaves do cofre para config em memória (chamado na inicialização)."""
    import config
    aplicadas = []
    for nome in PROVEDORES:
        valor = obter(nome)
        if valor:
            config.CHAVES[nome] = valor
            aplicadas.append(nome)
    token = obter("telegram_token")
    if token:
        config.TELEGRAM_TOKEN = token
        aplicadas.append("telegram_token")
    uid = obter("telegram_uid")
    if uid.isdigit():
        config.TELEGRAM_USER_ID = int(uid)
        aplicadas.append("telegram_uid")
    return {"aplicadas": aplicadas}


def _redacao_extra() -> None:
    """Faz o redator de logs mascarar também o que está no cofre."""
    try:
        import seguranca
        valores = [obter(n) for n in PROVEDORES + OUTROS]
        seguranca.SEGREDOS_COFRE = tuple(v for v in valores if v and len(v) >= 4)
    except Exception:
        pass
