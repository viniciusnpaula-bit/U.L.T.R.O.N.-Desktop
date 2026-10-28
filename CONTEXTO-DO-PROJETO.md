# U.L.T.R.O.N. Desktop — contexto completo do projeto

> **Versão do produto:** 1.19.0
> **Documento gerado em:** 28/10/2026
> **Objetivo deste arquivo:** dar a uma pessoa (ou a outra IA) todo o contexto
> necessário para entender, rodar, manter e evoluir o projeto sem depender do
> histórico da conversa que o produziu.
> **Escopo:** visão de produto, arquitetura, camadas, segurança, interface
> espacial 2.0, testes, processo de trabalho e estado atual da entrega.
> **Contém segredos?** Não. Nenhum valor de `.env`, token, PIN ou caminho de
> usuário é reproduzido aqui.

---

## 1. O que é o ULTRON

Assistente pessoal para Windows que conversa por voz e por texto, executa ações
no computador e **nunca age sem autorização** para o que é sensível.

- Fala e ouve em português do Brasil (Google STT, Groq Whisper e SAPI do Windows
  como alternativas; Edge TTS e pyttsx3 para falar).
- Responde com um modelo de linguagem escolhido entre vários provedores
  (Gemini, Groq, NVIDIA, OpenAI, OpenRouter, Mistral, DeepSeek, Cerebras,
  Together, xAI), com fallback e orçamento de tempo.
- Age no PC por ferramentas locais: arquivos, janelas, programas, hardware,
  navegador controlado, webcam/gestos, palco de mídia, lembretes, fluxos.
- Mantém memória local em SQLite, cifrada em repouso.
- Tem uma interface desktop própria (Electron + HTML/CSS/JS puro) e um HUD
  flutuante opcional.

A regra central do produto: **nenhuma saída da IA autoriza uma ação**. A
intenção passa por uma política local (`seguranca.py`), que decide
`ALLOW` / `CONFIRM` / `DENY`. Ações críticas pedem PIN (nunca por voz).

---

## 2. Princípios de projeto

1. **Local-first.** Chaves, memória, cofre, diário de desfazer e logs ficam no
   computador. A nuvem só recebe o necessário para o modelo responder.
2. **Fail-closed.** Sem chave, sem sessão, sem confirmação ou sem permissão, a
   ação não acontece. O gateway de segurança falha fechado.
3. **Dados reais, nunca simulados na tela.** A interface não inventa
   autenticação, telemetria, eventos, progresso ou diário. Se o núcleo não
   respondeu, a tela mostra “aguardando/offline”, não um estado fictício.
4. **Sem dependências novas na casca.** Renderer sem framework, sem bundler,
   sem CDN. CSP `script-src 'self'` intacta.
5. **Tudo que é sensível é explícito.** PIN, Hello, allowlist, caminhos
   protegidos, hosts permitidos e limites de tamanho são verificados no lado
   confiável (Python/Electron main), não no renderer.

---

## 3. Arquitetura em uma página

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ULTRON.exe / atalho  →  launcher.py  →  desktop.py                        │
│                                                                          │
│  Python: núcleo (main.py)          API local 127.0.0.1 (desktop_api.py)   │
│  ├─ voz / STT / TTS                ├─ token por sessão (≥32 chars)        │
│  ├─ cérebro (cerebro.py)           ├─ Host/Origin conferidos              │
│  ├─ ferramentas (ferramentas.py)   └─ rotas /api/v1/* limitadas           │
│  ├─ segurança (seguranca.py)                                             │
│  ├─ memória (memoria.py, SQLite cifrado)                                 │
│  ├─ desfazer (desfazer.py)                                               │
│  └─ palco (palco.py)                                                     │
│                              ▲                                           │
│                              │ IPC nomeado (preload.js)                  │
│  Electron main (main.js) ────┘  →  Renderer (electron/site/)             │
│  ├─ janela principal bloqueada por padrão                                │
│  ├─ HUD flutuante (mini-hud)                                             │
│  ├─ protocolo ultron-palco://                                            │
│  └─ powerMonitor: bloquear/suspender encerra a sessão                    │
└──────────────────────────────────────────────────────────────────────────┘
```

- **O Python é dono do estado.** O renderer só desenha o que a API devolve.
- **O renderer não fala HTTP.** `preload.js` expõe métodos nomeados; `api.js`
  (main) chama a API local com o token; `src/real.js` traduz eventos.
- **O palco** substitui o núcleo por vídeo, imagem, PDF, site ou texto, com id
  opaco em vez de caminho de arquivo.

---

## 4. Mapa de diretórios

| Caminho | O que é |
|---|---|
| `main.py` | Entrada do núcleo em modo voz/texto/bandeja; orquestra escuta e resposta. |
| `launcher.py` | Único ponto de entrada do atalho/`ULTRON.exe`; escolhe painel, texto, bandeja ou `--doctor`. |
| `desktop.py` | Sobe núcleo + API + Electron e derruba tudo ao fechar. |
| `desktop_runtime.py` | Ciclo de vida do painel, fila de eventos, comandos, sessão, voz, palco, atualização. |
| `desktop_api.py` | HTTP local autenticado, somente loopback. |
| `cerebro.py` | Conversa com os provedores, ferramentas, streaming e limites. |
| `ferramentas.py` | Catálogo de ferramentas que agem no PC (o maior módulo). |
| `seguranca.py` | Risco, allowlist, autorizador central, confirmações, PIN, logs. |
| `permissoes.json` | Política declarativa: níveis de confirmação, timeouts, allowlist. |
| `sessao.py` | Sessão local em memória (bloqueada até desbloqueio explícito). |
| `biometria.py` | Windows Hello (rosto/impressão/PIN do Windows). |
| `cofre.py` | Cofre de credenciais (DPAPI + AES-GCM). |
| `memoria.py` | SQLite: mensagens, fatos, lembretes; conteúdo cifrado (`v1:`). |
| `nuance.py` | Leitura local de tom (frustração, pressa, gratidão…). |
| `personalidade.py` | Perfis (ULTRON/JARVIS/VISÃO/EDITH), jeitos, dados do usuário. |
| `voz.py` / `voz_nativa.py` | Edge TTS/pyttsx3 e reconhecimento SAPI opcional. |
| `transcricao.py` | STT (Groq Whisper, Google, Windows) e VAD. |
| `fala.py` / `correcoes_voz.py` | Correção de palavras mal ouvidas e dicionário pessoal. |
| `arquivos.py` | ZIP seguro, organização de pastas, allowlist de caminhos. |
| `desfazer.py` | Diário local de inversas + Lixeira do Windows. |
| `palco.py` | Validação e estado do palco (mídia/site/texto). |
| `navegador.py` / `visao.py` | Playwright opcional e webcam/gestos (OpenCV). |
| `hardware.py` / `diagnostico.py` | Relatório de hardware e diagnóstico. |
| `atualizacao.py` / `assinatura.py` | Update assinado (Ed25519) com backup e rollback. |
| `telegram_bot.py` | Canal Telegram (pede PIN; não muda a política local). |
| `fluxos.py` | Fluxos/rotinas do usuário. |
| `electron/` | Shell Electron: janela, ponte IPC, HUD, protocolo do palco, testes. |
| `electron/site/` | Interface: HTML/CSS/JS sem framework, orbe, desbloqueio, prévia. |
| `tests/` | 43 arquivos de teste pytest (núcleo, API, segurança, voz, UI indireta). |
| `testes_seguranca.py` | Suíte de segurança standalone (58 verificações). |
| `installer/` | Instalador Python (`ultron_setup.py`). |
| `tools/` | Build, ícone, chaves de assinatura, publicação. |
| `.internal/` | Specs, planos e artefatos SDD (não versionado). |
| `dados/` | Banco, cofre, diário, preferências — **dado do usuário, não exportar**. |
| `logs/` | Logs locais. |
| `.env` | Chaves e configuração — **segredo, não exportar**. |

---

## 5. O caminho de uma ordem

1. **Entrada.** Voz (STT) ou texto no console da interface; o comando chega ao
   runtime.
2. **Intenção.** `cerebro.py` monta o prompt com memória, personalidade,
   autoconhecimento e o catálogo de ferramentas; o modelo escolhe uma
   ferramenta e argumentos.
3. **Política local.** `ferramentas.executar` é o único portão: classifica
   risco/operação/alvo e chama `seguranca.autorizar()`.
   - `ALLOW` → executa.
   - `CONFIRM` → pede confirmação (voz, teclado ou Telegram); crítico pede PIN.
   - `DENY` → recusa e registra o motivo.
4. **Execução.** A ferramenta age (arquivo, janela, palco, navegador…). Toda
   operação de arquivo reversível grava a inversa em `desfazer.py`.
5. **Resposta.** O texto volta ao runtime, que publica eventos e o turno da
   conversa; a interface desenha a resposta e o estado real.
6. **Auditoria.** Logs de segurança guardam decisão, alvo e motivo — nunca o
   PIN nem a chave de IA.

---

## 6. API local (`desktop_api.py`)

- Só aceita `127.0.0.1` (recusa qualquer outro host na criação).
- Exige `Host: 127.0.0.1:<porta>` e, se houver `Origin`, a origem local exata.
- Token aleatório por sessão, mínimo de 32 caracteres, comparado com
  `hmac.compare_digest` no header `X-ULTRON-Token`.
- Corpo JSON obrigatório, no máximo 8 KB; comando no máximo 4.000 caracteres.
- `PUT`, `DELETE` e `OPTIONS` respondem `405`.
- Porta preferida **3900**; se ocupada, escolhe uma porta livre do loopback.
- Respostas sempre `Cache-Control: no-store` e `Connection: close`.
- Nenhum log de acesso padrão (evita identificar caminhos/ids).

### Rotas `GET`

| Rota | Devolve |
|---|---|
| `/api/v1/health` | `{ok, version}` |
| `/api/v1/unlock` | estado da sessão, Hello, PIN configurado, irreversíveis, versão, histórico |
| `/api/v1/status` | snapshot do núcleo (CPU/RAM/disco, microfone, fala, sessão…) |
| `/api/v1/events` | fila de eventos desde o último poll |
| `/api/v1/microphones` | dispositivos e seleção atual |
| `/api/v1/voz` | vozes disponíveis e voz ativa |
| `/api/v1/cofre` | nomes de itens do cofre (nunca valores) |
| `/api/v1/fatos` | fatos memorizados |
| `/api/v1/fluxos` | fluxos do usuário |
| `/api/v1/lembretes` | lembretes |
| `/api/v1/personalidade` | perfil, jeito, tratamento, dados do usuário, saudação |
| `/api/v1/personalidade/previa` | trecho exato de personalidade enviado à IA |
| `/api/v1/update` / `update/check` | versão atual e resultado da checagem |
| `/api/v1/undo` | **somente leitura**: `{limite, itens:[{id, operacao, resumo, desfeito, criado}]}` ou `indisponivel` |
| `/api/v1/conversation` | turnos da sessão de bate-papo |

### Rotas `POST`

`unlock` (hello/pin) · `lock` · `commands` · `microphone` ·
`microphone/device` · `confirmations` · `emergency-stop` · `palco/fechar` ·
`voz` · `voz/restaurar` · `voz/testar` · `microfone/testar` · `fluxos` ·
`lembretes` · `fatos` · `personalidade` · `personalidade/restaurar` ·
`update/apply` · `update/launch` · `update/rollback` ·
`conversation/clear` · `shutdown`.

Cada rota valida o conjunto exato de campos antes de chamar o runtime.

---

## 7. Shell Electron

| Arquivo | Papel |
|---|---|
| `electron/main.js` | Janela principal, HUD, IPC, protocolo do palco, powerMonitor, permissões de câmera. |
| `electron/preload.js` | Ponte nomeada (`window.ultron.*`); nada de rota livre. |
| `electron/mini-preload.js` | Ponte mínima do HUD. |
| `electron/api.js` | Cliente HTTP local com token; falha fechado. |
| `electron/links.js` | Validação de links externos (http/https público, sem IP privado). |
| `electron/palco-protocol.js` | Esquema `ultron-palco://` para mídia local com id opaco. |

### Garantias de segurança do shell

- `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`.
- `will-navigate` bloqueado e `setWindowOpenHandler` nega novas janelas.
- Todo `ipcMain.handle` confere `isSender(event, mainWindow)` (ou `miniWindow`
  para o HUD) — outro renderer não consegue chamar a ponte.
- `powerMonitor` em `lock-screen` e `suspend` encerra a sessão local e avisa a
  interface; a tela volta ao desbloqueio.
- Permissão de câmera só para `video` na janela principal, nunca `audio`.
- O renderer recebe apenas o necessário: a interface nunca vê o token da API,
  o PIN ou caminhos absolutos do palco.

### HUD flutuante

`mini-hud.html` é uma janela pequena, sempre no topo, que **não** inicia outro
microfone nem outro cliente de API: recebe snapshots publicados pela janela
principal e devolve apenas os verbos permitidos. Roda o orbe no modo 2D (mais
leve e legível no tamanho reduzido).

---

## 8. Interface espacial 2.0 (entrega 2026-10-27/28)

### 8.1 Casca

`electron/site/index.html` (181 IDs únicos) organiza a tela em:

```
.stage
├─ header.bridge        identidade, versão, sinais, tema
├─ main.arena
│  ├─ aside#drawerChat  dock esquerdo: bate-papo (voz + texto)
│  ├─ section#chamber   câmara: núcleo 3D/2D, estado, verbos
│  └─ aside#sidePanel   dock direito: diário de desfazer + sinais
├─ .console-hull        resposta grande + console + verbos rápidos
└─ .drawer              ajustes (voz/jeito, microfone, cofre, fatos, sobre)
```

Sobre a câmara ficam `#core` (moldura), `#orbCanvas` (canvas 2D) e o chip
`#coreMode` (3D ↔ 2D). O palco (`#palco`) substitui o núcleo quando há mídia.

### 8.2 Tokens e estilo

`style.css` é a única folha: define a paleta viva (`--core`), vidro
(`--glass`, `--glass-line`), tipografia, espaçamento e movimento. Quatro temas:

| Tema | `--core` |
|---|---|
| `ultron` (padrão) | `#ff3446` |
| `jarvis` | `#2ad4f0` |
| `amber` | `#ffb03a` |
| `emerald` | `#37e0a2` |

A troca de tema muda estrelas, núcleo, fios e botões **sem recolorir a logo**.

### 8.3 Comportamento (`app.js`)

- Liga a ponte real (`RealTransport`), faz polling de status/eventos e desenha
  somente o que chegou.
- **Rails recolhíveis**: bate-papo (`Ctrl+1`) e diário (`Ctrl+2`) vão a 46 px.
  Estado em `data-chat`/`data-sys`; só a escolha do usuário é persistida
  (`ultron-chat-aberto`, `ultron-sys-aberto`). O padrão responsivo (diário
  recolhido abaixo de 1280 px) **não** vira preferência salva.
- **Diário de desfazer**: lê `GET /api/v1/undo` apenas com a sessão
  desbloqueada; ao bloquear, a lista é limpa da tela. Mostra operação, resumo,
  hora e o selo “desfeito”; estados vazio, erro e indisponível são distintos.
  O botão “desfazer” envia o comando real ao núcleo e se desabilita durante o
  envio.
- **Modo do núcleo**: `localStorage['ultron-core']` (`3d` padrão, `2d` opcional),
  trocável no chip da câmara ou nos ajustes, sem recarregar.
- **Sessão**: ao abrir, mostra o desbloqueio; ao bloquear (botão, Windows ou
  suspensão), limpa o diário e reabre o overlay. A câmera do desbloqueio é só
  pré-visualização, sem áudio e sem gravação.
- **Palco**: texto via `textContent`; PDF abre pelo id opaco no visualizador do
  sistema; site/vídeo em área isolada.

### 8.4 Núcleo (`src/orb.js`)

- `criarOrbe(canvas, { modo })`, `definirModo`, `normalizarModo('3d'|'2d')`.
- **3D**: projeção em perspectiva desenhada no canvas 2D — cristal, casca,
  anéis giroscópicos e ondas; a cor vem de `--core` do tema.
- **2D**: o orbe anterior, preservado como ramo do mesmo loop.
- `estadoDoOrbe(status, mem, agora)` continua traduzindo somente o status real
  (`conectando`, `online`, `ouvindo`, `pensando`, `falando`, `offline`…).
- Sem WebGL, sem three.js. O chip reflete o modo ativo.

### 8.5 Tipografia e acessibilidade

- Piso: **nenhum texto funcional abaixo de 10 px**; corpo **13 px**; resposta
  **15 px** (a resposta é a única coisa grande da tela).
- Foco visível, `aria-live` na resposta, rótulos e `aria-expanded` nos rails.
- `prefers-reduced-motion`: estrelas estáticas, sem varredura, transições
  mínimas; `prefers-reduced-transparency`: vidro vira cor sólida.
- Layout validado sem sobreposição em 1440×900, 1024×768 e 860×600.
- Atalhos: `Ctrl+1` bate-papo, `Ctrl+2` diário, `Ctrl+,` ajustes, `Ctrl+K`
  comando, `Esc` fecha/limpa, `Esc Esc` para tudo.

### 8.6 Prévia (`preview.html` + `preview-mock.js`)

Ferramenta **de desenvolvimento**, nunca empacotada no app:

- cópia fiel de `index.html` (mesmos 181 IDs) com título “prévia”;
- `preview-mock.js` entra antes de `app.js` e responde com dados de exemplo
  (inclui 3 linhas de diário e sessão liberada);
- `?chat` mostra uma conversa de exemplo; `?live` dispara um comando;
- teste de paridade garante que todo id da tela real existe na prévia e que o
  mock não vaza para `index.html`.

Servir com `python -m http.server 8099 --directory electron/site` e abrir
`http://127.0.0.1:8099/preview.html` (`file://` não carrega módulos ES).

---

## 9. Dados e persistência

| Caminho | Conteúdo | Observação |
|---|---|---|
| `dados/ultron.db` | mensagens, fatos, lembretes | conteúdo cifrado AES-256-GCM (`v1:`), metadados visíveis |
| `dados/.cofre.chave` | chave do cofre | protegida por DPAPI; backup junto do banco |
| `dados/cofre.json` | itens do cofre | cifrado; valores nunca vão para a tela |
| `dados/desfazer/` | diário de inversas | expira em 7 dias, máx. 50 operações |
| `dados/voz.json` | voz escolhida | preferência local |
| `dados/personalidade.json` | perfil, jeito, dados do usuário | opcional |
| `dados/correcoes_voz.json` | dicionário pessoal | só para a voz do usuário |
| `.env` | chaves e configuração | segredo; nunca versionar/exportar |
| `logs/` | log de setup, segurança e execução | não versionar |

**Backup correto:** copiar `dados/ultron.db` **e** `dados/.cofre.chave` juntos,
na mesma conta Windows do mesmo PC. Sem a chave, o histórico fica ilegível
(mas intacto); o ULTRON não gera outra por cima.

---

## 10. Segurança em detalhe

### 10.1 Sessão local (1.19.0)

- O Desktop abre **bloqueado**.
- Desbloqueio por Windows Hello (quando há sensor) ou `ULTRON_PIN` do `.env`.
- A sessão vive só em memória: fechar o app, bloquear ou suspender o Windows
  encerra a sessão.
- Com a sessão liberada, ações de risco **ALTO locais e reversíveis** rodam sem
  confirmação. Continuam confirmando:
  - irreversíveis: `executar_comando`, `rodar_codigo`, `desligar_pc`,
    `reiniciar_pc`, `apagar_arquivo`, `enviar_formulario`;
  - privacidade: `ver_tela`, `webcam_foto`, `controlar_mouse_com_gesto`.
- CRÍTICO, Telegram, fluxos e origem desconhecida não mudam.
- PIN nunca é falado, nunca aparece na interface e nunca entra no prompt.

### 10.2 Política declarativa (`permissoes.json`)

```json
{
  "versao": 2,
  "confirmacao": { "baixo": false, "medio": "fora_da_allowlist",
                   "alto": true, "critico": true },
  "timeouts": { "confirmacao_voz": 12, "confirmacao_teclado": 20,
                "confirmacao_telegram": 60 },
  "allowlist": { "programas": { ... }, "pastas": [ ... ] }
}
```

### 10.3 Criptografia

- Cofre: DPAPI (chave do usuário Windows) + AES-256-GCM.
- Memória: mesmo esquema, prefixo `v1:`; migração automática e transacional.
- Updates: SHA-256 + assinatura Ed25519 (chave pública embutida; privada fora
  do repositório).

### 10.4 Superfícies de ataque tratadas

- API local: loopback + token + Host/Origin + JSON estrito + limites.
- IPC: canais nomeados + verificação de remetente.
- Renderer: CSP `script-src 'self'`, sem `innerHTML` para conteúdo do núcleo,
  sem `eval`, sem CDN.
- Palco: id opaco, allowlist de pastas, hosts públicos, sem caminho no corpo.
- Links: http/https público, sem credenciais na URL, sem localhost/rede privada.
- Câmera: permissão só de vídeo, só na janela principal, sem gravação.

---

## 11. Configuração (sem valores)

O `.env` é criado pelo instalador e segue `.env.example`. Grupos de variáveis:

- **Identidade:** `NOME_USUARIO`
- **Chaves:** `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`,
  `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`,
  `DEEPSEEK_API_KEY`, `CEREBRAS_API_KEY`, `TOGETHER_API_KEY`, `XAI_API_KEY`
- **Provedores/modelos:** `PROVEDORES`, `*_MODEL`, `REASONING_EFFORT`
- **Resiliência:** `IA_TENTATIVAS`, `IA_BACKOFF_BASE`, `IA_BACKOFF_TETO`,
  `IA_BACKOFF_JITTER`, `IA_TEMPO_MAX_PROVEDOR`, `IA_TEMPO_MAX_TOTAL`
- **Voz:** `VOZ`, `VOZ_PITCH`, `VOZ_RATE`, `LIMIAR_VOZ`, `SILENCIO_FIM`,
  `VOZ_NATIVA`
- **Memória:** `HISTORICO_MSGS`, `RECALL_MSGS`, `RECALL_DIAS`
- **Janela/atalhos:** `JANELA_SEGUIMENTO`, `HOTKEY_FALAR`, `HOTKEY_PARAR`
- **Sessão:** `ULTRON_PIN`
- **Telegram:** `TELEGRAM_TOKEN`, `TELEGRAM_USER_ID`

Sem pelo menos uma chave de IA o ULTRON avisa e não inicia.

---

## 12. Como rodar

### Instalação normal (usuário)

1. Python 3.12+ 64 bits e Node.js LTS.
2. Extrair o ZIP do Release em uma pasta simples (`C:\ultron`).
3. Executar `ULTRON-Setup.exe` (não precisa de administrador).
4. Abrir pelo atalho ou por `ULTRON.exe`.
5. Preencher o `.env` com uma chave (Gemini é gratuita).

Diagnóstico sem abrir o painel: `ULTRON.exe --diagnostico`.

### Desenvolvimento

```powershell
# suíte Python (quando pytest está instalado)
python -m pytest tests -q

# segurança standalone (unittest)
python -m unittest testes_seguranca

# shell Electron (requer API local já rodando e ULTRON_API_URL/TOKEN)
cd electron
npm install
npm start

# prévia da interface no navegador
python -m http.server 8099 --directory electron/site
# abrir http://127.0.0.1:8099/preview.html

# testes Node (sem instalar nada)
node --test electron/test/*.test.js electron/site/test/*.test.mjs
```

Observações do ambiente desta cópia:

- O Node pode não estar no `PATH` (aqui está em `C:\Program Files\nodejs\node.exe`).
- `pytest` não está instalado nesta máquina; os testes Python não foram
  executados nesta entrega (ver §14).
- `npm install`/Electron não foram usados: os testes Node rodam com `node:test`
  puro, sem `node_modules`.

---

## 13. Testes

### 13.1 Suítes Node (executadas nesta entrega: **43/43 verdes**)

| Arquivo | Cobre |
|---|---|
| `electron/site/test/handlers.test.mjs` | todo handler `onclick` existe no módulo; sem ligação duplicada; stub `VAZIO` seguro |
| `electron/site/test/real.test.mjs` | transporte real, palco, microfone, offline, PIN, temas, voz/jeito, sessão, `/undo`, **paridade da prévia** |
| `electron/site/test/unlock.test.mjs` | overlay de desbloqueio, Hello/PIN reais, dados reais, `prefers-reduced-motion` |
| `electron/site/test/chat.test.mjs` | abas do bate-papo, limite de 15 mensagens, limpeza pela ponte |
| `electron/site/test/orb.test.mjs` | modo 3D/2D, projeção finita, arestas do cristal, `estadoDoOrbe` |
| `electron/test/api.test.js` | cliente da API, loopback, token, erros sem vazar token |
| `electron/test/links.test.js` | validação de URLs públicas (IPv4/IPv6, DNS, credenciais) |
| `electron/test/palco-protocol.test.js` | Range/HEAD, id opaco, expiração, extensões de mídia |

### 13.2 Suítes Python

- `tests/` — 43 arquivos (`test_desktop_api.py`, `test_desktop_runtime.py`,
  `test_palco.py`, `test_desfazer.py`, `test_memoria*.py`, `test_seguranca`
  indireto, voz, VAD, Telegram, update, hardware, visão etc.).
- `testes_seguranca.py` — 58 verificações de política (allowlist, PIN,
  confirmação, caminhos protegidos, logs).
- Números de referência do CHANGELOG 1.19.0: **474 pytest + 58 segurança +
  37 Node**. O Node cresceu para **43** com a prévia (T11). Os números Python
  não foram reverificados nesta máquina.

### 13.3 Verificações manuais desta entrega

- Navegador (Chromium do app), 1000×700: sem overflow, sem texto < 10 px.
- 1440×900 / 1024×768 / 860×600: header, docks, câmara, resposta e console sem
  sobreposição; diário recolhe sozinho abaixo de 1280 px.
- Prévia: 3 linhas de diário (terceira “desfeito”), chip 3D→2D e persistência
  após recarregar, `?chat` com 4 mensagens, zero erros de console.
- Quadro do núcleo a 60 fps (p50 ≈ 16,6–16,7 ms; p95 ≈ 17,3 ms) em 3D e 2D,
  dpr 1.
- Temas: `--core` muda para `#ff3446`, `#2ad4f0`, `#ffb03a`, `#37e0a2`.

---

## 14. Estado da entrega (interface espacial, 2026-10-27/28)

Plano: `.internal/plans/2026-10-27-interface-espacial.md`
Spec: `.internal/specs/2026-10-27-interface-espacial-design.md`
Artefatos SDD: `.internal/sdd/2026-10-27-interface-espacial/`

| Tarefa | Status | Resultado |
|---|---|---|
| 1. Runtime `/undo` | concluída | `undo_list` somente leitura, `indisponivel` sem módulo |
| 2. Rota `/api/v1/undo` | concluída | GET autenticado, sem escrita |
| 3. Ponte Electron | concluída | `undo:list`, preload, `RealTransport.undoList` |
| 4–5. Orbe 3D/2D | concluída | projeção no canvas 2D, ramo 2D preservado |
| 6. Casca HTML | concluída | 181 ids, header/docks/câmara/console |
| 7–8. CSS | concluída | tokens de vidro, retículo, diário, gaveta, desbloqueio, responsivo |
| 9. Modo do núcleo | concluída | chip, `localStorage['ultron-core']`, ajustes |
| 10. Diário e rails | concluída | `/undo`, sinais reais, recolhimento, limpeza ao bloquear |
| 11. Prévia | concluída | `preview.html` + mock + teste de paridade |
| 12. Fechamento | concluída | CHANGELOG, suíte verde, HUD em 2D, medições |

### Arquivos alterados nesta entrega

- `electron/site/style.css` (reescrito: T7 + T8)
- `electron/site/index.html` (casca nova)
- `electron/site/app.js` (T9 + T10 + correção dos rails)
- `electron/site/preview.html` (cópia fiel + mock)
- `electron/site/preview-mock.js` (dados de prévia)
- `electron/site/test/real.test.mjs` (teste de paridade)
- `electron/site/mini-hud.js` (orbe em 2D)
- `CHANGELOG.md` (entrada “interface espacial”, sem bump)

### Invariantes preservados

- Nenhuma dependência nova; nenhum CDN; nenhum WebGL/React/Tailwind.
- CSP idêntica entre `index.html` e `preview.html`; `script-src 'self'`.
- Versão continua **1.19.0** (`electron/package.json`, meta e `/health`).
- `unlock.js`, `stage.inert`, `powerMonitor`, permissões de câmera e modais
  inalterados.
- Nada foi commitado ou enviado (não há commit nesta entrega).

---

## 15. Pendências e riscos conhecidos

1. **`electron/package.json` → `build.files` não lista `site/src/unlock.js`.**
   O caminho de distribuição real (ZIP + `ULTRON.exe`) copia a pasta inteira e
   não é afetado; `npm run dist` (electron-builder) geraria uma casca sem o
   módulo de desbloqueio. Corrigir antes de usar `npm run dist`.
2. **`README.md` cita 328 testes** na seção de desenvolvimento; o CHANGELOG
   1.19.0 fala em 474. O número do README está defasado.
3. **Custo do núcleo 3D**: ~1.953 `stroke()` por quadro. Medido a 60 fps nesta
   máquina em 1000×700; em hardware fraco, as alavancas são reduzir `toro()`,
   agrupar arestas por profundidade ou usar o modo 2D.
4. **Calibrações visuais do orbe** (achados da T5, não bloqueantes):
   alfa por malha ignora `intensidade`; `normalizar()` entrega faixa dinâmica
   estreita (~0,44–0,51); amplitude das ondas fixa em 0,03 enquanto a spec pede
   crescimento com a energia; comentário de cabeçalho do `orb.js` ainda
   descreve só o ramo 2D.
5. **`pytest` ausente nesta máquina** — a suíte Python não foi executada nesta
   entrega. Rodar em um ambiente com `requirements.txt` instalado antes de
   publicar.
6. **Prévia é ferramenta de dev.** `preview.html`/`preview-mock.js` não entram
   no build do Electron nem no ZIP de release; o teste de paridade protege
   contra divergência de ids.
7. **Resolvido em 28/10 — seletor impossível no `requirements.txt`:**
   `winrt-Windows.Security.Credentials.UI>=4!10.0.28000.2705,<5` nunca podia ser
   satisfeito: o `4!` é epoch PEP 440, então `4!10...` é **maior** que `5` e
   falha o teto `<5`. O pip listava a versão e ainda assim respondia “No
   matching distribution”. O teto passou a `<5!0` (epoch 5), que preserva a
   linha 4.x e aceita a versão publicada. Windows Hello continua opcional:
   sem o pacote, `biometria.py` devolve indisponível e o PIN assume.
8. **O instalador não aborta quando a verificação final falha.** Ele imprime
   `!! núcleo importável` e ainda assim conclui com “Pronto. Iniciado.”, o que
   abre o app quebrado. Falhas de import deveriam interromper o passo 6 ou
   impedir o “Pronto”. (Observado em 28/10: `openai` com pasta incompleta
   passou pela checagem de dependências e só apareceu no import do núcleo.)

---

## 16. Apêndice — atalhos, chaves e convenções

### Atalhos da interface

| Atalho | Ação |
|---|---|
| `Ctrl+1` | recolher/abrir o bate-papo |
| `Ctrl+2` | recolher/abrir o diário |
| `Ctrl+,` | ajustes |
| `Ctrl+K` | focar o comando |
| `Esc` | fecha gaveta/palco; limpa o campo |
| `Esc Esc` | parada de emergência |

### Chaves de `localStorage`

| Chave | Valores | Uso |
|---|---|---|
| `ultron-theme` | `ultron`/`jarvis`/`amber`/`emerald` | tema |
| `ultron-core` | `3d`/`2d` | modo do núcleo |
| `ultron-chat-aberto` | `1`/`0` | rail do bate-papo (só escolha do usuário) |
| `ultron-sys-aberto` | `1`/`0` | rail do diário (só escolha do usuário) |

### Convenções de código

- Python 3.12+, módulos na raiz, imports locais; testes em `tests/`.
- Renderer: ES modules nativos, sem bundler; CSS com tokens; HTML sem `innerHTML`
  para conteúdo vindo do núcleo.
- Textos de interface em português do Brasil; nomes de código em português
  quando o domínio é do produto.
- Comentários explicam **por que**, não o óbvio.

---

## 17. Checklist para gerar uma cópia que pode circular

Excluir sempre:

- `.env` (e qualquer `.env.*`, exceto `.env.example`)
- `dados/` (banco, cofre, diário, preferências)
- `.git/`
- `*.exe` (`ULTRON.exe`, `ULTRON-Setup.exe`)

Recomendado excluir também (peso/ruído, não segredo):

- `venv/`, `node_modules/`, `logs/`, `build/`, `dist*/`
- `.internal/` (planos e specs internas)
- `__pycache__/`, `.pytest_cache/`, `*.log`

Manter:

- código Python, `electron/`, `tests/`, documentação (`README.md`,
  `CHANGELOG.md`, `SECURITY.md`, `LICENSE`, este arquivo),
- `.env.example`, `permissoes.json`, `requirements*.txt`,
- `installer/`, `tools/`.

---

*Fim do documento. Gerado a partir do código real desta cópia; nenhum valor
sensível foi incluído.*
