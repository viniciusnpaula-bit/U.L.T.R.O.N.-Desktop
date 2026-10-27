# Auditoria — U.L.T.R.O.N. Desktop (Fase 1)

Data: 2026-10-22 · Versão em trabalho: **1.10.0** (branch `main` local, 4 commits à frente do último Release publicado v1.9.8)

Este documento é a **referência de funcionamento** usada para verificar as fases seguintes.
Ele descreve o que o código faz hoje, o que a documentação promete, e as diferenças entre os dois.

---

## 1. Estrutura real

| Camada | Módulo | Papel |
|---|---|---|
| Interface | `electron/main.js`, `preload.js`, `mini-preload.js` | janela, ponte IPC restrita a rotas nomeadas |
| Interface | `electron/site/` (`index.html`, `app.js`, `style.css`, `src/orb.js`, `zoom-lock.js`, `mini-hud.*`) | câmara do núcleo, bate-papo, eventos, barra de sistema |
| API local | `desktop_api.py` | loopback `127.0.0.1:3900`, token por sessão, `X-ULTRON-Token`, CORS/Origin fechados |
| Núcleo | `desktop_runtime.py` | ciclo de vida, filas de comando/evento, microfone, atualizações, bate-papo |
| Cérebro | `cerebro.py` | provedores (Gemini/Groq/NVIDIA), ferramentas, streaming de frases, visão |
| Ferramentas | `ferramentas.py` | 30 ferramentas registradas, todas pelo portão `ferramentas.executar` |
| Segurança | `seguranca.py`, `permissoes.json`, `confirmacao.py` | risco, allowlist, confirmação, PIN, logs, parada de emergência |
| Memória | `memoria.py` (SQLite `dados/ultron.db`) | mensagens, fatos, lembretes |
| Voz | `voz.py` | captura (`sounddevice`), reconhecimento (`SpeechRecognition`/Google), TTS (`edge-tts` → `pyttsx3`) |
| Empacotamento | `installer/`, `tools/build_setup.py`, `tools/publicar.py`, `assinatura.py` | `ULTRON.exe`, `ULTRON-Setup.exe`, ZIP assinado (Ed25519) |

---

## 2. Inventário por recurso (verificado no código)

### Interface
- Núcleo em canvas (`criarOrbe`): energia ligada ao estado real do núcleo; **não gira continuamente** (rotação lenta só sob atividade).
- Bate-papo de voz, fita de eventos, linha de comando única, barra de sistema com 3 barras recolhíveis (`Ctrl+1`, `Ctrl+2`, `Ctrl+,`).
- Temas ULTRON/JARVIS/VISÃO/EDITH trocam `--core`; logo oficial intocada.
- Zoom desligado por decisão de projeto (`zoom-lock.js` + main).
- Ajustes: temas, microfone (listar/aplicar), canal local, atualização em 3 passos.

### Núcleo / voz
- Escuta contínua com palavra de ativação ("Ei, Ultron"), janela de seguimento (`JANELA_SEGUIMENTO`, 6 s), confirmação por voz para ações de risco.
- Estados publicados: `iniciando`, `calibrando`, `ouvindo`, `processando`, `pausado`, `erro`, `encerrado`.
- Streaming: `cerebro.processar_stream()` + `voz.falar_partes()` (1ª frase falada antes do fim da geração).
- "Segurar para falar": `HOTKEY_FALAR` (padrão `ctrl+alt+space`) → `voz.Ouvido.escutar_manual()`.
- TTS: Edge TTS online com reserva local `pyttsx3`; interrupção por `voz.parar_fala`; eco tratado com pausa.

### Ferramentas (30)
clima, notícias, busca web, YouTube, abrir site, minimizar janelas, fechar aplicativo, abrir programa/jogo,
listar jogos, listar pasta, ler arquivo, criar arquivo, criar pasta, mover, procurar, apagar (lixeira),
digitar, pressionar tecla, clicar, print + análise, volume, mídia, info do PC, bloquear tela,
comando de diagnóstico, desligar/reiniciar/cancelar, lembrar/esquecer fato, criar/listar lembretes.

### Segurança
- `permissoes.json`: níveis (`baixo/medio/alto/critico`), allowlist de programas, diretórios, operações e comandos.
- Ações `CRITICO` exigem PIN (`ULTRON_PIN`), nunca por voz.
- Toda ferramenta passa por `ferramentas.executar`; não há caminho alternativo.
- Logs em `logs/ultron.log` e `logs/seguranca.log`, com redação de chaves/PIN.
- Parada de emergência: `Ctrl+Alt+X` e comando de parada.

### Memória
- `mensagens` (histórico 16), `fatos` (limite 50 × 300 chars), `lembretes`.
- `LIKE` escapado (`ESCAPE '\'`), mínimo de 3 caracteres úteis para apagar.

### API local
`GET /health`, `/status`, `/events`, `/conversation`, `/microphones`, `/update`, `/update/check`;
`POST /commands`, `/microphone`, `/microphone/device`, `/confirmations`, `/emergency-stop`,
`/update/apply`, `/update/launch`, `/update/rollback`, `/shutdown`.

### Empacotamento
- `tools/build_setup.py` gera `ULTRON.exe` (launcher windowed), `ULTRON-Setup.exe` e o ZIP; o ícone vem só de `electron/assets/ULTRON.ico`.
- ZIP inclui código, assets e binários; exclui `.env`, `dados/`, `logs/`, `venv/`, `node_modules/`, `__pycache__`, `ULTRON-Mobile/` e a prévia.
- Release assinado: `SHA256SUMS.txt` + `SHA256SUMS.txt.sig` (Ed25519, chave pública embutida).

---

## 3. Divergências documentação ↔ código (encontradas e corrigidas na 1.9.9)

| Documento dizia | Código fazia | Situação |
|---|---|---|
| Python 3.10+ no README e no instalador | `diagnostico.py` exigia 3.12 | **corrigido**: 3.12 em todos |
| "bat-papo" | "bate-papo" | **corrigido** |
| `NOTAS-RECONSTRUCAO.txt` | arquivo passou a `CHANGELOG.md` | **corrigido** |
| SKILL/README citavam `central de 7 páginas` | interface é uma câmara única | **corrigido** na 1.9.x |

Pendências conhecidas (não são defeitos, são recursos que **não existem**):
- Não há webcam, detecção de objetos, gestos, WhatsApp, vídeo, edição de imagem, automação de navegador, controle remoto.
- Não há notificação de lembretes com o app fechado.
- Não há VoiceStudio (a menção antiga no LEIA-ME foi removida).

---

## 4. Dependências, permissões e custos

| Item | Requisito | Custo |
|---|---|---|
| Python 3.12+ 64 bits, Node LTS | instalador | grátis |
| `openai`, `requests`, `python-telegram-bot`, `cryptography`, etc. | `requirements.txt` | grátis |
| Gemini API | chave grátis (limite diário) | grátis com limite |
| Groq / NVIDIA Build | chave | grátis com limite |
| Edge TTS | internet | grátis |
| PyInstaller | build local | grátis |
| Windows: microfone, tela, teclado global | permissões do Windows | — |
| Telegram (opcional) | bot + chat id | grátis |
| GitHub Release assinado | repo público | grátis |

---

## 5. Linha de base de verificação

Comandos e resultados no commit de trabalho (executados ao fim da Fase 1 anterior):

```
python -m unittest testes_seguranca          → 50 testes OK
python -m pytest tests -q                    → 77 passando
node --test electron/test/api.test.js        → 3 passando
node --test electron/site/test/real.test.mjs → 5 passando
python -m compileall -q . (sem venv/build)   → sem erros
node --check em todos os .js/.mjs            → sem erros
```

Toda fase seguinte deve manter esta linha verde e acrescentar seus próprios testes.
