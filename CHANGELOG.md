ULTRON Desktop 1.18.0 — escuta com Whisper grátis e conferência na dúvida

- Motor de escuta novo: o Groq Whisper `large-v3` no plano gratuito (2.000
  requisições/dia) passa a ser o primeiro a ouvir; se a chave faltar, a cota
  estourar ou a internet cair, o ULTRON volta sozinho para o Google e depois
  para o Windows, sempre sem cobrança. Áudio vai e volta em memória (PCM 16 kHz
  → WAV), sem arquivo temporário; o log guarda só motor, latência e confiança.
- Silêncio puro não gasta requisição nem vira texto: uma checagem local de
  energia descarta áudio sem fala antes de chamar a nuvem (o Whisper chegava a
  "inventar" palavras em silêncio).
- Despertar normalizado: "EIULTRON", "EIUTRON", "E ULTRON" e variantes viram
  "Ei, ULTRON" antes da busca, então o comando não se perde quando o Whisper
  gruda as palavras.
- Conferência automática: quando a confiança da transcrição é baixa, ou média
  com verbo de ação, o ULTRON repete o que entendeu antes de agir. Perguntas
  simples e fala clara seguem sem atrito; ações de risco continuam com a
  confirmação de sempre.
- Ajustes: `VOZ_MOTOR=auto|groq|google|nativo` e
  `VOZ_CONFERIR=auto|sempre|nunca` no `.env`.
- Testes: 410 Python e 14 Node.

ULTRON Desktop 1.17.0 — escuta mais precisa

- Recalibração automática do limiar de voz: além da calibração ao abrir, o
  limiar é reajustado ao ruído atual do ambiente a cada 5 minutos sem comando
  reconhecido ou após 3 "não entendi" seguidos. Nunca recalibra enquanto o
  ULTRON fala (evita capturar o próprio eco).
- VAD (detecção de atividade de voz): o corte de início/fim da fala deixa de
  ser só volume. Usa `webrtcvad` quando instalado; caso contrário, um VAD em
  Python puro analisa energia nas bandas da fala humana (300–3400 Hz), a taxa de
  cruzamento por zero e o limiar calibrado. Pausas naturais e consoantes finais
  fracas não cortam mais a frase no lugar errado, e a recalibração passa a
  valer de verdade quando a sala fica mais silenciosa ou mais ruidosa.
- Dicionário de correções pessoais: "não, eu disse X" grava o par (ouvido →
  dito) em `dados/correcoes_voz.json` e o aplica nas próximas transcrições
  parecidas. Quando só uma palavra mudou ("abri" → "abra"), aprende a palavra,
  então a correção serve para qualquer comando; quando a frase corrigida é só
  um trecho ("Rocket League"), guarda o trecho e não engole o verbo. Local, sem
  nuvem e só para a voz de quem usa.
- Fuzzy matching generalizado: a comparação aproximada que já existia para
  abrir programas passa a valer para o vocabulário de comandos ("fexar
  aplicativo" → "fechar aplicativo", "organizar arquibos" → "organizar
  arquivos"). Conjugações e plurais legítimos (desliga, toca, bloqueia,
  músicas) nunca são reescritos.
- Testes: 364 Python e 30 Node.

ULTRON Desktop 1.16.0 — autoconhecimento, vídeo no mudo e organizar arquivos

- Autoconhecimento em runtime: o system prompt passa a trazer, gerado do sistema
  vivo, o nome/perfil ativo, a versão do pacote, o SO com build e arquitetura, a
  contagem de ferramentas por área, os limites fixos do produto (sem gerar ou
  editar imagem, sem editar vídeo, sem WhatsApp, sem app de celular) e o resumo
  do portão de segurança. É montado uma vez por processo, sem WMI nem PowerShell,
  e falha em silêncio: nunca impede uma resposta.
- Renomear o perfil (U.L.T.R.O.N., JARVIS, VISÃO, EDITH) agora muda também a
  identidade que o modelo declara, em vez de um "Você é o ULTRON" fixo.
- Ferramenta nova registrada entra na contagem sozinha, em "outras" quando não
  tiver grupo — sem editar o prompt.
- Palco: vídeo começa no mudo (YouTube, Vimeo, link direto e arquivo local) e
  o som liga pelo botão "som" no cabeçalho. No player externo o botão recarrega
  sem o parâmetro de mudo; em vídeo local o áudio alterna na hora. Também
  resolve o autoplay que o Chromium bloqueia quando há som.
- Organizar arquivos ganhou três modos: por tipo (padrão), por data (Ano/Mês da
  última modificação) e por extensão (PDF, JPG...). `subpastas=true` inclui o que
  está dentro das subpastas. A prévia continua vindo antes da confirmação, nada é
  sobrescrito e o desfazer devolve cada arquivo ao caminho original, removendo
  inclusive as pastas de ano/mês criadas. Lixo de sistema, arquivos ocultos e
  restos de download (.tmp, .part, .crdownload) não são movidos. Nova categoria
  "Código" para .py, .js, .json, .html e afins.
- Testes: 328 Python e 30 Node.

ULTRON Desktop 1.15.0 — memória, voz nativa e Voz e Jeito

- Memória entre sessões em SQLite local (`dados/ultron.db`): recall determinístico
  por palavras dos últimos 120 dias, até 4 trechos, sem embeddings e sem nuvem.
  Não repete o histórico da sessão, redige chaves/tokens/PIN e sobrevive ao
  "limpar" (que apaga só a conversa exibida).
- Voz nativa opcional do Windows (SAPI): entra como reserva quando o Google falha
  (`VOZ_NATIVA=auto`) ou como preferência (`VOZ_NATIVA=sempre`); `nunca` desliga.
  Sem o pacote de fala pt-BR, o Google segue como padrão.
- Ajustes › Voz e Jeito: painel único com abas **voz**, **jeito**, **microfone** e
  **sobre você**; 15 timbres Edge TTS, 13 estilos independentes da identidade,
  dados opcionais do usuário e saudação ao abrir.
- Jeito com regra obrigatória: todo estilo não neutro leva ao topo do prompt um
  bloco “MODO DE FALA OBRIGATÓRIO — <estilo>”, com instrução e exemplos, válido
  em toda resposta. Corrige o caso em que “ignorante” respondia no tom normal.
- Correção: alternar a saudação não apaga mais os campos de “sobre você” ainda
  não aplicados; a saudação salva apenas a si mesma.
- Dependências atualizadas (grupo Python via dependabot) e lock alinhado ao
  ambiente testado.
- Testes: 307 Python e 30 Node.

ULTRON Desktop 1.14.0 — a interface vira instrumento

- Memória entre sessões: a cada resposta o ULTRON procura, no SQLite local,
  trechos de conversas dos últimos 120 dias que tenham a ver com o pedido e os
  usa como contexto. É recall determinístico por palavras (sem embeddings e sem
  nuvem), não repete o que já está no histórico e redige chaves/tokens/PIN antes
  de montar o prompt. "limpar" continua apagando só a sessão, não a memória.
- Nuances: leitura local de frustração, irritação, ansiedade, tristeza, confusão,
  animação e gratidão por léxico, negação, intensificadores, caixa e pontuação.
  O tom da resposta se ajusta; urgência é sinalizada sem virar diagnóstico.
- Precisão: o prompt passa a pedir pergunta curta quando o pedido tem duas
  leituras que mudam o resultado, e a fala atual sempre vence um trecho antigo.
- Voz nativa opcional: quando o Windows tem reconhecedor pt-BR (SAPI), ele entra
  como reserva se o Google falhar (`VOZ_NATIVA=auto`) ou como preferência
  (`VOZ_NATIVA=sempre`); `nunca` desliga. Sem o pacote de fala, nada muda e o
  Google segue como padrão. O áudio vira WAV temporário e é apagado.
- Novas variáveis: `RECALL_MSGS` (padrão 4), `RECALL_DIAS` (120) e `VOZ_NATIVA`
  (auto). `HISTORICO_MSGS` passa a 12 por padrão no exemplo.
- Ajustes › Voz e Jeito: um painel só, com quatro abas. **voz** mostra os 15
  timbres reais do Edge TTS em cartões; clicar salva, aplica e fala uma amostra.
  **jeito** oferece 13 estilos independentes da identidade (equilibrado,
  brincalhão, profissional, mordomo, amigo, direto, motivador, narrador, amoroso,
  sarcástico, malandro, ignorante, rigoroso) — nenhum altera as regras de
  segurança. **microfone** mantém a escolha da entrada e a pausa da escuta.
  **sobre você** guarda nome, apelido, idade, gênero, tratamento e um texto livre
  em `dados/personalidade.json`, além do interruptor de saudação ao abrir.
- Jeito com regra, não adjetivo: cada estilo não neutro agora leva ao topo do
  system prompt um bloco “MODO DE FALA OBRIGATÓRIO — <estilo>”, com instrução
  concreta, exemplos de abertura e a ordem de valer em toda resposta, com
  prioridade sobre o tom do perfil. Corrige o caso em que o jeito “ignorante”
  era salvo mas a resposta saía no tom normal. O bloco é só de fala e não altera
  nenhuma regra de segurança.
- Testes: 37 novos cobrindo nuances, recall (inclusive exclusão do histórico e
  redação de segredo) e o fallback de voz; 13 novos no painel Voz e Jeito
  (persistência de jeito, dados do usuário, saudação e validação da API) e 4
  novos no modo de fala obrigatório; suíte em 307 testes Python e 30 Node.
- Bate-papo: a barra de conversa virou uma aba com as 15 últimas mensagens, por
  voz ou texto, do usuário e do ULTRON. A contagem e os rótulos passam a falar
  em "mensagens" e "voz e texto"; "limpar" esvazia também a sessão do núcleo,
  sem as mensagens voltarem pela reconciliação de 20 s.
- Redesenho da superfície: fundo quase preto, fios de 1px no lugar de caixas,
  três níveis de texto e um único acento vivo. Os controles são texto; a
  moldura só aparece no hover e no foco.
- O campo de partículas ganhou profundidade: o ponteiro inclina a poeira em
  parallax e as partículas mais rápidas deixam um rastro curto. Os pontos
  vermelhos continuam orbitando o núcleo.
- A gaveta de ajustes entra e sai pela direita, com transição curta e
  interrompível: reabrir durante a saída devolve o painel de onde ele estava.
  Ela abre na hora, sem esperar a conexão com o núcleo.
- Ajustes começam pelo topo, não rolam na horizontal e usam uma seta desenhada
  nos selects, no lugar do controle nativo.
- O tratamento agora é único por perfil: ULTRON, JARVIS, VISÃO e EDITH guardam
  cada um o seu ("senhor", "meu senhor", ...). Trocar de perfil não sobrescreve
  o tratamento do outro; arquivos antigos migram o valor para o perfil ativo.
- Contraste revisado: texto secundário em 5,08:1 e anel de foco sólido de 2px.
  Com "menos movimento", o que desliza para de deslizar e a leitura continua.
- Palco: vídeo, imagem, PDF, site ou texto aparecem no lugar do núcleo, sem
  abrir outra janela. Arquivo local é servido por um esquema próprio e a
  interface recebe só um id temporário, nunca o caminho. PDF abre no
  visualizador do Windows; YouTube e Vimeo rodam em modo de privacidade.
- A ferramenta mostrar_na_interface entra no portão ferramentas.executar:
  texto, arquivo da allowlist e YouTube/Vimeo são risco baixo; site externo e
  mídia fora dos hosts conhecidos pedem confirmação.
- Desfazer: criar, mover, apagar, compactar, descompactar, organizar e criar
  site deixam uma inversa em um diário local (`dados/desfazer/`). O comando
  "desfazer" funciona sem IA, sempre pede confirmação e desfaz uma operação por
  vez.
- O desfazer confere o estado antes de agir: se o arquivo mudou, se o destino
  está ocupado ou se a pasta extraída ganhou conteúdo, ele recusa em vez de
  apagar o que o usuário editou. Item apagado volta pela Lixeira do Windows,
  casando pasta original, nome, tamanho e data. Caminhos protegidos e caminhos
  fora da pasta do usuário/allowlist nunca são tocados.
- O diário é atômico, tem trava, expira em 7 dias, guarda até 50 operações e
  não sai do computador. `pywin32` passa a ser dependência explícita no Windows
  para a restauração da Lixeira.
- Interface: o segundo comando digitado não era enviado. O objeto de reserva
  usado quando um elemento não existe não tinha `remove`, e a falha virava uma
  rejeição silenciosa ao adicionar a fala; corrigido e coberto por teste.
- Interface: a conversa digitada não é mais apagada pela reconciliação de 20 s;
  os turnos digitados passam a ser guardados na sessão do painel.
- Respostas a comandos digitados agora são faladas em segundo plano: o painel
  recebe o texto na hora e o áudio não trava o próximo comando.
- Palco: uma pasta também é aceita; o ULTRON mostra o arquivo mais recente do
  tipo pedido (vídeo, imagem ou PDF) e explica qual escolheu. Caminhos
  `file:///` são normalizados, sem abrir programa nem repetir a chamada.
- O laço de ferramentas passou de 4 para 6 passos, dando folga para pedidos que
  exigem listar a pasta, confirmar e mostrar a mídia na mesma tarefa.
- API local: as rotas de correção/exclusão de fatos e as de cofre voltaram a
  responder; ramos de POST duplicados dentro do GET foram removidos.

ULTRON Desktop 1.13.0 — uma interface só, sem painel duplicado

- Interface redesenhada: fundo quase preto, linhas finas, tipografia mono e um
  único acento vermelho. O núcleo mantém os pontos vermelhos orbitando.
- O antigo chat de sessão foi removido. Agora existe uma só conversa: o que é
  dito por voz e o que é escrito aparece no mesmo lugar, e "limpar" fica no
  cabeçalho da conversa.
- Ajustes abrem por padrão ao iniciar. O botão do topo alterna o painel e o
  conteúdo da câmara cede espaço, em vez de ficar coberto.
- Cada perfil de personalidade tem a sua cor própria (ULTRON vermelho, JARVIS
  ciano, VISÃO âmbar, EDITH verde), sem herdar a cor do tema ativo.
- Avisos do núcleo aparecem como aviso rápido e não poluem mais a conversa.
- Atalhos: Ctrl+1 recolhe a conversa, Ctrl+, abre Ajustes, Ctrl+K foca o campo
  de comando, Esc fecha Ajustes.

ULTRON Desktop 1.12.1 — a interface volta a conectar ao núcleo

- Corrigido: um nome de função errado em `app.js` (`salvarMicrophone`) lançava
  `ReferenceError` ao carregar a interface e interrompia a inicialização antes
  da conexão com o núcleo. O painel ficava em "CONECTANDO" e todo comando
  respondia "Núcleo desconectado — comando não enviado".
- Removidas ligações duplicadas de controles (microfone, testes de voz e
  atualização) que sobrescreviam os handlers corretos.
- Novo teste de interface quebra o CI quando um controle aponta para uma função
  inexistente ou é ligado duas vezes.

ULTRON Desktop 1.12.0 — novas plataformas de chave e links oficiais
- Novas plataformas de chave no cofre: OpenAI, OpenRouter, Mistral, DeepSeek,
  Cerebras, Together AI e xAI (Grok), além de Gemini, Groq e NVIDIA Build.
- Cada plataforma mostra o link oficial para criar a chave; o link abre no
  navegador do sistema e só domínios oficiais são aceitos.
- Salvar ou remover uma chave descarta os clientes em cache, então a chave nova
  passa a valer no comando seguinte, sem reiniciar o ULTRON.
- Provedor com chave salva é usado mesmo que não esteja em PROVEDORES.

ULTRON Desktop 1.11.0 — fluxos com etapas, lembretes canceláveis e controles do Windows

FLUXOS NOMEADOS (Fase 4)
- fluxos.py define sequências fixas no código: "abrir.rocket" (só o jogo),
  "modo_jogo" (jogo → Spotify → minimizar) e "minimizar".
- Cada passo usa uma ferramenta registrada pelo portão ferramentas.executar; não há
  caminho alternativo. Se uma etapa falha (erro, negação de segurança, cancelamento),
  o fluxo PARA e informa o nome da etapa; as seguintes não rodam.
- Ferramenta executar_fluxo disponível para a IA e botões "Fluxos rápidos" em Ajustes.
- Abertura de programa agora tenta confirmar o resultado; quando não consegue
  verificar, diz "não consegui confirmar que ele iniciou" em vez de afirmar.

LEMBRETES CANCELÁVEIS
- listar_lembretes mostra número, hora local e texto.
- Nova ferramenta cancelar_lembrete(numero|trecho): exige número da lista ou trecho
  com 3+ letras; trecho ambíguo pede o número; sem alvo, não apaga nada.
- Ajustes › Memória: lista de lembretes com botão "cancelar" (com confirmação).

CONTROLES DO WINDOWS (um por vez)
- ajustar_brilho (0–100) via WMI; quando o monitor não aceita, informa isso em vez
  de fingir sucesso.
- prever_organizacao: mostra a prévia (quantos arquivos por categoria) SEM mover
  nada; só pastas da allowlist de diretórios são aceitas.

TESTES
- 12 novos: ordem das etapas, parada na primeira falha nomeando a etapa, negação de
  segurança interrompendo, fluxo desconhecido sem execução, lembrete por número,
  por trecho, ambíguo e sem alvo.

ULTRON Desktop 1.10.3 — cofre de chaves de API (lugar seguro)

ONDE COLOCAR AS CHAVES, COM SEGURANÇA
- Nova seção "Chaves de API" em Ajustes: cola-se a chave e ela é gravada CIFRADA em
  dados/cofre.json. A tela nunca mostra a chave de volta — só o final (• • • • 7890)
  e de onde veio (cofre ou .env).
- Proteção em duas camadas: chave de criptografia AES-256-GCM protegida pelo DPAPI
  do Windows (CryptProtectData, por usuário/máquina) e o próprio arquivo com
  permissão restrita. Sem DPAPI (Linux/testes) o app usa chave local e DECLARA isso
  no status — nunca finge que está protegido.
- Precedência cofre → .env: quem já tem chave no arquivo antigo continua funcionando
  sem mudar nada; a chave do cofre, quando existe, vence.
- Botão "testar" por provedor: faz uma chamada mínima (lista de modelos) e diz se a
  chave foi aceita — sem gastar tokens e sem mostrar a chave.
- "remover" apaga do cofre e devolve a vez ao .env, quando houver.
- cofre.py aplica as chaves na inicialização e registra os valores na redação de
  logs (seguranca.redigir), então nenhuma chave aparece em log, histórico ou painel.
- dados/cofre.json e dados/.cofre.chave entram no .gitignore e ficam fora do ZIP.

ROTAS LOCAIS
  GET /api/v1/cofre · POST /api/v1/cofre {nome, valor} ·
  POST /api/v1/cofre/remover {nome} · POST /api/v1/cofre/testar {nome}

TESTES
- 6 novos: gravação cifrada, nada em texto claro no arquivo, status só com o final,
  remoção, credencial inválida e declaração da proteção em uso.

ULTRON Desktop 1.10.2 — memória consultável e contexto enxuto

MEMÓRIA
- Ajustes › Memória: lista os fatos guardados, com busca literal (sem curinga),
  "editar" (corrigir o texto) e "apagar" — sempre com confirmação antes.
- Rotas locais: GET /api/v1/fatos, POST /api/v1/fatos {id, texto} (corrigir) e
  {id} (apagar), GET /api/v1/lembretes.
- memoria.buscar_fatos, corrigir_fato, apagar_fato_por_id e fatos_centrais.
- Contexto curto: o system prompt recebe no máximo 8 fatos centrais (os mais
  recentes e mais curtos) em vez de todos. Menos tokens e menos exposição.
- Lembretes: a interface mostra o próximo com data/hora no fuso local e avisa, em
  texto, que só são disparados com o ULTRON aberto.

LIMITES
- O limite de 50 fatos e 300 caracteres por fato continua valendo (config.py).
- Ainda não há notificação de lembrete com o app fechado — está declarado na tela.

ULTRON Desktop 1.10.1 — voz confiável e personalidade configurável

VOZ
- Mensagens de erro em português com causa e ação (sem microfone, microfone
  desconectado, sem internet, fala não entendida, silêncio, áudio travado).
- escutar_detalhado(): o reconhecimento devolve as interpretações possíveis.
- Fala incerta: se duas leituras divergem num verbo de consequência (apagar,
  fechar, desligar) ou o comando contém um desses verbos com mais de uma leitura,
  o painel mostra as opções e nada é executado sem confirmação. O canal é o mesmo
  de confirmações (request_id + prazo); sem resposta = recusa.
- Ajustes › Voz: "testar microfone" (só mede nível local, nada é gravado nem
  enviado), "testar voz" (avisa que o texto vai ao Edge TTS para gerar o áudio),
  lista de 15 vozes pt-BR e botão para aplicar. A escolha fica em dados/voz.json e
  vale após reiniciar. A voz reserva local (pyttsx3) continua indicada na interface.

PERSONALIDADE
- personalidade.py: perfis ULTRON, JARVIS, VISÃO e EDITH, com tom, tamanho e
  tratamento configuráveis, gravados em dados/personalidade.json.
- Ajustes › Personalidade: trocar perfil, definir como o ULTRON te chama, ver a
  instrução gerada e restaurar o padrão.
- As regras de segurança do system prompt NÃO mudam com o perfil.

TESTES
- 11 novos: personalidade (padrão, persistência, arquivo corrompido, restaurar,
  perfil inválido) e fala incerta (queda de braço entre leituras, verbos de
  consequência, assunto neutro).

ULTRON Desktop 1.10.0 — IA em streaming e segurar para falar

IA EM STREAMING (voz imediata)
- cerebro.processar_stream() usa stream=True nos provedores compatíveis com OpenAI
  (Gemini, Groq, NVIDIA) e entrega FRASES COMPLETAS conforme chegam.
- voz.falar_partes() sintetiza em paralelo: a 1ª frase toca enquanto o resto ainda
  está sendo gerado (voz.falar continua igual para quem chama com texto pronto).
- Ferramentas não fazem streaming: continuam no fluxo normal, com o mesmo portão
  ferramentas.executar e o mesmo fallback entre provedores.
- Se o streaming falhar (rede, provedor, resposta vazia), a resposta cai no modo
  normal automaticamente — nenhum caminho fica sem resposta.
- Log [tempo] 1º áudio e [tempo] 1ª frase falada para medir a melhora.
- A interface continua recebendo a resposta completa (bat-papo e câmara iguais).

SEGURAR PARA FALAR
- HOTKEY_FALAR (padrão ctrl+alt+espaco; vazio desliga) em config.py e .env.example.
  Não conflita com HOTKEY_PARAR (ctrl+alt+x).
- Enquanto a combinação está pressionada o núcleo grava; ao soltar, o texto vai para
  o mesmo fluxo de comando (sem "Ei, Ultron" e sem esperar silêncio).
- Nunca grava com a escuta pausada. voz.Ouvido.escutar_manual + _gravar(gatilho=...).

TESTES
- 6 testes novos: 1ª frase antes da última, parada interrompe, frases fechadas,
  falha do stream cai no modo normal, escutar_manual pausado e com gatilho.

ULTRON Desktop 1.9.9 — limpeza, assinatura das atualizações e legibilidade

LIMPEZA (nada usado ficou para trás)
- Binários ULTRON.exe / ULTRON-Setup.exe saíram do versionamento (*.exe e build/ no
  .gitignore). Continuam sendo gerados por tools/build_setup.py e continuam no ZIP.
- Uma cópia só de cada imagem: o ícone vive em electron/assets/ULTRON.ico; a logo
  U.L.T.R.O.N.-Logo.png segue na raiz e em electron/site/icons/.
- Removidos por não terem uso: desktop_ui.py (painel tkinter antigo),
  tests/test_desktop_ui.py, electron/site/protocol/, ULTRON-icon.svg,
  tools/sincronizar_local.py e os .bat redundantes (iniciar.bat, iniciar_bandeja.bat,
  iniciar_texto.bat, instalar_inicio_desktop.bat e os três de electron/).
  Mantidos: iniciar_desktop.bat (reserva do atalho) e testar_seguranca.bat.
- NOTAS-RECONSTRUCAO.txt virou CHANGELOG.md (mais recente primeiro).
- "bat-papo" corrigido para "bate-papo" em interface, README e notas.

ATUALIZAÇÃO ASSINADA
- SHA256SUMS.txt passa a vir acompanhado de SHA256SUMS.txt.sig (Ed25519). A chave
  pública é embutida no app; sem assinatura válida a atualização é recusada.
- tools/gerar_chaves.py cria o par fora do repositório (~/.ultron-signing/).
- tools/publicar.py assina o SUMS e envia o .sig no Release.

INTERFACE
- O mock de prévia saiu do app (preview.html só para navegador); o document.write
  bloqueado pela CSP foi removido.

ULTRON Desktop 1.9.8 — recolher as barras (bate-papo, eventos e sistema)

As três colunas viram barras recolhíveis, cada uma com o seu controle:

  [conversa]  [eventos]  [sistema ⚙]     <- botões no topo, com estado aceso
   Ctrl+1      Ctrl+2     Ctrl+,

- Bate-papo (esquerda): botão no topo e seta "‹" no cabeçalho da própria barra.
- Eventos (direita): botão no topo (o antigo "assumir que some em telas médias").
- Sistema (direita, por cima): abre pelo ⚙, recolhe pela seta "‹ recolher", Esc
  ou clique fora.
- A escolha é lembrada (localStorage): reabrir o app mantém o layout como você
  deixou. Grades animam com transição de 0,28 s.
- Em telas < 1320 px os eventos começam recolhidos e podem ser ligados no topo.

Correção de layout: `.drawer[hidden]` agora vence o `display: grid` — antes a barra
de sistema "fechada" continuava ocupando espaço/tempo de layout.

ULTRON Desktop 1.9.7 — botão "atualizar ULTRON" em três passos

O botão em Ajustes agora faz tudo numa sequência só:

  1. VERIFICAR — consulta o último Release do GitHub e compara com a versão instalada.
     Se já está atualizado, para aqui: "você já está na versão mais recente ✓".
  2. ATUALIZAR — baixa o ZIP, confere o SHA-256 publicado, faz backup e aplica o que
     pode na hora (Python, assets, interface já carregada fica para o fim). A barra
     de progresso mostra baixando → conferindo → aplicando.
  3. REINICIAR (só se necessário) — se algum arquivo em uso sobrou (ULTRON.exe,
     ULTRON-Setup.exe, .pyc), o app pergunta: "Reiniciar o ULTRON agora para
     concluir?". "Agora" dispara o script de troca e reabre sozinho; "depois"
     deixa o botão "reiniciar agora" disponível na barra.

Detalhes que evitam susto:
- needs_restart é verdadeiro apenas quando a cópia falhou por arquivo em uso; uma
  atualização de Python puro já vale no próximo comando, sem reiniciar.
- Arquivos de dados nunca são tocados: .env, dados/, logs/, venv/, node_modules.
- Ao reabrir, se havia atualização pendente de reinício, o botão reaparece.
- progresso em barra fina (2 px) abaixo dos botões; estados com cor (amarelo =
  baixando/pronto, verde = aplicado, vermelho = falhou).

Testes: 69 passando, incluindo dois novos — aplicação imediata e "só pede reinício
quando o arquivo está em uso". Teste de ponta a ponta contra o Release real:
1.0.0 → 1.9.6 aplicado, 93 arquivos, .env/dados/venv preservados.

ULTRON Desktop 1.9.6 — sistema como barra lateral e inicialização à prova de falha

SISTEMA (AJUSTES) VIROU BARRA LATERAL
- Deixou de ser uma gaveta de tela cheia: agora é uma barra encostada à direita,
  com borda arredondada, na mesma família visual do bate-papo (que fica à esquerda).
- Não cobre mais a câmara por inteiro e mantém a linha de comando livre.
- Fecha por três caminhos: seta "fechar", tecla Esc (listener em fase de captura,
  funciona com o foco em select/botão) e clique fora. Ctrl+, alterna.

ROBUSTEZ DA INTERFACE
- $() devolve um stub inerte quando um id não existe: a interface não morre mais
  por causa de um elemento ausente (era o que travava Esc/preview).
- O mock de prévia (preview-mock.js) é injetado de forma síncrona, só quando a
  ponte do Electron não existe; no app instalado ele nunca roda.
- z-index por camada: campo de partículas 0, palco 1, clique-fora 20, barra 21,
  confirmação 40, toast 50.

ESTÉTICA
- Campo de partículas mais discreto (opacidade 0.42) e vinheta mais suave: o
  núcleo continua sendo o único foco da tela.
- Seta/seta de recolher da barra no mesmo idioma do cabeçalho do bate-papo.

ULTRON Desktop 1.9.5 — repositório próprio, atualização confiável e mock fora do app

MUDANÇA DE REPOSITÓRIO
- O projeto agora vive em viniciusnpaula-bit/U.L.T.R.O.N.-Desktop (o repositório
  Projeto-U.L.T.R.O.N. fica só com o app Android antigo).
- atualizacao.py aponta para o repositório novo por padrão; ULTRON_UPDATE_REPO
  ainda permite sobrescrever.

ATUALIZAÇÃO MAIS ROBUSTA
- Fallback: se /releases/latest responder 403/404 (repositório privado), o app
  lista /releases e usa o estável mais recente.
- Estado em cache na memória: o painel não relê o disco a cada consulta.
- Repositório tornado público: a API pública do GitHub não mostra releases de
  repositório privado sem token.

INTERFACE
- preview-mock.js só é carregado quando NÃO existe a ponte do Electron (prévia no
  navegador). No app instalado, o mock não roda.
- Versão visível em toda a interface: 1.9.5.

PUBLICAÇÃO
- tools/publicar.py: build -> commit -> push na main -> Release com ZIP e
  SHA256SUMS.txt. Usa o gh de "C:\Program Files\GitHub CLI" mesmo fora do PATH.
- O Release é o que alimenta o botão "verificar atualização" do app.

ULTRON Desktop 1.9.4 — atualização pelo GitHub e zoom travado

ATUALIZAÇÃO
- Ajustes (Ctrl+,) tem a barra "verificar atualização". Ela consulta o último
  Release de viniciusnpaula-bit/Projeto-U.L.T.R.O.N., compara versões e mostra as
  novidades.
- Fluxo: baixa o ZIP do Release -> confere o SHA-256 publicado no SHA256SUMS.txt
  -> extrai só código e assets (nunca dados do usuário) -> backup em
  %LOCALAPPDATA%\ULTRON\updates -> script .bat independente espera o ULTRON e o
  electron fecharem, troca os arquivos com robocopy /XD venv node_modules dados
  logs e reabre o app. Se a cópia falhar, restaura o backup automaticamente.
- Botão "desfazer" volta para o backup da última atualização.
- Sem SHA256SUMS.txt no Release a atualização é RECUSADA. Host fora do GitHub é
  recusado. HTTP sem TLS é recusado.
- Rotas locais novas: GET /api/v1/update, /api/v1/update/check; POST
  /api/v1/update/{apply,launch,rollback}.
- Para o botão encontrar pacote, cada Release precisa de:
    1) o ZIP ULTRON-Desktop-vX.Y.Z.zip como asset;
    2) SHA256SUMS.txt com o hash do ZIP.
  tools/build_setup.py --zip já gera os dois na pasta de saída.

ZOOM
- O zoom do Chromium foi desligado: Ctrl+roda, Ctrl +/-, Ctrl+0 e o gesto de
  pinça não ampliam mais. O fator volta a 100% ao abrir a janela (o Electron
  guardava o último por origem, por isso a interface reabria ampliada).
- window.ultron.setZoom(true) reativa, caso algum dia se queira acessibilidade.

ULTRON Desktop 1.9.4 — bate-papo de voz no painel

A coluna direita agora tem dois andares: em cima a CONVERSA DE VOZ (bate-papo), embaixo
a fita de eventos.

COMO FUNCIONA
- O núcleo publica cada fala reconhecida e cada resposta como evento
  conversation_turn (papel, texto, origem, horário). main.py ganhou o gancho
  `conversa` em modo_voz; desktop_runtime._registrar_conversa guarda os últimos 80
  turnos e GET /api/v1/conversation devolve o histórico da sessão.
- O painel pinta em bolhas: "você · voz" à direita com o aro do núcleo, "ultron" à
  esquerda. Fala escrita no campo aparece como "você · escrito", assim dá para
  distinguir o que foi falado do que foi digitado.
- A lista começa vazia com instrução ("Diga 'Ei, Ultron' — cada fala reconhecida e
  cada resposta aparecem aqui"), rola sozinha quando você está no fim e ganha um
  brilho rápido na fala que acabou de chegar.
- Selo "ao vivo" no cabeçalho só fica aceso quando o microfone está realmente
  capturando; pausado vira "pausado", sem captura vira "sem escuta".
- Botão "última ↓" volta ao fim da conversa; "limpar" (na fita) apaga a sessão toda.
- Turnos vêm do evento (tempo real) e são reconciliados a cada 20 s por
  /conversation, com chave papel+horário+trecho para não duplicar.
- Privacidade: o runtime passa cada texto por seguranca.redigir antes de guardar —
  PIN, chaves e tokens nunca entram no bate-papo. Há teste para isso.

ULTRON Desktop 1.9.4 — interface 2.0 (câmara do núcleo)

A interface antiga foi descartada por completo: sidebar de 7 páginas, cartões de
métrica, feed de atividade, barra de comando solta e duas áreas de escrita.

AGORA É UMA TELA SÓ
- Fundo: campo de partículas lento que acompanha a cor do tema.
- Núcleo: um "sol de vento" desenhado em canvas — halo atmosférico, cinco
  filamentos de plasma deformados por senóides, um horizonte nítido e uma pupila
  que respira. Substitui os anéis girando da versão anterior.
- A energia do núcleo é o estado REAL do núcleo: em silêncio ele respira devagar,
  enquanto você fala ele acelera, pensando/responsdendo ele pulsa forte, sem núcleo
  ele apaga. O rótulo (À ESCUTA / OUVINDO VOCÊ / PENSANDO / RESPONDENDO / EM
  SILÊNCIO) e a dica abaixo vêm do mesmo status da API.
- Resposta: uma frase grande no centro, que encolhe sozinha quando é longa
  (classe .long), com um ponto luminoso piscando ao lado.
- Verbos: as ações rápidas viraram pílulas discretas abaixo da resposta.
- Uma linha de comando só: prompt "›", campo, botão de microfone com estado e
  botão de enviar. O nível do microfone é uma linha fina embaixo dela.
- À direita, uma fita de eventos (hora + você/ultron/aviso). Substitui os quatro
  cartões, o feed e a lista de histórico antigos.
- Ajustes: uma gaveta única (Ctrl+,) com tema, microfone e canal local. As sete
  páginas viraram isso.
- Janela flutuante redesenhada no mesmo idioma: orbe em miniatura, resposta e
  seis verbos.

DETALHES QUE VALEM
- Temas (ULTRON/JARVIS/VISÃO/EDITH) agora trocam a cor viva do núcleo, do brilho,
  das bordas e do ponto de respiração — não só um acento na sidebar.
- Atalhos: Ctrl+, ajustes; Ctrl+K foca a linha de comando; Esc limpa/fecha.
- Acessibilidade: rótulos aria em todos os controles, aria-live no estado e na
  resposta, prefers-reduced-motion desliga toda animação.
- Janela estreita: a fita desce para baixo; altura pequena: núcleo menor e menos
  verbos. Sem scroll horizontal.
- Nenhum estado inventado: tudo desenhado vem de /status e /events. Métricas só
  as reais (cpu, ram, disco, contagem da sessão).

ARQUIVOS
- electron/site/index.html, style.css e app.js reescritos.
- electron/site/src/orb.js: novo núcleo (criarOrbe) e campo de partículas
  (criarCampo); estadoDoOrbe agora devolve também a dica em português.
- electron/site/mini-hud.{html,css,js} reescritos.
- electron/site/preview-mock.js: mock do núcleo só para pré-visualizar a tela no
  navegador; o Electron injeta a ponte real (preload.js).
- Testes da UI atualizados para a nova estrutura (a suíte continua em 55 testes).

ULTRON Desktop 1.9.4 — instalador único e ícone corrigido

INSTALADOR
- setup.bat, "ULTRON Desktop.exe" (launcher.cs) e iniciar_desktop.bat duplicado foram
  substituídos por um único ULTRON-Setup.exe compilado de installer/ultron_setup.py.
  Um .bat que dispara python/pip/npm e um PE sem assinatura que abre outro processo
  eram o que mais chamava atenção de antivírus. Agora há um programa só, com ícone,
  versão, descrição e assinatura de checksum (SHA256SUMS.txt).
- Instalação verificada antes de mexer em qualquer coisa: arquivos, caminho simples,
  permissão de escrita, espaço em disco e versão de Python (>=3.10, 64 bits) e Node (>=18).
- Passos idempotentes com marcadores (venv/.ultron-venv.json, venv/.ultron-deps.json,
  electron/node_modules/.ultron-electron.json): rodar de novo repara e não reinstala tudo.
- .env nunca é sobrescrito. Atalho no Menu Iniciar e na Área de Trabalho aponta para
  ULTRON.exe. Desinstalação remove só o atalho que aponta para esta pasta.
- Log de instalação em logs/setup.log, com segredos mascarados.

ÍCONE
- ULTRON.ico antigo: PNGs reais, mas a arte do brasão vinha sobre um quadrado escuro
  sólido, sem transparência, e alguns scanners estranham payload de ícone assim.
- Agora tools/make_icon.py recorta a arte, aplica transparência (preservando o aro
  vermelho) e gera 16/24/32/48/64/128/256 px. --check falha o build se o .ico quebrar.

LAUNCHER
- launcher.py compila para ULTRON.exe (windowed). Um único ponto de entrada:
  abre o painel, ou --texto / --bandeja / --diagnostico. Resolve o problema de raiz
  quando o .exe é executado a partir de uma pasta diferente da instalação.

CORREÇÕES
- main.py --testar voltou a funcionar (chamava pytest e abria o núcleo antes).
- Duas entradas de início automático (Ultron.vbs e ULTRON Desktop.vbs) podiam iniciar
  dois processos; a remoção agora limpa as duas.
- API local com porta preferida 3900: o launcher consegue saber quando o painel está
  pronto. Continua só em loopback, com fallback para porta livre.
- Testes de microfone não dependem mais da preferência salva na máquina de quem roda
  (falhavam em qualquer PC com microfone configurado). voz.py e microphone_devices.py
  toleram configuração/rede do PortAudio parcial.

ULTRON Desktop v1.6.1 — diagnóstico local e rastreamento seguro

- Diagnóstico limitado a verificações locais e passivas: não chama provedores, não executa ferramentas, não grava nem reproduz áudio e não captura tela.
- Rastreamento registra apenas rótulos internos permitidos para intenção, ferramenta, etapa e estado; textos livres não são gravados.
- A versão do aplicativo, da API e da interface foi atualizada para 1.6.1.
- Nova aba "Orbe" no menu: círculo com várias linhas ondulando. Quando VOCÊ fala, as linhas giram mais rápido e a cor fica mais forte e viva.
- Estados: ESCUTANDO (calmo), OUVINDO VOCÊ (rápido e vivo), PROCESSANDO, FALANDO (o ULTRON respondendo), PAUSADO/ERRO/OFFLINE (apagado).
- A cor segue o tema escolhido (canto superior): "ultron" = vermelho, "jarvis" = ciano (parecido com a referência).
- A aba tem campo de texto e botão de pausar/retomar escuta. A interface anterior continua igual.
- O orbe só consulta o núcleo (5x por segundo) enquanto a aba está aberta.
- Núcleo: novo campo "speaking" no status (ligado enquanto o ULTRON fala).

ULTRON Desktop v1.5.2 — resposta por voz mais rápida
- A fala é dividida em frases: a 1ª toca enquanto a próxima ainda está sendo gerada (antes esperava a resposta inteira).
- O Groq gpt-oss passa a usar raciocínio "low" (REASONING_EFFORT no .env; vazio desliga). Se a API recusar, volta ao normal sozinho.
- Silêncio que encerra sua fala: 0,7 s (antes 1,0 s). Ajustável em SILENCIO_FIM no .env.
- Medição: logs/ultron.log registra "[tempo] reconhecimento de voz", "[tempo] IA" e "[tempo] 1º áudio" a cada comando.
- Novo: testes_latencia.py.

ULTRON Desktop v1.5.1 — correções de segurança e estabilidade
- abrir_site: endereço com ?, # ou muito longo agora pede confirmação (evita vazar dados por URL).
- lembrar_fato e ver_tela agora pedem confirmação (ver_tela envia o print da tela para a IA na nuvem).
- esquecer_fato com trecho vazio não apaga mais todos os fatos.
- Confirmação por voz só aceita: sim, confirmo, confirmado, autorizo, autorizado, positivo. "ok", "isso", "pode" etc. foram removidos.
- IA online: timeout de 15 s e 1 nova tentativa por provedor (antes 40 s e 2), para não travar a voz quando um provedor cai.
- Para não ser perguntado de novo, adicione "tela.ver", "memoria.lembrar" ou "site.abrir_com_dados" em allowlist.operacoes no permissoes.json.

ULTRON Desktop v1.5.0 — seleção de microfone

A versão 1.4.0 adiciona um painel flutuante arrastável que fica sobre outras janelas, com mini núcleo decorativo, status reais e ações rápidas encaminhadas ao mesmo fluxo de comandos da interface principal. A versão 1.4.1 aplica a logo oficial aos ícones, atalhos e interface.

A interface continua em Electron com HTML, CSS e JavaScript. A esfera central e os cartões de recursos sem estado verificável foram removidos. Conversa, microfone, ações rápidas, métricas e eventos continuam ligados ao núcleo e à API local.

O Desktop inicia um único DesktopRuntime, a API autenticada em 127.0.0.1 e a interface Electron. A escuta do microfone permanece sob controle do núcleo e o botão do painel pausa ou retoma esse mesmo fluxo. A interface não abre subprocessos de voz nem simula conexão ou métricas.

O token local é aleatório e temporário por execução. Ele é passado ao processo Electron pelo ambiente do processo e não é gravado em configurações. Ações e confirmações continuam sendo validadas pelo núcleo.

setup.bat instala dependências Python e Electron. O ZIP de distribuição é uma cópia de fonte verificada; ainda precisa de instalação em Windows com Python e Node.js para gerar o instalador executável.

Não distribua .env, credenciais, bancos locais, logs, caches, node_modules ou ambiente virtual.
