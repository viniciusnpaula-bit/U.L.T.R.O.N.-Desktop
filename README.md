# U.L.T.R.O.N. Desktop

Assistente pessoal para Windows: conversa por voz, age no PC e **nunca age sem você** —
toda ação sensível passa por confirmação e, nas críticas, por PIN.

Interface 2.0: uma câmara com o núcleo animado no centro, o bate-papo de voz à esquerda,
os eventos à direita e uma única linha de comando.

## Instalar

1. Python 3.12+ (64 bits) e Node.js LTS instalados.
2. Baixe o ZIP do [último Release](../../releases/latest) e extraia para uma pasta simples,
   por exemplo `C:\ultron`.
3. Execute **`ULTRON-Setup.exe`**. Não precisa de administrador.

O instalador confere a pasta antes de mexer em qualquer coisa, cria o ambiente Python
isolado, instala o Electron, cria o atalho e verifica tudo no final. Rodar de novo
**repara** sem reinstalar tudo. Log em `logs\setup.log`.

Para remover: `ULTRON-Setup.exe --uninstall` (mantém suas chaves e a memória).
Diagnóstico sem abrir o painel: `ULTRON.exe --diagnostico`.

## Primeiro uso

O instalador cria o `.env`. Cole uma chave de IA — a do
[Gemini](https://aistudio.google.com/apikey) é gratuita:

```ini
GEMINI_API_KEY=
PROVEDORES=groq,gemini,nvidia,openai,openrouter,mistral,deepseek,cerebras,together,xai
```

Depois de abrir, outras plataformas podem ser adicionadas em **Ajustes › Chaves de
API**: OpenAI, OpenRouter, Mistral, DeepSeek, Cerebras, Together AI e xAI (Grok),
cada uma com o link oficial para criar a chave.

Sem chave o ULTRON avisa e não inicia; configure pelo menos uma no `.env`.
Diga **“Ei, Ultron”** seguido do comando.

## Atualizações

Ajustes (`Ctrl+,`) → **verificar atualização**. O ULTRON consulta o último Release
deste repositório, baixa o pacote, confere o SHA-256 publicado e aplica com backup e
rollback automático. Dados, chaves e ambiente Python nunca são tocados.

A partir da 1.9.9 cada Release é **assinado** (Ed25519). O app só aplica a
atualização se a assinatura do `SHA256SUMS.txt` for válida — o SHA-256 sozinho não
provava origem, só integridade. A chave pública fica embutida em `atualizacao.py`;
a privada nunca entra no repositório (fica em `%USERPROFILE%\.ultron-signing`).

> **Primeira versão assinada**: instale a 1.9.9 (ou superior) manualmente uma vez.
> As versões anteriores não conhecem a chave pública e recusariam o pacote.

Cada Release precisa de três arquivos:

1. `ULTRON-Desktop-vX.Y.Z.zip`
2. `SHA256SUMS.txt` com o hash do ZIP
3. `SHA256SUMS.txt.sig` — assinatura Ed25519 do SUMS (`python tools/gerar_chaves.py`
   cria a chave; `python tools/publicar.py` assina e envia)

Gere os dois com `python tools/build_setup.py --zip`.

## Desenvolvimento

```bash
python -m pytest tests -q            # suíte local (68 testes)
python tools/make_icon.py            # regera ULTRON.ico a partir da arte
python tools/build_setup.py --zip    # compila ULTRON.exe, ULTRON-Setup.exe e o ZIP
python launcher.py --doctor          # diagnóstico
```

Estrutura:

| pasta | o que é |
|---|---|
| `electron/site/` | interface (HTML/CSS/JS, sem framework) |
| `electron/` | shell Electron: janela, ponte IPC, janela flutuante |
| `desktop_api.py` | API local só em 127.0.0.1, com token por sessão |
| `desktop_runtime.py` | núcleo: voz, comandos, eventos, bate-papo, atualização |
| `cerebro.py`, `ferramentas.py` | IA e ferramentas que agem no PC |
| `seguranca.py`, `permissoes.json` | riscos, confirmações, PIN, allowlist |
| `installer/`, `tools/` | instalador e build |
| `ULTRON-Mobile/` | app Android (projeto anterior, independente) |

## Segurança

Nenhuma saída da IA autoriza ação: intenções passam pela política local, ações críticas
pedem PIN (nunca por voz), e o gateway falha fechado. A chave de IA fica só no `.env`
local — nunca no código, no histórico ou no APK.
