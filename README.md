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

## Voz

O reconhecimento usa o Google (online). Se o Windows tiver um reconhecedor de
fala pt-BR instalado, ele pode ser usado como reserva quando o Google falha
(`VOZ_NATIVA=auto`) ou preferido (`VOZ_NATIVA=sempre`); `VOZ_NATIVA=nunca`
desliga. Sem o pacote de fala pt-BR, o caminho nativo fica inativo e o Google
segue como padrão. Para habilitar, instale o pacote de fala em **Configurações ›
Hora e idioma › Idioma e região**.

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
python -m pytest tests -q            # suíte local (307 testes)
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
| `personalidade.py`, `voz.py` | perfis, jeito, dados do usuário, saudação e vozes Edge TTS |
| `voz_nativa.py` | reconhecimento de voz opcional do Windows (SAPI), offline |
| `seguranca.py`, `permissoes.json` | riscos, confirmações, PIN, allowlist |
| `installer/`, `tools/` | instalador e build |
| `ULTRON-Mobile/` | app Android (projeto anterior, independente) |

## Segurança

Nenhuma saída da IA autoriza ação: intenções passam pela política local, ações críticas
pedem PIN (nunca por voz), e o gateway falha fechado. A chave de IA fica só no `.env`
local — nunca no código, no histórico ou no APK.
