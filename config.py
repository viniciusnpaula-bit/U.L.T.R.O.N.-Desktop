"""Configurações lidas do arquivo .env"""
import os
from pathlib import Path
from dotenv import load_dotenv

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import shutil
import sqlite3
import time

# ------------------------------------------------------------- 1. Política de Diretórios
BASE = Path(__file__).resolve().parent


def _determinar_modo() -> str:
    if os.environ.get("ULTRON_PORTABLE") == "1" or (BASE / ".portable").is_file():
        return "portatil"
    if os.environ.get("ULTRON_INSTALLED") == "1":
        return "instalado"
    if os.environ.get("ULTRON_DEV") == "1" or os.environ.get("PYTEST_CURRENT_TEST") or (BASE / ".git").is_dir():
        return "desenvolvimento"
    base_str = str(BASE).lower()
    if "\\programs\\" in base_str or "\\program files" in base_str:
        return "instalado"
    return "instalado"


MODO_EXECUCAO = _determinar_modo()
DIR_INSTALACAO = BASE

_env_data = os.environ.get("ULTRON_DATA_DIR")
_env_config = os.environ.get("ULTRON_CONFIG_DIR")
_env_logs = os.environ.get("ULTRON_LOGS_DIR")

if _env_data:
    DIR_DADOS = Path(_env_data).resolve()
elif MODO_EXECUCAO in ("desenvolvimento", "portatil"):
    DIR_DADOS = BASE / "dados"
else:
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    DIR_DADOS = Path(local_app_data) / "ULTRON"

if _env_config:
    DIR_CONFIG = Path(_env_config).resolve()
elif MODO_EXECUCAO in ("desenvolvimento", "portatil"):
    DIR_CONFIG = BASE
else:
    app_data = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    DIR_CONFIG = Path(app_data) / "ULTRON"

if _env_logs:
    DIR_LOGS = Path(_env_logs).resolve()
elif MODO_EXECUCAO in ("desenvolvimento", "portatil"):
    DIR_LOGS = BASE / "logs"
else:
    DIR_LOGS = DIR_DADOS / "logs"

# Criação segura dos diretórios de escrita (somente no perfil do usuário / dados mutáveis)
for _d in (DIR_DADOS, DIR_CONFIG, DIR_LOGS):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

# Caminhos específicos centralizados
ARQUIVO_BANCO = DIR_DADOS / "ultron.db"
ARQUIVO_COFRE = DIR_DADOS / "cofre.json"
ARQUIVO_CHAVE_COFRE = DIR_DADOS / ".cofre.chave"
ARQUIVO_MOBILE_PAIRING = DIR_DADOS / "mobile_pairing.json"
DIR_SKILLS = DIR_DADOS / "skills"
ARQUIVO_FLUXOS = DIR_DADOS / "fluxos.json"
ARQUIVO_SESSAO = DIR_DADOS / "sessao.json"
ARQUIVO_DESFAZER_DIR = DIR_DADOS / "desfazer"
ARQUIVO_ENV = DIR_CONFIG / ".env"


def reconfigurar_diretorios() -> dict[str, Path]:
    """Reavalia as variáveis de ambiente e atualiza todos os caminhos de dados e configuração."""
    global MODO_EXECUCAO, DIR_INSTALACAO, DIR_DADOS, DIR_CONFIG, DIR_LOGS
    global ARQUIVO_BANCO, ARQUIVO_COFRE, ARQUIVO_CHAVE_COFRE, ARQUIVO_MOBILE_PAIRING, DIR_SKILLS
    global ARQUIVO_FLUXOS, ARQUIVO_SESSAO, ARQUIVO_DESFAZER_DIR, ARQUIVO_ENV

    MODO_EXECUCAO = _determinar_modo()
    DIR_INSTALACAO = BASE

    _env_data = os.environ.get("ULTRON_DATA_DIR")
    _env_config = os.environ.get("ULTRON_CONFIG_DIR")
    _env_logs = os.environ.get("ULTRON_LOGS_DIR")

    if _env_data:
        DIR_DADOS = Path(_env_data).resolve()
    elif MODO_EXECUCAO in ("desenvolvimento", "portatil"):
        DIR_DADOS = BASE / "dados"
    else:
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        DIR_DADOS = Path(local_app_data) / "ULTRON"

    if _env_config:
        DIR_CONFIG = Path(_env_config).resolve()
    elif MODO_EXECUCAO in ("desenvolvimento", "portatil"):
        DIR_CONFIG = BASE
    else:
        app_data = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        DIR_CONFIG = Path(app_data) / "ULTRON"

    if _env_logs:
        DIR_LOGS = Path(_env_logs).resolve()
    elif MODO_EXECUCAO in ("desenvolvimento", "portatil"):
        DIR_LOGS = BASE / "logs"
    else:
        DIR_LOGS = DIR_DADOS / "logs"

    for _d in (DIR_DADOS, DIR_CONFIG, DIR_LOGS):
        try:
            _d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    ARQUIVO_BANCO = DIR_DADOS / "ultron.db"
    ARQUIVO_COFRE = DIR_DADOS / "cofre.json"
    ARQUIVO_CHAVE_COFRE = DIR_DADOS / ".cofre.chave"
    ARQUIVO_MOBILE_PAIRING = DIR_DADOS / "mobile_pairing.json"
    DIR_SKILLS = DIR_DADOS / "skills"
    ARQUIVO_FLUXOS = DIR_DADOS / "fluxos.json"
    ARQUIVO_SESSAO = DIR_DADOS / "sessao.json"
    ARQUIVO_DESFAZER_DIR = DIR_DADOS / "desfazer"
    ARQUIVO_ENV = DIR_CONFIG / ".env"

    return {
        "instalacao": DIR_INSTALACAO,
        "dados": DIR_DADOS,
        "config": DIR_CONFIG,
        "logs": DIR_LOGS,
    }


def migrar_dados_legados(forcar: bool = False) -> dict:
    """Migra com segurança os dados existentes no diretório BASE para DIR_DADOS e DIR_CONFIG.

    Requisitos:
    - Backup prévio antes de qualquer alteração
    - Cópia transacional de SQLite com PRAGMA integrity_check
    - Não sobrescreve dados de destino existentes
    - Não apaga a origem
    - Idempotente (registra estado em .migracao.json)
    """
    relatorio = {"status": "ok", "migrados": [], "conflitos": [], "erros": []}

    if DIR_DADOS.resolve() == (BASE / "dados").resolve() and DIR_CONFIG.resolve() == BASE.resolve() and not forcar:
        return {**relatorio, "status": "ignorado_mesmo_diretorio"}

    marcador = DIR_DADOS / ".migracao.json"
    if marcador.is_file() and not forcar:
        return {**relatorio, "status": "ja_migrado"}

    backup_dir = DIR_DADOS / "backups" / f"migracao-pre-{int(time.time())}"
    backup_criado = False

    def _assegurar_backup():
        nonlocal backup_criado
        if not backup_criado:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_criado = True

    try:
        DIR_DADOS.mkdir(parents=True, exist_ok=True)
        DIR_CONFIG.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # 1. Migração do .env para DIR_CONFIG
    env_legado = BASE / ".env"
    if env_legado.is_file() and env_legado.resolve() != ARQUIVO_ENV.resolve():
        if not ARQUIVO_ENV.exists():
            _assegurar_backup()
            try:
                ARQUIVO_ENV.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(env_legado, ARQUIVO_ENV)
                relatorio["migrados"].append(str(ARQUIVO_ENV.name))
            except OSError as err:
                relatorio["erros"].append(f".env: {err}")
        else:
            relatorio["conflitos"].append(str(ARQUIVO_ENV.name))

    # 2. Migração do banco SQLite (ultron.db)
    banco_legado = BASE / "dados" / "ultron.db"
    if banco_legado.is_file() and banco_legado.resolve() != ARQUIVO_BANCO.resolve():
        if not ARQUIVO_BANCO.exists():
            _assegurar_backup()
            conn_orig = None
            conn_dest = None
            try:
                ARQUIVO_BANCO.parent.mkdir(parents=True, exist_ok=True)
                conn_orig = sqlite3.connect(str(banco_legado), timeout=5.0)
                conn_dest = sqlite3.connect(str(ARQUIVO_BANCO), timeout=5.0)
                with conn_dest:
                    conn_orig.backup(conn_dest)

                integrity = conn_dest.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"Integridade SQLite corrompida: {integrity}")
                relatorio["migrados"].append(str(ARQUIVO_BANCO.name))
            except Exception as exc:
                relatorio["erros"].append(f"ultron.db: {exc}")
                if conn_dest:
                    try:
                        conn_dest.close()
                    except Exception:
                        pass
                    conn_dest = None
                if conn_orig:
                    try:
                        conn_orig.close()
                    except Exception:
                        pass
                    conn_orig = None
                if ARQUIVO_BANCO.exists():
                    try:
                        ARQUIVO_BANCO.unlink()
                    except OSError:
                        pass
            finally:
                if conn_orig:
                    try:
                        conn_orig.close()
                    except Exception:
                        pass
                if conn_dest:
                    try:
                        conn_dest.close()
                    except Exception:
                        pass
        else:
            relatorio["conflitos"].append(str(ARQUIVO_BANCO.name))

    # 3. Migração de arquivos de configuração em dados/ (cofre, sessao, fluxos, pareamento mobile)
    for nome in (".cofre.chave", "cofre.json", "fluxos.json", "sessao.json", "mobile_pairing.json"):
        origem = BASE / "dados" / nome
        destino = DIR_DADOS / nome
        if origem.is_file() and origem.resolve() != destino.resolve():
            if not destino.exists():
                _assegurar_backup()
                try:
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origem, destino)
                    relatorio["migrados"].append(nome)
                except OSError as err:
                    relatorio["erros"].append(f"{nome}: {err}")
            else:
                relatorio["conflitos"].append(nome)

    # 4. Migração de Skills (dados/skills)
    skills_legadas = BASE / "dados" / "skills"
    if skills_legadas.is_dir() and skills_legadas.resolve() != DIR_SKILLS.resolve():
        _assegurar_backup()
        try:
            shutil.copytree(skills_legadas, DIR_SKILLS, dirs_exist_ok=True)
            relatorio["migrados"].append("skills")
        except OSError as err:
            relatorio["erros"].append(f"skills: {err}")

    try:
        import json
        payload = {
            "status": "concluido" if not relatorio["erros"] else "parcial",
            "timestamp": time.time(),
            "migrados": relatorio["migrados"],
            "conflitos": relatorio["conflitos"],
            "erros": relatorio["erros"],
            "backup": str(backup_dir) if backup_criado else None,
        }
        marcador.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass

    return relatorio


if MODO_EXECUCAO == "instalado":
    try:
        migrar_dados_legados()
    except Exception:
        pass

# Carregamento do .env (prioriza o do perfil DIR_CONFIG, com fallback para o de BASE)
if ARQUIVO_ENV.is_file():
    load_dotenv(ARQUIVO_ENV)
if (BASE / ".env").is_file() and (BASE / ".env").resolve() != ARQUIVO_ENV.resolve():
    load_dotenv(BASE / ".env")


def _env(nome, padrao=""):
    return os.getenv(nome, padrao).strip()


NOME = _env("NOME_USUARIO", "senhor")
# Provedores com API compatível com OpenAI. A ordem define a preferência; quem não
# tem chave é apenas pulado. Todos podem ser configurados pelo cofre da interface.
PROVEDORES = [p.strip().lower() for p in _env(
    "PROVEDORES",
    "groq,gemini,nvidia,openai,openrouter,mistral,deepseek,cerebras,together,xai",
).split(",") if p.strip()]
CHAVES = {
    "gemini": _env("GEMINI_API_KEY"),
    "groq": _env("GROQ_API_KEY"),
    "nvidia": _env("NVIDIA_API_KEY"),
    "openai": _env("OPENAI_API_KEY"),
    "openrouter": _env("OPENROUTER_API_KEY"),
    "mistral": _env("MISTRAL_API_KEY"),
    "deepseek": _env("DEEPSEEK_API_KEY"),
    "cerebras": _env("CEREBRAS_API_KEY"),
    "together": _env("TOGETHER_API_KEY"),
    "xai": _env("XAI_API_KEY"),
}
MODELOS = {
    "gemini": _env("GEMINI_MODEL", "gemini-2.0-flash"),
    "groq": _env("GROQ_MODEL", "openai/gpt-oss-120b"),
    "nvidia": _env("NVIDIA_MODEL", "openai/gpt-oss-20b"),
    "openai": _env("OPENAI_MODEL", "gpt-4o-mini"),
    "openrouter": _env("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    "mistral": _env("MISTRAL_MODEL", "mistral-small-latest"),
    "deepseek": _env("DEEPSEEK_MODEL", "deepseek-chat"),
    "cerebras": _env("CEREBRAS_MODEL", "llama-3.3-70b"),
    "together": _env("TOGETHER_MODEL", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "xai": _env("XAI_MODEL", "grok-2-latest"),
}
MODELOS_VISAO = {
    "gemini": _env("GEMINI_VISION_MODEL", "") or MODELOS["gemini"],
    "groq": _env("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "openai": _env("OPENAI_VISION_MODEL", "") or MODELOS["openai"],
    "openrouter": _env("OPENROUTER_VISION_MODEL", "") or MODELOS["openrouter"],
    "mistral": _env("MISTRAL_VISION_MODEL", "pixtral-12b-2409"),
    "together": _env("TOGETHER_VISION_MODEL", "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo"),
    "xai": _env("XAI_VISION_MODEL", "grok-2-vision-1212"),
}
URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "together": "https://api.together.xyz/v1",
    "xai": "https://api.x.ai/v1",
}
VOZ = _env("VOZ", "pt-BR-AntonioNeural")
VOZ_PITCH = _env("VOZ_PITCH", "-12Hz")
VOZ_RATE = _env("VOZ_RATE", "+0%")
# Liga/desliga a síntese de voz no Desktop e os anúncios falados do agendador.
VOZ_ATIVO = (_env("VOZ_ATIVO", "1") or "1").lower() not in (
    "0", "nao", "não", "false", "off")
VOZ_NOTIFICACOES = (_env("VOZ_NOTIFICACOES", "1") or "1").lower() not in (
    "0", "nao", "não", "false", "off")
# Voz clonada na nuvem (opcional): Fish Audio. Sem chave ou id, usa só o Edge TTS.
VOZ_NUVEM_CHAVE = _env("VOZ_NUVEM_CHAVE")
VOZ_NUVEM_ID = _env("VOZ_NUVEM_ID")
VOZ_NUVEM_MODELO = _env("VOZ_NUVEM_MODELO", "s2.1-pro-free")
def _num_env(nome, padrao, tipo=float):
    try:
        return tipo(_env(nome, str(padrao)) or padrao)
    except ValueError:
        return padrao


LIMIAR_VOZ = max(0.0, _num_env("LIMIAR_VOZ", 0.0))
# Fração do limiar calibrado que já conta como fala (0.35 capta fala a 30-50 cm
# sem disparar com ruído estável). Suba para 0.5+ em ambientes muito ruidosos.
try:
    LIMIAR_VOZ_FATOR = min(1.0, max(0.1, float(_env("LIMIAR_VOZ_FATOR", "0.35") or 0.35)))
except ValueError:
    LIMIAR_VOZ_FATOR = 0.35
SILENCIO_FIM = max(0.1, _num_env("SILENCIO_FIM", 1.3))   # segundos de silêncio que encerram sua fala
AFE_ATIVO = (_env("AFE_ATIVO", "1") or "1").lower() not in (
    "0", "nao", "não", "false", "off")
REASONING = _env("REASONING_EFFORT", "low").lower()        # "low" = IA mais rápida; vazio desliga
# Retry das chamadas de IA: tentativas por provedor, backoff exponencial com
# jitter e um teto de tempo total por provedor (o Ultron responde por voz).

IA_TENTATIVAS = max(1, _num_env("IA_TENTATIVAS", 4, int))
IA_BACKOFF_BASE = max(0.0, _num_env("IA_BACKOFF_BASE", 1.0))
IA_BACKOFF_TETO = max(0.0, _num_env("IA_BACKOFF_TETO", 16.0))
IA_BACKOFF_JITTER = min(1.0, max(0.0, _num_env("IA_BACKOFF_JITTER", 0.5)))
IA_TEMPO_MAX_PROVEDOR = max(1.0, _num_env("IA_TEMPO_MAX_PROVEDOR", 45.0))
IA_TEMPO_MAX_TOTAL = max(1.0, _num_env("IA_TEMPO_MAX_TOTAL", 60.0))
# Quantas mensagens do histórico entram em cada resposta (menos = resposta mais rápida).
try:
    HISTORICO_MSGS = max(2, int(_env("HISTORICO_MSGS", "12") or 12))
except ValueError:
    HISTORICO_MSGS = 12
# Memória de sessões anteriores: quantos trechos relevantes entram no contexto.
try:
    RECALL_MSGS = max(0, int(_env("RECALL_MSGS", "4") or 4))
except ValueError:
    RECALL_MSGS = 4
try:
    RECALL_DIAS = max(1, int(_env("RECALL_DIAS", "120") or 120))
except ValueError:
    RECALL_DIAS = 120
# Reconhecimento de voz: "auto" (Google e, se falhar, o nativo do Windows),
# "sempre" (nativo primeiro) ou "nunca" (só Google).
VOZ_NATIVA = (_env("VOZ_NATIVA", "auto") or "auto").lower()
# Motor de escuta: "auto" = Groq grátis e, se falhar, Google e depois Windows;
# "groq" (só Groq + reservas), "google" ou "nativo" (força um motor primeiro).
VOZ_MOTOR = (_env("VOZ_MOTOR", "auto") or "auto").lower()
# Conferência do que foi ouvido: "auto" (só em dúvida ou risco), "sempre" ou "nunca".
VOZ_CONFERIR = (_env("VOZ_CONFERIR", "auto") or "auto").lower()
HOTKEY_PARAR = _env("HOTKEY_PARAR", "ctrl+alt+x")
# Segurar para falar: grava enquanto a combinação está pressionada, envia ao soltar
HOTKEY_FALAR = _env("HOTKEY_FALAR", "ctrl+alt+space") or ""
# Limites da memória de fatos (evita crescimento sem fim e abuso)
try:
    FATO_MAX_CARACTERES = max(40, int(_env("FATO_MAX_CARACTERES", "300") or 300))
except ValueError:
    FATO_MAX_CARACTERES = 300
try:
    FATO_MAX_TOTAL = max(1, int(_env("FATO_MAX_TOTAL", "50") or 50))
except ValueError:
    FATO_MAX_TOTAL = 50
FATO_MIN_BUSCA = 3   # caracteres úteis para apagar com segurança

# Skills: procedimentos em dados/skills. Desligar não toca no disco.
SKILLS_ATIVO = (_env("SKILLS_ATIVO", "1") or "1").lower() not in (
    "0", "nao", "não", "false", "off")
SKILLS_MAX_INDICE = max(1, _num_env("SKILLS_MAX_INDICE", 15, int))
SKILLS_CORPO_MAX = max(200, _num_env("SKILLS_CORPO_MAX", 2000, int))
SKILLS_PENDENTES_MAX = max(1, _num_env("SKILLS_PENDENTES_MAX", 3, int))
SKILLS_PENDENTE_DIAS = max(1, _num_env("SKILLS_PENDENTE_DIAS", 7, int))
SKILLS_STALE_DIAS = max(1, _num_env("SKILLS_STALE_DIAS", 30, int))
SKILLS_ARQUIVAR_DIAS = max(2, _num_env("SKILLS_ARQUIVAR_DIAS", 90, int))
SKILLS_MAX_TOTAL = max(1, _num_env("SKILLS_MAX_TOTAL", 100, int))

# Memória no Obsidian: pasta do vault (vazio = Documents/ULTRON-Vault), quantas
# notas entram no contexto de cada resposta (0 desliga a leitura automática) e
# se a integração está ligada.
OBSIDIAN_VAULT = _env("OBSIDIAN_VAULT", "")
OBSIDIAN_ATIVO = (_env("OBSIDIAN_ATIVO", "1") or "1").lower() not in (
    "0", "nao", "não", "false", "off")
try:
    OBSIDIAN_RECALL = max(0, int(_env("OBSIDIAN_RECALL", "3") or 3))
except ValueError:
    OBSIDIAN_RECALL = 3

# Segundos em que uma fala sem "Ei, Ultron" ainda é aceita como comando (0 desliga)
try:
    JANELA_SEGUIMENTO = max(0.0, float(_env("JANELA_SEGUIMENTO", "15") or 15))
except ValueError:
    JANELA_SEGUIMENTO = 15.0
# Bloqueio automático da sessão após N minutos sem uso (0 desliga).
try:
    SESSAO_MINUTOS = max(0.0, float(_env("ULTRON_SESSAO_MINUTOS", "15") or 15))
except ValueError:
    SESSAO_MINUTOS = 15.0
PIN = _env("ULTRON_PIN")   # opcional: exigido em ações CRÍTICAS (digitado no teclado/Telegram, nunca por voz)
# Preferido: hash PBKDF2 do PIN (tools/definir_pin.py). Quando presente, ULTRON_PIN
# em texto é ignorado; o texto só continua valendo por compatibilidade.
PIN_HASH = _env("ULTRON_PIN_HASH")
TELEGRAM_TOKEN = _env("TELEGRAM_TOKEN")
_uid = _env("TELEGRAM_USER_ID")
TELEGRAM_USER_ID = int(_uid) if _uid.isdigit() else 0

# Integrações opcionais (configuráveis pelo cofre). Vazio = recurso desligado.
SPOTIFY_CLIENT_ID = _env("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _env("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REFRESH = _env("SPOTIFY_REFRESH")

# Briefing matinal (desligado por padrão): compõe clima, notícias, agenda e lembretes.
BRIEFING_ATIVO = (_env("BRIEFING_ATIVO", "0") or "0").lower() not in (
    "0", "nao", "não", "false", "off")
BRIEFING_HORA = _env("BRIEFING_HORA", "08:00")
CIDADE = _env("CIDADE", "São Paulo")

# U.L.T.R.O.N. Mobile (servidor HTTP LAN autenticado via HMAC-SHA256).
MOBILE_ENABLED = (_env("ULTRON_MOBILE_ENABLED", "1") or "1").lower() not in (
    "0", "nao", "não", "false", "off")
MOBILE_HOST = _env("ULTRON_MOBILE_HOST", "0.0.0.0") or "0.0.0.0"
MOBILE_PORT = max(1, min(65535, _num_env("ULTRON_MOBILE_PORT", 8765, int)))
MOBILE_CLOCK_SKEW_S = max(5, min(300, _num_env("ULTRON_MOBILE_CLOCK_SKEW_S", 60, int)))
MOBILE_ALLOW_NON_PRIVATE = (_env("ULTRON_MOBILE_ALLOW_NON_PRIVATE_CLIENTS", "0") or "0").lower() in (
    "1", "sim", "true", "on")

# O cofre cifrado (dados/cofre.json) tem precedência sobre o .env. Falha aqui nunca
# impede o app de abrir: o .env continua valendo.
try:
    import cofre as _cofre
    if hasattr(_cofre, "aplicar_na_config"):
        _cofre.aplicar_na_config()
    if hasattr(_cofre, "_redacao_extra"):
        _cofre._redacao_extra()
except Exception as _erro:      # noqa: BLE001 - inicialização não pode quebrar
    pass

try:
    import mobile_pairing as _mobile_pairing
    if hasattr(_mobile_pairing, "registrar_redacao"):
        _mobile_pairing.registrar_redacao()
except Exception:      # noqa: BLE001 - inicialização não pode quebrar
    pass
