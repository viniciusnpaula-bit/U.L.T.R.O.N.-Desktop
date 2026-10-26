"""Configurações lidas do arquivo .env"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
for _d in ("logs", "dados"):
    (BASE / _d).mkdir(exist_ok=True)


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
LIMIAR_VOZ = float(_env("LIMIAR_VOZ", "0") or 0)
SILENCIO_FIM = float(_env("SILENCIO_FIM", "0.5") or 0.5)   # segundos de silêncio que encerram sua fala
REASONING = _env("REASONING_EFFORT", "low").lower()        # "low" = IA mais rápida; vazio desliga
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
HOTKEY_PARAR = _env("HOTKEY_PARAR", "ctrl+alt+x")
# Segurar para falar: grava enquanto a combinação está pressionada, envia ao soltar
HOTKEY_FALAR = _env("HOTKEY_FALAR", "ctrl+alt+espaco") or ""
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

# Segundos em que uma fala sem "Ei, Ultron" ainda é aceita como comando (0 desliga)
try:
    JANELA_SEGUIMENTO = max(0.0, float(_env("JANELA_SEGUIMENTO", "6") or 6))
except ValueError:
    JANELA_SEGUIMENTO = 6.0
PIN = _env("ULTRON_PIN")   # opcional: exigido em ações CRÍTICAS (digitado no teclado/Telegram, nunca por voz)
TELEGRAM_TOKEN = _env("TELEGRAM_TOKEN")
_uid = _env("TELEGRAM_USER_ID")
TELEGRAM_USER_ID = int(_uid) if _uid.isdigit() else 0

# O cofre cifrado (dados/cofre.json) tem precedência sobre o .env. Falha aqui nunca
# impede o app de abrir: o .env continua valendo.
try:
    import cofre as _cofre
    _cofre.aplicar_na_config()
    _cofre._redacao_extra()
except Exception as _erro:      # noqa: BLE001 - inicialização não pode quebrar
    print(f"[cofre] não foi possível aplicar as chaves guardadas ({type(_erro).__name__})")
