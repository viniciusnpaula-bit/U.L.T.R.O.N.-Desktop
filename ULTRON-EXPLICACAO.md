# U.L.T.R.O.N. Desktop — Explicação Completa do Projeto

**Versão do produto:** 2.0.0  
**Língua:** Português do Brasil  
**Plataforma:** Windows  
**Data da explicação:** 02/11/2026

---

## 1. O que é o ULTRON

O **U.L.T.R.O.N. Desktop** é um assistente pessoal para Windows que:

- **Conversa por voz e por texto** em português do Brasil.
- **Executa ações no computador**: abrir programas, organizar arquivos, controlar Spotify, webcam, navegador, hardware, lembretes, etc.
- **Nunca age sem você**: toda ação sensível passa por confirmação e, nas críticas, por PIN.
- **Funciona local-first**: chaves, memória, cofre, diário de desfazer e logs ficam no seu PC. A nuvem só recebe o estritamente necessário para o modelo de IA responder.

A regra central do produto: **nenhuma saída da IA autoriza uma ação**. A intenção passa por uma política local (`seguranca.py`), que decide `ALLOW` / `CONFIRM` / `DENY`.

---

## 2. Princípios de projeto

1. **Local-first.** Chaves, memória, cofre, diário de desfazer e logs ficam no computador. A nuvem só recebe o necessário para o modelo responder.
2. **Fail-closed.** Sem chave, sem sessão, sem confirmação ou sem permissão, a ação não acontece. O gateway de segurança falha fechado.
3. **Dados reais, nunca simulados na tela.** A interface não inventa autenticação, telemetria, eventos, progresso ou diário. Se o núcleo não respondeu, a tela mostra "aguardando/offline", não um estado fictício.
4. **Sem dependências novas na casca.** Renderer sem framework, sem bundler, sem CDN. CSP `script-src 'self'` intacta.
5. **Tudo que é sensível é explícito.** PIN, Hello, allowlist, caminhos protegidos, hosts permitidos e limites de tamanho são verificados no lado confiável (Python/Electron main), não no renderer.

---

## 3. Arquitetura (visão geral)

```
ULTRON.exe / atalho  →  launcher.py  →  desktop.py

Python: núcleo (main.py)          API local 127.0.0.1 (desktop_api.py)
├─ voz / STT / TTS                ├─ token por sessão (≥32 chars)
├─ cérebro (cerebro.py)           ├─ Host/Origin conferidos
├─ ferramentas (ferramentas.py)   └─ rotas /api/v1/* limitadas
├─ segurança (seguranca.py)
├─ memória (memoria.py, SQLite cifrado)
├─ desfazer (desfazer.py)
└─ palco (palco.py)
                              ▲
                              │ IPC nomeado (preload.js)
Electron main (main.js) ─────┘  →  Renderer (electron/site/)
├─ janela principal bloqueada por padrão
├─ HUD flutuante (mini-hud)
├─ protocolo ultron-palco://
└─ powerMonitor: bloquear/suspender encerra a sessão
```

- **O Python é dono do estado.** O renderer só desenha o que a API devolve.
- **O renderer não fala HTTP.** `preload.js` expõe métodos nomeados; `api.js` chama a API local com o token; `src/real.js` traduz eventos.
- **O palco** substitui o núcleo por vídeo, imagem, PDF, site ou texto, com id opaco em vez de caminho de arquivo.

---

## 4. O caminho de uma ordem (do usuário à execução)

| Passo | O que acontece |
|-------|----------------|
| 1. Entrada | Voz (STT) ou texto no console da interface; o comando chega ao runtime. |
| 2. Intenção | `cerebro.py` monta o prompt com memória, personalidade, autoconhecimento e o catálogo de ferramentas; o modelo escolhe uma ferramenta e argumentos. |
| 3. Política local | `ferramentas.executar` é o único portão: classifica risco/operação/alvo e chama `seguranca.autorizar()`. `ALLOW` → executa; `CONFIRM` → pede confirmação; `DENY` → recusa e registra. |
| 4. Execução | A ferramenta age (arquivo, janela, palco, navegador…). Operação de arquivo reversível grava a inversa em `desfazer.py`. |
| 5. Resposta | O texto volta ao runtime, que publica eventos e o turno da conversa; a interface desenha a resposta e o estado real. |
| 6. Auditoria | Logs de segurança guardam decisão, alvo e motivo — nunca o PIN nem a chave de IA. |

---

## 5. Mapa de módulos (raiz do projeto)

| Arquivo | Papel |
|---------|-------|
| `main.py` | Entrada do núcleo: modo voz, texto, bandeja, atalhos, desbloqueio inicial. |
| `launcher.py` | Ponto de entrada do atalho/`ULTRON.exe`; escolhe painel, texto, bandeja ou `--doctor`. |
| `desktop.py` | Sobe núcleo + API + Electron e derruba tudo ao fechar. |
| `desktop_runtime.py` | Ciclo de vida do painel, fila de eventos, comandos, sessão, voz, palco, atualização. |
| `desktop_api.py` | HTTP local autenticado, somente loopback (`127.0.0.1`), token por sessão. |
| `cerebro.py` | Conversa com provedores de IA, ferramentas, streaming e limites. |
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
| `skills.py` | Skills em Markdown (`dados/skills/<slug>/SKILL.md`). |
| `autoconhecimento.py` | Bloco do system prompt gerado do sistema vivo (nome, versão, SO, habilidades, limites). |
| `arquivos.py`, `hardware.py` | ZIP seguro/organização de pastas e relatório de hardware. |
| `navegador.py`, `visao.py` | Navegador controlado (Playwright) e webcam/gestos (OpenCV). |
| `confirmacao.py` | Confirmações de ações sensíveis. |
| `teclado.py` | Entrada de teclado do terminal. |
| `registro.py` | Registro geral. |
| `registros_emocionais.json` | Mapa registro emocional → tom/velocidade da voz. |
| `observador` / `desktop_autostart` / `desktop_runtime` | Suporte ao desktop Electron. |

**Pasta `electron/`**: shell Electron — janela, ponte IPC, HUD flutuante, protocolo do palco, testes.  
**Pasta `electron/site/`**: interface (HTML/CSS/JS puro, sem framework).  
**Pasta `installer/`**: instalador Python (`ultron_setup.py`).  
**Pasta `tools/`**: build, ícone, chaves de assinatura, publicação.  
**Pasta `tests/`**: testes pytest (núcleo, API, segurança, voz, UI indireta).  
**Pasta `dados/`**: banco, cofre, diário, preferências — dado do usuário, não exportar.  
**Pasta `logs/`**: logs locais.

---

## 6. Interface (espacial 2.0)

A interface 2.0 é uma "câmara com o núcleo animado no centro", o bate-papo à esquerda, os eventos à direita e uma única linha de comando.

- `electron/site/index.html` (181 IDs únicos) organiza a tela em: header, dock esquerdo (bate-papo), câmara (núcleo 3D/2D), dock direito (diário de desfazer + sinais), console inferior e gaveta de ajustes.
- `style.css` é a única folha: paleta viva (`--core`), vidro (`--glass`, `--glass-line`), tipografia, espaçamento e movimento.
- Quatro temas: `ultron` (`#ff3446`), `jarvis` (`#2ad4f0`), `amber` (`#ffb03a`), `emerald` (`#37e0a2`).
- Núcleo 3D desenhado no canvas 2D (sem WebGL, sem three.js): cristal, casca, anéis giroscópicos e ondas. O orbe 2D anterior continua disponível.
- Atalhos: `Ctrl+1` bate-papo, `Ctrl+2` diário, `Ctrl+,` ajustes, `Ctrl+K` comando, `Esc` fecha/limpa, `Esc Esc` parada de emergência.
- `preview.html` + `preview-mock.js`: ferramenta de desenvolvimento (não empacotada no app) para pré-visualizar a interface com dados de exemplo.

---

## 7. Voz

### Reconhecimento (STT)
- Motor principal: **Groq Whisper large-v3** (plano gratuito, 2.000 requisições/dia).
- Fallback automático: Google → motor de fala nativo do Windows (SAPI).
- `VOZ_MOTOR=auto|groq|google|nativo` no `.env`.
- Silêncio puro não gasta requisição: checagem local de energia descarta áudio sem fala antes de chamar a nuvem.
- Confiança baixa: o ULTRON repete o que entendeu antes de agir (conferência).
- `VOZ_CONFERIR=auto|sempre|nunca` no `.env`.
- Palavra de ativação: "Ei, Ultron" (também aceita variantes). Atalho "segurar para falar": `Ctrl+Alt+Space`.

### Sintese (TTS)
- **Edge TTS** online com 15 timbres pt-BR reais.
- Reserva local: **pyttsx3** (sem internet).
- 13 estilos de fala (jeito): equilibrado, brincalhão, profissional, mordomo, amigo, direto, motivador, narrador, amoroso, sarcástico, malandro, ignorante e rigoroso. O jeito muda só o tom, nunca as regras de segurança.
- **Registro emocional** (1.20.0): o modelo escolhe um registro (`neutro`, `lamento`, `encorajador`, `alerta`, `comemorando`, `serio`, `duvida`) e o tom/velocidade da voz se ajusta em até 15%.

### Precisão de escuta
- Recalibração automática do limiar de volume (a cada 5 min sem comando ou após 3 "não entendi").
- VAD (detecção de atividade de voz) com `webrtcvad` ou VAD em Python puro.
- Dicionário de correções pessoais (`dados/correcoes_voz.json`): "não, eu disse Rocket League" ensina o ULTRON.
- Fuzzy matching para comandos distorcidos ("fexar aplicativo", "organizar arquibos").

---

## 8. Memória e personalidade

### Memória local (SQLite cifrado)
- `dados/ultron.db`: mensagens, fatos, lembretes.
- Conteúdo cifrado em repouso com **AES-256-GCM** (chave protegida por DPAPI do Windows).
- Histórico entre sessões: "limpar" esvazia só a sessão do bate-papo, não o banco.
- Recall local: a cada resposta, o ULTRON procura trechos de conversas anteriores (até 120 dias) com palavras em comum e os usa como contexto — sem embeddings, sem enviar o banco para fora.
- Últimas mensagens da sessão vão como histórico normal (`HISTORICO_MSGS`, padrão 12).

### Obsidian (opcional)
- Lê e escreve em um vault do Obsidian (`OBSIDIAN_VAULT` no `.env`; padrão `Documents/ULTRON-Vault`).
- Nota `Preferencias.md` entra sempre no contexto; até 3 notas relacionadas entram por resposta.
- Ferramentas: `obsidian_buscar`, `obsidian_ler`, `obsidian_notas`, `obsidian_tarefas`, `obsidian_status`, `obsidian_criar`, `obsidian_anexar`, `obsidian_diario`.
- `OBSIDIAN_ATIVO=0` desliga leitura e escrita; `OBSIDIAN_RECALL=0` desliga leitura automática.

### Nuances (tom)
- Leitura local por léxico, negação, intensificadores e pontuação: frustração, irritação, ansiedade, tristeza, confusão, animação e gratidão. O tom da resposta se ajusta. Não é diagnóstico.

### Personalidade
- Perfis: **U.L.T.R.O.N.**, JARVIS, VISÃO, EDITH.
- Dados do usuário opcionais: nome, apelido, idade, gênero, como quer ser chamado, texto livre (`dados/personalidade.json`).
- Saudação ao abrir ligável/desligável.

---

## 9. Segurança

### Sessão local (1.19.0)
- O Desktop abre **bloqueado**.
- Desbloqueio por **Windows Hello** (quando há sensor) ou `ULTRON_PIN` do `.env`.
- A sessão vive só em memória: fechar o app, bloquear ou suspender o Windows encerra a sessão.
- Com a sessão liberada, ações de risco ALTO locais e reversíveis rodam sem confirmação. Continuam confirmando: irreversíveis (`executar_comando`, `rodar_codigo`, `desligar_pc`, `reiniciar_pc`, `apagar_arquivo`, `enviar_formulario`) e privacidade (`ver_tela`, `webcam_foto`, `controlar_mouse_com_gesto`).
- PIN nunca é falado, nunca aparece na interface e nunca entra no prompt.
- Parada de emergência: `Ctrl+Alt+X` ou `Esc Esc`.

### API local (`desktop_api.py`)
- Só aceita `127.0.0.1` (recusa qualquer outro host).
- Exige `Host: 127.0.0.1:<porta>` e, se houver `Origin`, a origem local exata.
- Token aleatório por sessão, mínimo 32 caracteres, comparado com `hmac.compare_digest` no header `X-ULTRON-Token`.
- Corpo JSON obrigatório, máximo 8 KB; comando máximo 4.000 caracteres.
- Porta preferida **3900**; se ocupada, escolhe uma porta livre do loopback.
- Respostas sempre `Cache-Control: no-store` e `Connection: close`.

### Shell Electron
- `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`.
- `will-navigate` bloqueado e `setWindowOpenHandler` nega novas janelas.
- Todo `ipcMain.handle` confere remetente (janela principal ou HUD).
- CSP `script-src 'self'`, sem `innerHTML` para conteúdo do núcleo, sem `eval`, sem CDN.

### Permissões (`permissoes.json`)
- Níveis de confirmação: `baixo` (false), `medio` (fora_da_allowlist), `alto` (true), `critico` (true).
- Allowlist de programas, diretórios, operações, teclas seguras e comandos.
- `permitir_shell_arbitrario: false`.

---

## 10. Funcionalidades principais

### Ações no PC
- Abre programas, sites e pastas; clica, digita, rola e usa o navegador controlado (lê a página, clica, preenche formulários e envia).
- Ajusta volume, brilho, janelas, zoom e modo escuro.
- Organiza, compacta, descompacta, cria, move e apaga arquivos (vai para a lixeira).
- Analisa o PC: CPU, memória, GPU (modelo e driver) e discos.
- Webcam: tira foto, detecta objetos e lê gestos da mão (punho, indica, dois dedos, três dedos, mão aberta). Com o gesto "indica", o ponteiro segue a mão. Tudo local, com confirmação antes de abrir a câmera.
- Escreve e roda código Python ou Node em um sandbox, sem as chaves de API do ULTRON no ambiente, e cria sites de uma página em pastas autorizadas.
- Marca na tela onde está o botão que você procura e lê o texto visível com OCR local.

### Desfazer
- Toda operação de arquivo do ULTRON (criar, mover, apagar, compactar, descompactar, organizar, criar site) deixa uma inversa em `dados/desfazer/`.
- Diga "desfazer" e o ULTRON pergunta antes de voltar atrás.
- Confere o estado atual antes de tocar em qualquer coisa; se mudou, recusa.
- O que foi apagado volta pela Lixeira do Windows.
- Caminhos protegidos (Windows, AppData, `.ssh`, o próprio ULTRON) e caminhos fora da pasta do usuário ou da allowlist nunca são tocados.
- O diário expira em 7 dias, guarda no máximo 50 operações e não sai do computador.

### Organizar arquivos
- Três modos: **tipo** (padrão), **data** (`Ano/Mês`), **extensão** (uma pasta por sufixo).
- Mostra prévia antes de mover; só move depois da confirmação.
- Nada é sobrescrito — nome repetido vira `nome (2).ext`.

### Spotify
- Controla o Spotify pela Web API oficial. Tocar e pausar exige Premium; buscar e consultar o que está tocando funciona em qualquer conta.
- Credenciais no cofre cifrado (Configurações → Spotify).
- Ferramentas: `spotify_buscar`, `spotify_tocar`, `spotify_controlar`, `spotify_estado`.

### Palco (mídia)
- Peça para mostrar vídeo, imagem, PDF, site ou texto: o conteúdo aparece **no lugar do núcleo**, sem abrir outra janela.
- Vídeos do YouTube e Vimeo rodam embutidos; sites abrem em área isolada; PDF abre no visualizador do Windows.
- `Esc` ou botão fechar devolvem o núcleo.
- Vídeo entra no mudo; botão som no cabeçalho do palco liga o áudio a pedido.
- Arquivos locais precisam estar na allowlist de pastas. A interface recebe só um id temporário, nunca o caminho do arquivo.

### Skills (2.0.0)
- Procedimentos em Markdown em `dados/skills/<slug>/SKILL.md`.
- O ULTRON vê só o índice no prompt e carrega o corpo quando precisa, via ferramenta `usar_skill(nome)`.
- Skills criadas pelo próprio agente entram como **pendentes**: valem só depois de aprovadas por você.
- Sem uso por 30 dias vira obsoleta; 90 dias, arquivada — nada é apagado.
- `SKILLS_ATIVO=0` desliga tudo.

### Atualizações
- O ULTRON consulta o último Release do repositório, baixa o pacote, confere o SHA-256 publicado e aplica com backup e rollback automático.
- A partir da 1.9.9 cada Release é **assinado** (Ed25519). O app só aplica a atualização se a assinatura do `SHA256SUMS.txt` for válida.
- Dados, chaves e ambiente Python nunca são tocados.

---

## 11. Instalação e primeiros passos

1. Instale **Python 3.12+ (64 bits)** e **Node.js LTS** (marcar "adicionar ao PATH").
2. Extraia o ZIP para uma pasta simples, por exemplo `C:\ultron`.
3. Execute **`ULTRON-Setup.exe`** (não precisa de administrador). Cria o ambiente Python isolado, instala o Electron, cria o atalho e verifica tudo no final.
4. Abra pelo atalho "U.L.T.R.O.N. Desktop" ou pelo `ULTRON.exe`.
5. Cole uma chave de IA no `.env` (Gemini é gratuita: https://aistudio.google.com/apikey).
6. Diga **"Ei, Ultron"** seguido do comando.

Diagnóstico sem abrir o painel: `ULTRON.exe --diagnostico`.

---

## 12. Desenvolvimento

```bash
python -m pytest tests -q            # suíte local de testes
python tools/make_icon.py            # regera ULTRON.ico a partir da arte
python tools/build_setup.py --zip    # compila ULTRON.exe, ULTRON-Setup.exe e o ZIP
python launcher.py --doctor          # diagnóstico
```

O navegador controlado usa Playwright (opcional, fora do `requirements.txt`): `pip install playwright` e `python -m playwright install chromium`.

---

## 13. Estado da entrega e pendências conhecidas

Conforme o `CONTEXTO-DO-PROJETO.md` (§15):

1. `electron/package.json` → `build.files` não lista `site/src/unlock.js`. Afeta apenas `npm run dist` (electron-builder), não o ZIP/EXE de distribuição.
2. `README.md` cita 328 testes; o CHANGELOG 1.19.0 fala em 474. Número defasado.
3. Custo do núcleo 3D: ~1.953 `stroke()` por quadro. Em hardware fraco, reduzir `toro()` ou usar modo 2D.
4. Calibrações visuais do orbe (não bloqueantes): alfa por malha ignora `intensidade`; amplitude das ondas fixa; comentário de cabeçalho do `orb.js` descreve só o ramo 2D.
5. `pytest` ausente nesta máquina — suíte Python não executada nesta entrega.
6. Prévia é ferramenta de dev; não entra no build do Electron nem no ZIP de release.
7. Resolvido: seletor impossível no `requirements.txt` (`winrt-Windows.Security.Credentials.UI`).
8. O instalador não aborta quando a verificação final falha — imprime `!! núcleo importável` e conclui com "Pronto. Iniciado.".

---

## 14. Resumo de arquivos de configuração e dados

| Caminho | Conteúdo | Observação |
|---------|----------|------------|
| `.env` | Chaves e configuração | Segredo; nunca versionar |
| `.env.example` | Modelo do `.env` | Pode versionar |
| `permissoes.json` | Política de segurança declarativa | Versão 2 |
| `dados/ultron.db` | Mensagens, fatos, lembretes | Cifrado AES-256-GCM |
| `dados/.cofre.chave` | Chave do cofre | Protegida por DPAPI |
| `dados/cofre.json` | Itens do cofre | Cifrado |
| `dados/desfazer/` | Diário de inversas | Expira em 7 dias, máx. 50 ops |
| `dados/voz.json` | Voz escolhida | Preferência local |
| `dados/personalidade.json` | Perfil, jeito, dados do usuário | Opcional |
| `dados/correcoes_voz.json` | Dicionário pessoal de voz | Só para a voz do usuário |
| `registros_emocionais.json` | Mapa registro → tom/velocidade | 15% de desvio máximo |
| `logs/` | Logs locais | Não versionar |

---

## 15. Como fazer backup

Copie **juntos**, na mesma conta Windows do mesmo PC:
- `dados/ultron.db`
- `dados/.cofre.chave`

Sem a chave, o histórico fica ilegível (mas intacto); o ULTRON não gera outra por cima. Em outra conta ou outro PC, a DPAPI não decifra a chave.

Para gerar backup em ZIP: `python tools/backup_dados.py` (o arquivo sai em `backups/`).

---

*Explicação gerada a partir do código real deste repositório (README.md, LEIA-ME.txt, CONTEXTO-DO-PROJETO.md, CHANGELOG.md, AUDITORIA.md, permissoes.json, config.py, main.py e restante da estrutura). Nenhum valor sensível foi incluído.*