# Relatório — Registro emocional na voz (1.20.0)

## 1. Arquivos criados/alterados

### Criados
| Arquivo | Por quê |
|---|---|
| `registro.py` | Lista fechada de registros, parser local determinístico (`extrair`), leitura/clamp do mapa de prosódia e aplicação do delta sobre a voz configurada. Também concentra a instrução do system prompt. |
| `registros_emocionais.json` | Mapa configurável `registro -> {rate, pitch}` no estilo de `permissoes.json`. Valores fora de ±15 são cortados em memória; o arquivo pode ser editado à mão. |
| `tests/test_registro_emocional.py` | Testes novos, sem IA real (respostas simuladas). |

### Alterados
| Arquivo | Mudança |
|---|---|
| `cerebro.py` | Injeta `registro.INSTRUCAO_SISTEMA` no `_system()`; remove a marca no `_loop()` (caminho normal/ferramentas); no streaming, extrai o registro uma vez, tira a marca do texto e expõe o nome via `_FrasesComRegistro.registro`. Nenhuma chamada de IA adicional e nenhuma alteração em retry/fallback. |
| `voz.py` | `_sintetizar` aceita o registro e soma o delta a `config.VOZ_RATE`/`config.VOZ_PITCH` **na mesma chamada** do Edge TTS. `falar_partes` decide o registro no primeiro item e mantém até o fim; `falar` aceita `emocao` opcional (padrão neutro). |
| `README.md` | Seção curta em **Voz e Jeito** explicando o registro, o JSON e o limite de 15%. |
| `CHANGELOG.md` | Entrada 1.20.0 no topo; a 1.19.0 permanece como histórico. |
| `CONTEXTO-DO-PROJETO.md` | Versão do produto para 1.20.0. |
| `electron/package.json`, `package-lock.json`, `preload.js`, `mini-preload.js`, `README.md`, `site/index.html`, `site/preview.html`, `site/preview-mock.js` | Versão para 1.20.0 (meta, HUD, `/health` e README do Electron). |
| `desktop_api.py`, `LEIA-ME.txt`, `tests/test_desktop_api.py` | Versão para 1.20.0. |
| `tests/test_streaming_voz.py` | Dobras de teste aceitam o 3º argumento de `_sintetizar`; o teste de escuta manual isola `voz.transcricao` para exercitar o caminho Google de verdade. Nenhuma asserção foi enfraquecida. |

O painel **Voz e Jeito** e os 13 estilos de personalidade não foram alterados.

## 2. Registros e prosódia

Lista fechada (7): `neutro`, `lamento`, `encorajador`, `alerta`, `comemorando`, `serio`, `duvida`.

Deltas padrão (somados à voz do painel, máx. ±15):

| Registro | rate | pitch | Efeito |
|---|---|---|---|
| neutro | 0% | 0 Hz | exatamente a voz configurada hoje |
| lamento | -8% | -8 Hz | mais lento e mais grave |
| encorajador | +5% | +4 Hz | um pouco mais vivo |
| alerta | +10% | +3 Hz | rápido e tenso |
| comemorando | +8% | +6 Hz | rápido e agudo |
| serio | -5% | -5 Hz | contido |
| duvida | -3% | 0 Hz | leve hesitação |

Exemplo de prompt: `[[registro:lamento]] Lamento, senhor. Vamos melhorar a ideia para vender mais.`

## 3. Linha de base

- **Antes (primeira medição):** `pytest -q` → **576 passed, 6 failed**. As 6 falhas estavam todas em `tests/test_skills.py` e vinham de uma edição em andamento do próprio arquivo de teste (fora desta funcionalidade).
- **Depois:** `pytest -q` → **596 passed, 0 failed, 33 subtests passed**. `tests/test_skills.py` isolado → 32 passed. Suíte de segurança (`testes_seguranca.py`) → **58 testes, OK**. JS (`node --test electron/site/test/*.test.mjs`) → **34 passed**.
- A suíte cresceu porque o arquivo `test_skills.py` do usuário terminou de estabilizar durante a sessão; nada desta funcionalidade toca nele.

## 4. Testes novos — PASS

Todos em `tests/test_registro_emocional.py` (executados aqui, sem IA real):

| Caso | Resultado |
|---|---|
| Reconhece cada um dos 7 registros | PASS |
| Marca ausente → neutro, texto intacto | PASS |
| Marca desconhecida → neutro e marca removida | PASS |
| Marca malformada (`]` faltando) → neutro e sem vazamento | PASS |
| Espaços/maiúsculas na marca | PASS |
| `neutro` com qualquer voz configura os mesmos parâmetros | PASS |
| Delta soma sobre a voz do painel | PASS |
| JSON absurdo (9999, texto, bool, float) é cortado em ±15 | PASS |
| JSON ausente usa o padrão embutido | PASS |
| Log contém só `[registro] nome` | PASS |
| Streaming remove a marca da tela e da fala | PASS |
| Registro decidido uma vez por resposta | PASS |
| Resposta sem marca não quebra | PASS |
| Chamada de ferramenta sem texto final não quebra | PASS |
| Fala recebe texto limpo e o registro | PASS |
| Os 13 estilos continuam iguais sob neutro | PASS |
| Instrução de registro presente no system prompt | PASS |

## 5. Verificado x não verificado

**Verificado aqui (executado e passou):**
- Parser, clamp, log, integração com `cerebro.processar_stream`/`_loop` e com `voz.falar_partes`.
- Texto de tela/fala/histórico sem a marca.
- Regressão dos 13 estilos e da suíte inteira, incluindo segurança e JS.
- Nenhuma chamada de IA adicional: o registro vem da mesma resposta.

**Não verificado (precisa de Windows/áudio real):**
- Como cada delta **soa** de fato no Edge TTS (a API aceita os parâmetros, mas a percepção de "caricato" exige escuta humana).
- Comportamento do modelo real (Gemini/Groq/etc.) seguindo a marca em 100% das respostas; o parser já cobre ausência/erro caindo em neutro.
- Voz clonada na nuvem (Fish Audio): a API atual não recebe rate/pitch; nesse modo a fala sai sem o delta e o app usa a mesma chamada de antes. O Edge TTS (reserva) aplica o delta.
- Reserva offline (pyttsx3) fala em ritmo fixo, sem o delta.

## 6. Decisão de versão

**1.19.0 → 1.20.0 (minor).** O número do meio marca atualização grande. Esta entrega muda o prompt de sistema de toda resposta, adiciona um comportamento visível (reconhecimento do sentimento + prosódia) e um arquivo de configuração novo. Não é correção pontual (patch), e não quebra compatibilidade nem exige migração.

## 7. Limitações conhecidas

1. A prosódia é aplicada no caminho de **streaming** (o caminho normal da voz). No fluxo de texto/`processar()` e na reserva offline, o texto sai correto e sem marca, mas com a voz neutra.
2. O modelo pode ocasionalmente esquecer a marca; nesse caso a resposta é neutra por desenho — nunca quebra.
3. Uma marca colocada no meio da resposta (fora do começo) não é removida; a instrução pede explicitamente o começo.
4. O delta é somado ao ajuste do usuário; quem já usa `VOZ_RATE`/`VOZ_PITCH` muito extremos pode chegar a um total alto. O delta em si nunca passa de 15.
5. Logs nunca recebem o texto; somente `[registro] nome`.
