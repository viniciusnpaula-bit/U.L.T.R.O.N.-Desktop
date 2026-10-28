# U.L.T.R.O.N. Desktop

Assistente pessoal para Windows: conversa por voz, age no PC e **nunca age sem você** —
toda ação sensível passa por confirmação e, nas críticas, por PIN.

Interface 2.0: uma câmara com o núcleo animado no centro, o bate-papo (voz e texto) à esquerda,
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

## Palco

Peça para mostrar um vídeo, uma imagem, um PDF, um site ou um texto e o conteúdo
aparece **no lugar do núcleo**, sem abrir outra janela. Vídeos do YouTube e do
Vimeo rodam embutidos; sites abrem em área isolada; PDF abre no visualizador do
Windows. `Esc` ou o botão **fechar** devolvem o núcleo.

Vídeo entra **no mudo**: o botão **som** no cabeçalho do palco liga o áudio a
pedido. Em YouTube/Vimeo ele recarrega o player sem o parâmetro de mudo; em
arquivo local alterna na hora. Isso também evita o bloqueio de autoplay com som
que o Chromium aplica.

Arquivos locais precisam estar na allowlist de pastas do ULTRON. A interface
recebe só um id temporário, nunca o caminho do arquivo. Site externo e mídia
fora dos hosts conhecidos pedem confirmação antes de aparecer.

## Desfazer

Toda operação de arquivo do ULTRON — criar, mover, apagar, compactar,
descompactar, organizar e criar site — deixa uma inversa em um diário local, em
`dados/desfazer/`. Diga **“desfazer”** e o ULTRON pergunta antes de voltar atrás.
Cada chamada desfaz a operação mais recente que ainda pode ser revertida.

O desfazer confere o estado atual antes de tocar em qualquer coisa: se o arquivo
mudou de tamanho ou de data, se o destino já está ocupado ou se a pasta extraída
ganhou conteúdo, ele **recusa** em vez de apagar o que você editou. O que foi
apagado volta pela **Lixeira do Windows**, casando pasta original, nome, tamanho
e data. Caminhos protegidos (Windows, AppData, `.ssh`, o próprio ULTRON) e
caminhos fora da pasta do usuário ou da allowlist nunca são tocados. O diário
expira em 7 dias, guarda no máximo 50 operações e não sai do computador.

## Organizar arquivos

Peça **“organiza a pasta Downloads”** e o ULTRON primeiro mostra a prévia (quantos
arquivos em cada destino) e só move depois da confirmação. Três modos:

- **tipo** (padrão): Imagens, Vídeos, Áudios, Documentos, Compactados,
  Instaladores, Código e Outros;
- **data**: `Ano/Mês` pela data de modificação;
- **extensão**: uma pasta por sufixo (`PDF`, `JPG`, …) e `SEM-EXTENSAO`.

Por padrão só entram os arquivos soltos na pasta; `subpastas=true` inclui o que
está dentro das subpastas (a estrutura antiga é achatada, mas o desfazer devolve
cada arquivo ao caminho original). Nada é sobrescrito — nome repetido vira
`nome (2).ext`. Arquivos ocultos, `desktop.ini`, `~$…` do Office e restos de
download (`.tmp`, `.part`, `.crdownload`) ficam onde estão. A pasta precisa estar
na allowlist, e organizar sempre pede confirmação.

## Memória e nuances

A conversa fica em SQLite (`dados/ultron.db`) e **não** é apagada por “limpar”:
limpar esvazia só a sessão do bate-papo. A cada resposta, o ULTRON procura
localmente trechos de conversas anteriores (até 120 dias) que tenham palavras em
comum com o pedido atual e os usa como contexto — sem embeddings e sem enviar o
banco para fora. As últimas mensagens da sessão continuam indo como histórico
normal (`HISTORICO_MSGS`, padrão 12). O recall não repete o que já está no
histórico e nunca leva chave, token ou PIN para o prompt.

O texto do usuário também passa por uma leitura local de nuances — frustração,
irritação, ansiedade, tristeza, confusão, animação e gratidão — e o tom da
resposta se ajusta. É uma leitura objetiva por léxico, negação, intensificadores
e pontuação; não é um diagnóstico.

## Memória no Obsidian

O ULTRON também lê e escreve em um vault do Obsidian (`OBSIDIAN_VAULT` no
`.env`; vazio = `Documents/ULTRON-Vault`). São notas Markdown comuns:

- a leitura é automática a cada resposta: a nota `Preferencias.md` entra sempre
  no contexto e até `OBSIDIAN_RECALL` notas (padrão 3) que tenham a ver com o
  pedido entram junto, com o nome e um trecho;
- `obsidian_buscar`, `obsidian_ler`, `obsidian_notas`, `obsidian_tarefas` e
  `obsidian_status` consultam o vault;
- `obsidian_criar`, `obsidian_anexar` e `obsidian_diario` gravam sozinhos, sem
  pedir confirmação (risco baixo): quando o ULTRON julgar que algo vale lembrar —
  uma preferência, um costume, um fato do dia — ele mesmo grava. Costumes vão
  para `Preferencias.md` (por exemplo, "música: sempre no Spotify"), então
  "toque música" já abre o Spotify sem perguntar de novo. O diário fica em
  `Diario/AAAA-MM-DD.md`, com data e hora reais;
- toda escrita entra no diário de desfazer: criar uma nota pode ser desfeito
  apagando-a; acrescentar texto pode ser desfeito cortando só o trecho que o
  ULTRON escreveu — se você editou a nota depois, o desfazer recusa em vez de
  cortar o seu texto.

Nomes de nota são relativos ao vault; caminho absoluto, `..` e as pastas
internas (`.obsidian`, `.trash`) são recusados. A leitura automática não sai do
computador. `OBSIDIAN_ATIVO=0` desliga a integração inteira (leitura e escrita) e
`OBSIDIAN_RECALL=0` desliga a leitura automática (inclusive a nota de
preferências).

## Autoconhecimento

A cada resposta o ULTRON recebe um bloco curto gerado do sistema vivo: nome e
perfil ativos, versão do pacote, SO com build e arquitetura, núcleos e RAM,
quantidade de ferramentas por área e o jeito/voz em uso. Junto vão os limites
fixos do produto — não gera nem edita imagem, não edita vídeo, não envia
WhatsApp, não tem app de celular — e o resumo do portão de segurança.

O bloco é montado uma vez por processo (sem WMI nem PowerShell, para não atrasar
a resposta) e se atualiza em uma hora. Se a leitura falhar, ele diz que não sabe:
nunca inventa e nunca impede uma resposta. Trocar o perfil (U.L.T.R.O.N., JARVIS,
VISÃO, EDITH) muda o nome que o modelo declara; registrar uma ferramenta nova
muda a contagem sozinho.

## Voz

O reconhecimento usa o Google (online). Se o Windows tiver um reconhecedor de
fala pt-BR instalado, ele pode ser usado como reserva quando o Google falha
(`VOZ_NATIVA=auto`) ou preferido (`VOZ_NATIVA=sempre`); `VOZ_NATIVA=nunca`
desliga. Sem o pacote de fala pt-BR, o caminho nativo fica inativo e o Google
segue como padrão. Para habilitar, instale o pacote de fala em **Configurações ›
Hora e idioma › Idioma e região**.

### Escuta mais precisa

Quatro ajustes trabalham juntos para o ULTRON entender melhor a sua voz:

- **Recalibração automática do limiar**: além da calibração ao abrir, o limiar
  de volume é reajustado ao ruído atual do ambiente a cada 5 minutos sem comando
  reconhecido ou após 3 "não entendi" seguidos. Nunca recalibra enquanto o
  ULTRON está falando, para não capturar o próprio eco.
- **VAD (detecção de atividade de voz)**: o corte de início/fim da fala deixa de
  ser só volume. Se o pacote `webrtcvad` estiver instalado, ele é usado; caso
  contrário, um VAD em Python puro olha a energia nas bandas da fala humana
  (300–3400 Hz), a taxa de cruzamento por zero e o limiar calibrado — assim uma
  pausa natural ou um "s" final mais fraco não cortam a frase no lugar errado.
- **Dicionário de correções pessoais**: quando você corrige ("não, eu disse
  Rocket League"), o par (o que ele ouviu → o que você disse) é salvo em
  `dados/correcoes_voz.json` e aplicado nas próximas transcrições parecidas. Se
  só uma palavra mudou ("abri" → "abra"), ele aprende a palavra e a correção vale
  em qualquer comando; se você corrigiu só um trecho ("Rocket League"), ele
  guarda o trecho e não engole o verbo. É local, sem nuvem e só para a sua voz.
- **Fuzzy matching generalizado**: a comparação aproximada que já existia para
  abrir programas passa a valer para o vocabulário de comandos. Se o
  reconhecimento distorcer uma palavra ("fexar aplicativo", "organizar
  arquibos"), o ULTRON reconhece a intenção em vez de responder "não entendi".
  Conjugações e plurais legítimos (desliga, toca, bloqueia, músicas) nunca são
  reescritos.

## Voz e Jeito

Ajustes (`Ctrl+,`) → **Voz e Jeito** reúne quatro abas:

- **voz**: os 15 timbres pt-BR reais do Edge TTS. Clicar em um cartão salva a
  escolha em `dados/voz.json`, aplica na hora e fala uma amostra curta. A voz
  reserva local (pyttsx3) continua disponível quando não há internet.
- **jeito**: 13 estilos de fala (equilibrado, brincalhão, profissional, mordomo,
  amigo, direto, motivador, narrador, amoroso, sarcástico, malandro, ignorante e
  rigoroso) independentes da identidade ULTRON/JARVIS/VISÃO/EDITH. O jeito muda
  o tom; **não** muda allowlist, confirmação, PIN nem qualquer regra de segurança.
  Todo estilo não neutro entra no prompt como um bloco de **modo de fala
  obrigatório**, com instrução e exemplos, válido em toda resposta — é o que
  impede o modelo de voltar sozinho ao tom neutro.
- **microfone**: escolha da entrada e pausa/retomada da escuta do núcleo.
- **sobre você**: nome, apelido, idade, gênero, como quer ser chamado e um texto
  livre. Tudo é opcional, fica em `dados/personalidade.json` e entra no prompt
  como informação — nunca como ordem. A **saudação ao abrir** liga ou desliga a
  frase falada quando a escuta é calibrada.

O botão **ver instrução** mostra exatamente o trecho de personalidade que a IA
recebe, sem chamar nenhum provedor.

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
python -m pytest tests -q            # suíte local (328 testes)
python tools/make_icon.py            # regera ULTRON.ico a partir da arte
python tools/build_setup.py --zip    # compila ULTRON.exe, ULTRON-Setup.exe e o ZIP
python launcher.py --doctor          # diagnóstico
```

O navegador controlado usa Playwright, que é opcional e fica fora do
`requirements.txt` para não pesar a instalação: `pip install playwright` e
`python -m playwright install chromium`. Sem ele, as ferramentas de navegador
explicam o que falta em vez de quebrar. A webcam e os gestos usam
`opencv-python-headless`, que já está nas dependências.

Estrutura:

| pasta | o que é |
|---|---|
| `electron/site/` | interface (HTML/CSS/JS, sem framework) |
| `electron/` | shell Electron: janela, ponte IPC, janela flutuante |
| `desktop_api.py` | API local só em 127.0.0.1, com token por sessão |
| `desktop_runtime.py` | núcleo: voz, comandos, eventos, bate-papo, atualização |
| `palco.py` | palco da interface: valida mídia e publica o que aparece no lugar do núcleo |
| `desfazer.py` | diário local e inversas das operações de arquivo, com Lixeira |
| `cerebro.py`, `ferramentas.py` | IA e ferramentas que agem no PC |
| `arquivos.py`, `hardware.py` | ZIP seguro/organização de pastas e relatório de hardware |
| `navegador.py`, `visao.py` | navegador controlado (Playwright) e webcam/gestos (OpenCV) |
| `fala.py` | correção de palavras mal ouvidas no comando de voz |
| `memoria.py`, `nuance.py` | memória SQLite entre sessões e leitura local de nuances |
| `obsidian.py` | leitura e escrita no vault do Obsidian (notas Markdown) |
| `personalidade.py`, `voz.py` | perfis, jeito, dados do usuário, saudação e vozes Edge TTS |
| `autoconhecimento.py` | bloco do system prompt gerado do sistema vivo (nome, versão, SO, habilidades, limites) |
| `voz_nativa.py` | reconhecimento de voz opcional do Windows (SAPI), offline |
| `seguranca.py`, `permissoes.json` | riscos, confirmações, PIN, allowlist |
| `installer/`, `tools/` | instalador e build |

## Segurança

Nenhuma saída da IA autoriza ação: intenções passam pela política local, ações críticas
pedem PIN (nunca por voz), e o gateway falha fechado. A chave de IA fica só no `.env`
local — nunca no código ou no histórico.

### Sessão local (1.19.0)

O Desktop abre bloqueado. A tela de desbloqueio usa o Windows Hello quando o PC
tem sensor; sem ele, use o `ULTRON_PIN` do `.env`. A sessão fica só em memória:
fechar o app ou bloquear/suspender o Windows volta ao estado bloqueado. Com a
sessão liberada, ações de risco ALTO locais e reversíveis rodam sem confirmação;
as irreversíveis e as que capturam tela/webcam ou tomam o mouse continuam
pedindo confirmação. Allowlist, comandos bloqueados, `DENY`, parada de
emergência e logs não mudam. O Telegram continua pedindo PIN.

### Histórico cifrado (1.19.0)

O conteúdo de `dados/ultron.db` (mensagens, fatos e lembretes) é cifrado com
AES-256-GCM usando a chave que o cofre protege com DPAPI. A migração do texto
antigo é automática na primeira operação de memória.

**Backup:** copie `dados/ultron.db` **e** `dados/.cofre.chave` juntos, na mesma
conta Windows do mesmo PC. Sem a chave, o histórico fica ilegível; o ULTRON não
gera outra por cima. Em outra conta ou outro PC, a DPAPI não decifra a chave.
