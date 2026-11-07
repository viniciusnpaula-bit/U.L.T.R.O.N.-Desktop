# Matriz de capacidades — catálogo dos 8 JARVIS → ULTRON Desktop

> **Versão avaliada:** 2.0.0 (código desta cópia)
> **Data:** 07/11/2026
> **Fonte do catálogo:** inventário funcional dos 8 repositórios (adewaskar,
> OpenJarvis, microsoft/JARVIS, jgm-source, sukkeesh, AnaaySampat,
> Aryan-0001, VarsshanCoder).
> **Fonte do estado atual:** `ferramentas.py` (78 ferramentas registradas),
> `desktop_api.py`, `electron/`, módulos da raiz e testes.
>
> Este documento compara **o catálogo** com **o que o ULTRON Desktop faz hoje**.
> Não é um roadmap fechado nem uma promessa: é um mapa de lacunas com evidência
> e prioridade. O catálogo descreve recursos *documentados* de oito projetos
> diferentes; nenhum deles tem tudo.

## Legenda

| Símbolo | Significado |
|---|---|
| ✅ | Existe e funciona no ULTRON Desktop hoje |
| 🟡 | Parcial: existe em versão reduzida ou por caminho indireto |
| ❌ | Falta |
| ⛔ | Fora do escopo deste produto (outro dispositivo/repositório) |
| 🔌 | Depende de serviço externo, chave ou aplicativo de terceiro |

Prioridade: **P1** = alto valor e esforço pequeno/médio; **P2** = valor claro,
esforço médio/grande; **P3** = desejável, sem urgência.

---

## Resumo

- **Feito (✅):** 46 capacidades
- **Parcial (🟡):** 26 capacidades
- **Falta (❌):** 27 capacidades
- **Fora de escopo (⛔):** 5 capacidades

O ULTRON já é forte no que o catálogo chama de "controle de computador",
"segurança", "memória local", "voz" e "interface". As lacunas se concentram em
**integrações de serviços** (e-mail, agenda, nuvem), **autonomia agendada**
(monitoramento, briefing, rotinas do usuário) e **pesquisa com fontes**.

---

## PARTE 1 — Inteligência artificial e raciocínio

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Conversa por texto e voz, com contexto e personalidade | ✅ | `cerebro.py`, `main.py`, `personalidade.py` (4 perfis, 13 jeitos) | — | — |
| Resumir, reescrever, traduzir, corrigir texto | 🟡 | Feito pelo modelo, sem ferramenta dedicada | Sem garantia de formato/idioma; depende do provedor | P3 |
| Raciocínio em etapas com uso de ferramentas | 🟡 | Loop de function calling em `cerebro.py` | Sem planejador explícito; sem paralelismo | P2 |
| Limite de ciclos para não rodar sem fim | ✅ | `MAX_PASSOS_FERRAMENTA = 6` | — | — |
| Seleção de modelo por complexidade/custo | 🟡 | Ordem de provedores + fallback + backoff (`config.py`) | Não mede custo/latência nem escolhe por capacidade | P3 |
| Comparar modelos por custo, latência e qualidade | ❌ | — | Sem benchmark; hoje é tentativa e erro | P3 |
| Modelos locais (Ollama etc.) | ❌ | — | 100% nuvem | P3 |
| Agentes especializados (pesquisador, telefone, desktop…) | ❌ | Um único loop com 78 ferramentas; skills como procedimento | Sem orquestração multiagente | P2 |
| Executar código como parte da solução (CodeAct) | ✅ | `rodar_codigo` (Python/Node, limite de 20 s) | Sem REPL persistente entre chamadas | P3 |
| Métricas por ferramenta (tempo, falha) | 🟡 | Log de segurança + `[tempo]` da 1ª frase | Sem telemetria local por ferramenta | P3 |

## PARTE 2 — Voz e comunicação

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| STT com mais de um motor | ✅ | Groq Whisper (`transcricao.py`), Google (`voz.py`), SAPI (`voz_nativa.py`) | — | — |
| VAD, calibração e correção de palavras | ✅ | `voz.py` (`_Vad`), recalibração automática, `correcoes_voz.py` | — | — |
| Palavra de ativação ("Ei, Jarvis") | 🟡 | Exige o prefixo "Ei, ULTRON" + janela de seguimento de 6 s | Não é motor de wake word; não escuta sem o prefixo | P2 |
| Push-to-talk e seleção de microfone | ✅ | `HOTKEY_FALAR`, tela de microfone, `testar_microfone` | — | — |
| TTS com várias vozes e motores | ✅ | Edge TTS (15 vozes), pyttsx3 offline, voz em nuvem opcional | Sem ElevenLabs/Gemini Live | — |
| Fala em streaming (primeira frase antes do fim) | ✅ | `cerebro.processar_stream` + `voz.falar_partes` | — | — |
| Interromper a fala do assistente (barge-in) | 🟡 | `Ctrl+Alt+X`, `Esc Esc`, parada de emergência | Não detecta a voz do usuário durante a fala | **P1** |
| Conversa contínua sem repetir o nome | ✅ | Janela de seguimento (`JANELA_SEGUIMENTO`) | Encerra por tempo | — |
| Diagnóstico de áudio e voz | ✅ | `testar_microfone`, `testar_voz`, tela de voz | — | — |
| Avatar com sincronização labial | ❌ | Orbe 3D/2D reage ao estado, sem rosto | Sem avatar humano | P3 |

## PARTE 3 — Pesquisa e internet

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Pesquisa web, notícias e vídeos | ✅ | `pesquisar_web` (DDG), `noticias`, `youtube` | Sem escolha de fonte | — |
| Navegador controlado (abrir, ler, clicar, preencher) | ✅ | `navegador.py` + Playwright opcional (8 ferramentas) | Exige instalar Playwright | — |
| Ler conteúdo de páginas e resumir | ✅ | `ler_pagina`, `ler_elementos_pagina` | — | — |
| Pesquisa com fontes e citações | 🟡 | O modelo pode citar o que leu | Sem pipeline que colete e confira evidências | P2 |
| Pesquisa profunda em várias etapas | ❌ | Uma rodada de busca por vez | Sem subperguntas, comparação entre fontes e relatório | P2 |
| Monitorar assunto e avisar mudanças | ❌ | — | Sem agendador nem histórico de verificações | P2 |

## PARTE 4 — Automação do dispositivo (celular)

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Controlar aplicativos Android | ⛔ | — | Produto separado (ULTRON Mobile) | — |
| Configurações do telefone (lanterna, volume, Wi-Fi) | ⛔ | — | Idem | — |
| Chamadas, SMS e WhatsApp | ⛔ | — | `autoconhecimento.py` declara esse limite | — |
| Mapas e navegação | 🟡 | `abrir_site`/`navegar` com URL do Maps | Sem integração nativa de rota | P3 |
| Alarmes, cronômetros e lembretes | 🟡 | `criar_lembrete`, `listar_lembretes`, `cancelar_lembrete` | Só lembrete único por minutos; sem recorrência nem alarme | **P1** |

## PARTE 5 — Controle de computador

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Abrir/fechar programas e jogos | ✅ | `abrir_programa`, `fechar_aplicativo`, `listar_jogos` | — | — |
| Janelas, teclado, mouse, rolagem, zoom | ✅ | `minimizar_janelas`, `pressionar_tecla`, `clicar`, `rolar_tela`, `ajustar_zoom` | — | — |
| Captura de tela, OCR e clique por texto | ✅ | `ver_tela`, `ler_texto_screen`, `localizar_na_tela`, `clicar_em_texto` | OCR depende do Tesseract instalado | — |
| Controle do navegador desktop | ✅ | `navegar`, `ler_pagina`, `clicar_pagina`, `preencher_campo` | — | — |
| Volume, brilho, modo escuro, mídia, bloquear | ✅ | `ajustar_volume`, `ajustar_brilho`, `alternar_modo_escuro`, `controlar_midia`, `bloquear_tela` | — | — |
| Desligar/reiniciar com confirmação | ✅ | `desligar_pc`, `reiniciar_pc`, `cancelar_desligamento` (com PIN) | — | — |
| Celular ↔ PC (pareamento, Wake-on-LAN, Tailscale) | ⛔ | — | Outro produto/rede | — |
| TV, ADB, Netflix | ⛔ | — | Sem suporte a Android TV | — |

## PARTE 6 — Visão computacional e multimídia

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Analisar imagens e screenshots | ✅ | `ver_tela`, `MODELOS_VISAO`, envio de imagem ao modelo | — | — |
| OCR local | ✅ | Tesseract + `pytesseract` (opcional) | Instalação manual | — |
| Foto por webcam | ✅ | `webcam_foto` (`visao.py`) | — | — |
| Gestos de mão e controle por gesto | 🟡 | 6 gestos (punho, indica, dois/tres dedos, mão aberta) + mouse | Sem mapa completo, calibração ou HUD por gesto | P3 |
| Detecção de objetos | 🟡 | Contornos/formas com OpenCV | Sem modelo de detecção (YOLO etc.) | P3 |
| Gerar imagens | ❌ | Declarado como limite em `autoconhecimento.py` | Exige API de imagem paga | P3 |
| Música e vídeo (Spotify, YouTube, palco) | ✅ | `spotify_*`, `youtube`, `controlar_midia`, `mostrar_na_interface` | Sem Netflix | — |
| Editar imagem/vídeo | ❌ | — | Fora do foco atual | P3 |

## PARTE 7 — Memória e personalização

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Memória de longo prazo entre sessões | ✅ | `memoria.py` (SQLite cifrado), recall por palavras até 120 dias | — | — |
| Busca semântica / embeddings | ❌ | — | Recall por palavra perde sinônimo/paráfrase | P2 |
| Memória documental (RAG de pastas) | 🟡 | Obsidian: `obsidian_buscar`, `obsidian_ler`, `obsidian_tarefas` | Sem indexação de documentos fora do vault | P2 |
| Fatos e preferências | ✅ | `lembrar_fato`, `esquecer_fato`, bloco de contexto | — | — |
| Excluir informação memorizada | 🟡 | `esquecer_fato`; "limpar" apaga só a sessão | Histórico antigo não tem exclusão pela interface | P2 |
| Resumo de sessão e continuidade | 🟡 | Histórico persistido + conversa da sessão | Sem resumo automático ao encerrar | P2 |
| Memória proativa / briefing | ❌ | — | Sem rotina diária nem sugestão por contexto | P2 |
| Personalidade, nome, jeito, voz | ✅ | `personalidade.py`, 13 estilos, registro emocional | — | — |

## PARTE 8 — Produtividade e organização

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Agenda e calendário | ❌ | — | Sem eventos, recorrência ou sincronização | **P1** |
| Tarefas e listas | 🟡 | `obsidian_tarefas` só lê checkboxes abertos | Sem criar/editar/concluir | P2 |
| Rotinas | 🟡 | `fluxos.py`: 3 fluxos fixos no código (`modo_jogo`, `abrir.rocket`, `minimizar`) | Usuário não cria; não agenda; não compartilha | **P1** |
| Briefing matinal | ❌ | Peças prontas: `clima`, `noticias`, `listar_lembretes` | Falta juntar e agendar | **P1** |
| Arquivos (listar, ler, criar, mover, apagar, ZIP, organizar) | ✅ | 10 ferramentas + `desfazer` + Lixeira | — | — |
| Converter imagem/PDF/HTML/comprimir | ❌ | Só ZIP | Sem `imagem → PDF`, `PDF → imagem`, `HTML → PDF` | P2 |
| Área de transferência com ações | ❌ | `pyperclip` só para digitar texto | Sem monitorar cópia e abrir painel de ações | P2 |

## PARTE 9 — Ferramentas técnicas

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Explicar, gerar e depurar código | ✅ | Modelo + `rodar_codigo` + leitura/escrita de arquivos | — | — |
| REPL persistente | ❌ | Execução isolada por chamada | Sem estado entre execuções | P3 |
| Cálculos, conversões e gráficos | 🟡 | O modelo calcula; não há ferramenta | Sem calculadora confiável nem conversão de unidade | **P1** |
| Sistema, hardware e diagnóstico | ✅ | `info_sistema`, `info_hardware`, `diagnostico.py`, `hardware.py` | — | — |
| Rede (DNS, speedtest, varredura) | 🟡 | `executar_comando` só aceita comandos de diagnóstico | Sem ferramenta dedicada nem resultado estruturado | P3 |
| QR Code | ❌ | — | Sem geração/leitura | P3 |

## PARTE 10 — Entretenimento e cotidiano

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Clima | ✅ | `clima` (atual + 3 dias) | — | — |
| Notícias | ✅ | `noticias` (manchetes + imagem no palco) | Sem filtro por fonte | — |
| Esportes, ações, cripto, câmbio | 🟡 | Só por `pesquisar_web` | Sem fonte estruturada nem alerta | P3 |
| Saúde, nutrição, receitas, treinos | ❌ | — | Sem base própria; modelo pode responder | P3 |
| Piadas e curiosidades | 🟡 | O modelo responde | Sem ferramenta/coleção local | P3 |
| Jogos | ❌ | — | Baixo valor para o produto | P3 |

## PARTE 11 — Integrações externas

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| E-mail (ler, resumir, enviar) | ❌ | O cofre já guarda `email_endereco`/`email_senha` | Sem IMAP/SMTP nem ferramenta | **P1** |
| Google Calendar / Drive / Tasks | ❌ | — | Exige OAuth e consentimento | P2 |
| Trello | ❌ | — | Exige API/chave | P3 |
| Telegram | ✅ | `telegram_bot.py` (canal com PIN) | Sem envio de arquivo/mídia | — |
| Slack / SMS | ❌ | — | Exige serviço externo | P3 |
| Spotify | ✅ | 4 ferramentas via Web API oficial (Premium para tocar) | — | — |
| Obsidian | ✅ | Leitura automática + 8 ferramentas + desfazer | — | — |
| MCP (servidores e ferramentas externas) | ❌ | Só ferramentas internas e skills Markdown | Sem cliente MCP | P2 |
| Plugins de terceiros | 🟡 | `skills.py` (procedimentos) + registro interno | Não carrega código de terceiro | P3 |

## PARTE 12 — Interface e experiência

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| HUD/orbe, temas, palco, HUD flutuante | ✅ | `electron/site/` (orbe 3D/2D), 4 temas, `palco.py`, mini-HUD | — | — |
| Avatar humano / holograma / lip-sync | ❌ | Orbe abstrato | Sem rosto animado | P3 |
| Personalização visual livre | 🟡 | 4 temas e modo 3D/2D | Sem cor livre, fundo próprio ou tamanho do núcleo | P3 |
| Painéis dinâmicos | 🟡 | Palco (vídeo/imagem/PDF/site/texto), diário, chat | Sem cartões configuráveis pelo usuário | P3 |
| Configurações, cofre, voz, microfone, fatos | ✅ | Gaveta de ajustes + rotas `/api/v1/*` | — | — |
| Gerenciar agentes/plugins | ❌ | — | Não há agentes nem plugins para gerenciar | P3 |
| Controlar a interface por voz | 🟡 | Comandos viram ferramentas | Tema, tamanho e painéis não são ferramentas | P3 |

## PARTE 13 — Autonomia e execução

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Tarefa multi-etapas com replanejamento | 🟡 | Até 6 rodadas de ferramentas; fluxos param na 1ª falha | Sem replanejar, retomar tarefa interrompida ou consolidar relatório | P2 |
| Verificar se a ação funcionou | 🟡 | Ferramentas devolvem resultado real; fluxo para na falha | Sem checagem visual pós-ação (print/OCR) | **P1** |
| Desfazer | ✅ | Arquivos e Obsidian com inversa e Lixeira | Volume, brilho e tema não são reversíveis | P3 |
| Execução agendada/periódica | ❌ | Só lembretes e `_agendar_fala` | Sem agendador de tarefas/fluxos | P2 |
| Interromper/cancelar | ✅ | `Esc Esc`, `Ctrl+Alt+X`, parada de emergência | Cancelar uma ferramenta específica em curso | P3 |
| Confirmação e autorização | ✅ | `seguranca.py` + `permissoes.json` (ALLOW/CONFIRM/DENY, PIN) | — | — |

## PARTE 14 — Segurança e diagnóstico

| Capacidade (catálogo) | Estado | No ULTRON hoje | Lacuna real | Prior. |
|---|---|---|---|---|
| Bloquear escrita por padrão e pedir confirmação | ✅ | Política local fail-closed, PIN para crítico | — | — |
| Sessão local e Windows Hello | ✅ | `sessao.py`, `biometria.py` (abre bloqueado) | — | — |
| Criptografia de dados e cofre | ✅ | AES-256-GCM + DPAPI (`cofre.py`, `memoria.py`) | — | — |
| Proteção contra SSRF e URLs privadas | ✅ | `electron/links.js`, allowlist de pastas/hosts | — | — |
| Logs e auditoria | ✅ | `seguranca.log` sem PIN nem chave | Sem painel de auditoria na tela | P3 |
| Diagnóstico do assistente | ✅ | `--doctor`, `diagnostico.py`, telas de teste | — | — |
| Atualização assinada com rollback | ✅ | Ed25519 + SHA-256 (`atualizacao.py`) | — | — |
| Recuperação de tarefa interrompida | ❌ | — | Sem fila/estado de tarefa | P2 |

---

## As 10 lacunas que eu atacaria primeiro

| # | Lacuna | Por que agora | Esforço | Risco |
|---|---|---|---|---|
| 1 | **Barge-in automático** (parar a fala ao detectar voz) | É a diferença entre "assistente" e "rádio"; VAD e `parar_fala` já existem | M | Falso positivo com ruído; precisa de limiar e teste em hardware real |
| 2 | **E-mail via IMAP/SMTP** | O cofre já tem os campos; ler/resumir/enviar é o pedido mais comum de assistente pessoal | M | Envio exige confirmação explícita; senha de app, nunca a senha da conta |
| 3 | **Agenda local + lembretes recorrentes** | Hoje só existe lembrete de "daqui a N minutos"; agenda é o que falta para o dia a dia | M | Recorrência e fuso; não sincronizar com Google ainda |
| 4 | **Briefing matinal agendado** | Clima, notícias e lembretes já existem; falta juntar e disparar | P/M | Precisa do agendador do item 3 |
| 5 | **Rotinas criadas pelo usuário** | `fluxos.py` é fixo no código; o usuário não consegue criar nem agendar | M | Cada passo continua passando pelo portão de segurança |
| 6 | **Verificação visual pós-ação** | `ver_tela`/OCR existem; conferir se o clique abriu a tela certa evita "mentira de conclusão" | P/M | Custo de uma captura por ação sensível |
| 7 | **Painel de área de transferência** | `pyperclip` já é dependência; alto valor e código pequeno | P/M | Conteúdo copiado é sensível: não persistir sem pedido |
| 8 | **Calculadora e conversões** | Evita erro aritmético e de unidade do modelo; ferramenta pequena e testável | P | Baixo |
| 9 | **Pesquisa profunda com fontes** | Separa o ULTRON de "chat que busca"; exige pipeline, não só tool | M/G | Custo de várias buscas; limite de tempo e citações obrigatórias |
| 10 | **Busca semântica na memória** | Recall por palavra já perde paráfrase; cresce com o tempo | M/G | Embeddings locais ou API; privacidade do histórico |

### Ganhos rápidos (P) fora do top 10

- Conversões de arquivo (`imagem → PDF`, `PDF → imagem`, comprimir): Pillow já
  está instalado.
- Comandos de voz para tema, modo 3D/2D e tamanho do núcleo.
- Cancelar uma ferramenta em execução (além da parada de emergência).
- Filtro de fonte em notícias e clima por cidade padrão.

---

## O que eu **não** traria

| Item do catálogo | Motivo |
|---|---|
| Controle de Android, TV, chamadas, SMS, WhatsApp | Outro produto (ULTRON Mobile) e outras permissões; no Desktop seria emulação frágil |
| Pareamento celular↔PC, Wake-on-LAN, Tailscale | Infraestrutura de rede inteira para um caso de uso que o repositório Mobile já cobre |
| Sete tipos de agente (orchestrator, react, openhands, rlm…) | O loop atual com 6 rodadas resolve o caso real; multiagente multiplica custo, latência e superfície de erro |
| Benchmark de modelos com custo/latência | Útil para pesquisa, não para o usuário; o fallback atual já evita ficar sem resposta |
| Avatar humano com lip-sync | Alto custo visual e de manutenção; o orbe já comunica estado sem prometer um rosto |
| Jogos, piadas, receitas, esportes, finanças | Baixo valor para um assistente de PC; o modelo responde quando perguntado |
| Netflix e serviços sem API pública | Sem caminho legítimo e estável |
| Geração de imagem/vídeo | Custo por chamada e revisão de segurança; hoje é limite declarado e correto |

---

## Observações de método

1. **"Documentado" não é "pronto".** O catálogo descreve READMEs e docs; vários
   recursos dos oito projetos são condicionais (API paga, plugin, ADB, Android
   específico) ou experimentais.
2. **O ULTRON tem vantagem que o catálogo não mostra:** política local
   fail-closed, PIN, sessão que morre ao bloquear, criptografia em repouso,
   atualização assinada e diário de desfazer. Nenhum dos oito repositórios
   documenta esse conjunto com a mesma profundidade.
3. **Contagem:** 104 capacidades avaliadas — 46 ✅, 26 🟡, 27 ❌, 5 ⛔.
4. **Evidência:** cada linha aponta o módulo/ferramenta que a sustenta. Onde não
   há módulo, a linha está marcada como ❌ em vez de "o modelo deve dar conta".

## Próximo passo

Se este mapa estiver correto, o caminho natural é abrir um bead por lacuna P1
(1 a 6), na ordem acima, cada um com spec própria — e tratar o agendador
(item 3) como base para briefing, rotinas e monitoramento. Nada aqui foi
implementado; este documento só compara.
