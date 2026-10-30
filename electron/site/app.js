import { RealTransport } from './src/real.js';
import { criarOrbe, criarCampo, estadoDoOrbe, normalizarModo } from './src/orb.js';
import { criarDesbloqueio } from './src/unlock.js';

/* Uma tela só. Nada aqui inventa estado: tudo desenhado vem do núcleo. */
// Elemento ausente devolve um stub inerte: a interface nunca morre por causa de um id.
const VAZIO = { textContent: '', value: '', hidden: true, dataset: {}, style: {}, className: '',
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  setAttribute() {}, removeAttribute() {}, getAttribute: () => null, append() {}, appendChild() {},
  prepend() {}, replaceChildren() {}, remove() {}, addEventListener() {}, removeEventListener() {},
  focus() {}, blur() {}, click() {}, querySelector: () => null, querySelectorAll: () => [],
  getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
  children: [], hidden: true, isConnected: false };
const $ = id => document.getElementById(id) || VAZIO;
const hudActions = Object.freeze({
  browser: 'Abra o navegador', spotify: 'Abra o Spotify', media: 'Pause ou retome a música',
  volume: 'Aumente o volume do PC', rocket: 'Abra o Rocket League', game: 'Ative o modo jogo',
  minimize: 'Minimize tudo',
});
const THEMES = ['ultron', 'jarvis', 'amber', 'emerald'];
const state = {
  connected: false, paused: false, history: [], commands: new Map(),
  pending: null, status: {}, lastResponse: '',
  turns: [],          // bate-papo: {role, text, source, at} — últimas 15
  turnKeys: new Set(),
  writing: 0,         // turnos que vieram do campo de texto nesta sessão
  palco: null,        // mídia exibida no lugar do núcleo
  palcoIgnorado: null, // id fechado localmente: não reabre por um status atrasado
  undo: [], undoErro: false, undoBusy: false, // diário read-only do dock direito
};
const transport = new RealTransport({ onEvent: handleEvent });
const desbloqueio = criarDesbloqueio({
  transport,
  aoMudarSessao: desbloqueada => {
    const botao = $('sessionButton');
    botao.textContent = desbloqueada ? 'liberado' : 'bloqueado';
    botao.dataset.state = desbloqueada ? 'on' : 'off';
  },
});

/* ── cena ────────────────────────────────────────────────────────────────── */
const CHAVE_MODO = 'ultron-core';
function lerModoNucleo() {
  try { return normalizarModo(localStorage.getItem(CHAVE_MODO)); } catch { return '3d'; }
}
let modoNucleo = lerModoNucleo();
const orb = criarOrbe($('orbCanvas'), { modo: modoNucleo });
const campo = criarCampo($('field'));
const orbMem = {};
let orbTimer = null, orbBusy = false;
orb.iniciar();
campo.iniciar();

function aplicarEstado(status) {
  const e = estadoDoOrbe(status, orbMem, performance.now());
  orb.definir(e);
  $('stateWord').textContent = e.rotulo;
  $('stateHint').textContent = e.dica;
  $('chamber').dataset.state = e.rotulo.toLowerCase();
  if ($('orbState')) $('orbState').textContent = e.rotulo;
}
async function orbTick() {
  if (orbBusy) return;
  orbBusy = true;
  try { aplicarEstado(await window.ultron.status()); } catch { aplicarEstado(null); } finally { orbBusy = false; }
}
function orbLoop(on) {
  if (on && !orbTimer) { orbTimer = setInterval(orbTick, 220); orbTick(); }
  if (!on) { clearInterval(orbTimer); orbTimer = null; }
}

/* ── tema ────────────────────────────────────────────────────────────────── */
function applyTheme(theme) {
  const selected = THEMES.includes(theme) ? theme : 'ultron';
  document.documentElement.dataset.theme = selected;
  try { localStorage.setItem('ultron-theme', selected); } catch {}
  document.querySelectorAll('#themeSwatches .swatch').forEach(node => node.setAttribute('aria-checked', String(node.dataset.theme === selected)));
  document.querySelectorAll('[data-theme-pill]').forEach(node => {
    node.setAttribute('aria-pressed', String(node.dataset.themePill === selected));
  });
  publishHudSnapshot();
}

/* ── núcleo 3D/2D ────────────────────────────────────────────────────────── */
/* A preferência é local e vale mais que o padrão: o chip e os botões da
   gaveta leem o mesmo estado, e o orbe só troca de ramo, sem recriar canvas. */
function aplicarModoNucleo(modo, { avisar = false } = {}) {
  modoNucleo = normalizarModo(modo);
  orb.definirModo(modoNucleo);
  try { localStorage.setItem(CHAVE_MODO, modoNucleo); } catch {}
  const chip = $('coreMode');
  chip.textContent = modoNucleo.toUpperCase();
  chip.setAttribute('aria-pressed', String(modoNucleo === '3d'));
  chip.title = `Alternar núcleo ${modoNucleo === '3d' ? '3D' : '2D'}`;
  document.querySelectorAll('[data-core]').forEach(node => {
    node.setAttribute('aria-checked', String(node.dataset.core === modoNucleo));
  });
  if (avisar) toast(`Núcleo ${modoNucleo.toUpperCase()}`);
}

/* ── HUD flutuante ───────────────────────────────────────────────────────── */
function publishHudSnapshot() {
  if (!window.ultron?.publishHudSnapshot) return;
  window.ultron.publishHudSnapshot({
    core: typeof state.status.core_running === 'boolean' ? (state.status.core_running ? 'Online' : 'Parado') : 'Indisponível',
    api: typeof state.status.api_running === 'boolean' ? (state.status.api_running ? 'Conectada' : 'Parada') : 'Indisponível',
    microphone: $('micVal')?.textContent || 'Indisponível',
    response: state.lastResponse || 'Indisponível',
    theme: document.documentElement.dataset.theme || 'ultron',
  }).catch(() => {});
}

/* ── utilidades ──────────────────────────────────────────────────────────── */
function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove('show'), 3200);
}

function setLed(id, status) {
  const node = $(id);
  if (!node) return;
  node.classList.remove('online', 'warn', 'error');
  if (status) node.classList.add(status);
}

function setMetric(name, value) {
  const node = $(name);
  if (node) node.textContent = value;
}

/* A resposta grande fica na câmara; a conversa guarda o mesmo texto. */
function responder(text) {
  const node = $('responseText');
  const clean = String(text || '').trim();
  node.textContent = clean || 'O núcleo recebeu o comando.';
  node.classList.toggle('long', node.textContent.length > 220);
  const reply = $('reply');
  reply.classList.remove('arriving');
  void reply.offsetWidth;      // reinicia a animação de chegada
  reply.classList.add('arriving');
  state.lastResponse = clean.slice(0, 500);
  if ($('orbResponse')) $('orbResponse').textContent = node.textContent;
  publishHudSnapshot();
}

/* ── bate-papo ────────────────────────────────────────────────────────────── */

/* Mesmo limite do núcleo: as 15 últimas mensagens, de voz ou de texto. */
const LIMITE_TURNOS = 15;

/* Identidade estável por turno: a API e o evento podem trazer a mesma fala. */
function chaveTurno(turno) {
  return `${turno.role}|${Math.round(Number(turno.at) || 0)}|${String(turno.text || '').slice(0, 40)}`;
}

function horaDe(segundos) {
  const d = Number(segundos) ? new Date(Number(segundos) * 1000) : new Date();
  return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function bolha(turno) {
  const usuario = turno.role === 'user';
  const item = document.createElement('article');
  item.className = `msg ${usuario ? 'user' : 'ultron'}`;
  item.dataset.key = chaveTurno(turno);

  const head = document.createElement('div');
  head.className = 'msg-head';
  const quem = document.createElement('span');
  quem.textContent = usuario ? (turno.source === 'texto' ? 'você · escrito' : 'você · voz') : 'ultron';
  const ponto = document.createElement('i');
  const time = document.createElement('time');
  time.textContent = horaDe(turno.at);
  head.append(quem, ponto, time);

  const corpo = document.createElement('p');
  corpo.textContent = String(turno.text || '');
  item.append(head, corpo);
  return item;
}

function adicionarTurno(turno, { fresh = true } = {}) {
  if (!turno || !turno.text || (turno.role !== 'user' && turno.role !== 'assistant')) return false;
  const key = chaveTurno(turno);
  if (state.turnKeys.has(key)) return false;
  state.turnKeys.add(key);
  state.turns.push(turno);
  while (state.turns.length > LIMITE_TURNOS) {
    state.turnKeys.delete(chaveTurno(state.turns.shift()));
  }

  const lista = $('commsList');
  $('commsEmpty')?.remove();
  const item = bolha(turno);
  if (fresh) item.classList.add('fresh');
  lista.append(item);
  while (lista.children.length > LIMITE_TURNOS) lista.firstElementChild.remove();
  const perto = lista.scrollHeight - lista.scrollTop - lista.clientHeight < 90;
  if (perto || turno.role === 'assistant') lista.scrollTop = lista.scrollHeight;
  $('commsCount').textContent = `${state.turns.length} ${state.turns.length === 1 ? 'mensagem' : 'mensagens'}`;
  return true;
}

function renderTurnos(turnos) {
  const lista = $('commsList');
  lista.replaceChildren();
  state.turns = [];
  state.turnKeys.clear();
  if (!turnos?.length) {
    const vazio = document.createElement('div');
    vazio.className = 'comms-empty';
    vazio.id = 'commsEmpty';
    vazio.innerHTML = '<b>Ainda não há mensagens.</b><span>Diga “Ei, Ultron” ou escreva abaixo — cada mensagem, de voz ou texto, aparece aqui.</span>';
    lista.append(vazio);
    $('commsCount').textContent = '0 mensagens';
    return;
  }
  for (const turno of turnos.slice(-LIMITE_TURNOS)) adicionarTurno(turno, { fresh: false });
  lista.scrollTop = lista.scrollHeight;
}

async function carregarConversa() {
  try {
    const dados = await transport.conversation();
    renderTurnos(dados?.turns || []);
  } catch { /* a API pode não ter a rota em versões antigas: a fita ainda mostra tudo */ }
}

/* ── diário do dock direito: GET /api/v1/undo, somente leitura ───────────── */
/* Cada linha é o que o núcleo já fez. Não há botão por linha: o comando real
   desfaz a última operação, não a linha clicada. Com a sessão bloqueada a lista
   é limpa e não volta a ser buscada — o diário contém caminhos do usuário. */
function linhaDesfazer(item) {
  const linha = document.createElement('article');
  linha.className = 'undo-row';
  linha.dataset.done = String(item?.desfeito === true);
  const cab = document.createElement('div');
  cab.className = 'undo-head';
  const op = document.createElement('b');
  op.textContent = String(item?.operacao || 'operação');
  op.title = op.textContent;
  const hora = document.createElement('time');
  hora.textContent = horaDe(item?.criado);
  cab.append(op, hora);
  if (item?.desfeito) {
    const selo = document.createElement('span');
    selo.className = 'undo-tag';
    selo.textContent = 'desfeito';
    cab.append(selo);
  }
  const resumo = document.createElement('p');
  resumo.textContent = String(item?.resumo || '');
  resumo.title = resumo.textContent;
  linha.append(cab, resumo);
  return linha;
}

function pintarDiario() {
  const lista = $('undoList');
  lista.replaceChildren();
  $('undoAction').disabled = state.undo.length === 0;
  if (state.undoErro) {
    const aviso = document.createElement('p');
    aviso.className = 'undo-empty err';
    aviso.textContent = 'diário indisponível';
    lista.append(aviso);
  } else if (!state.undo.length) {
    const vazio = document.createElement('p');
    vazio.className = 'undo-empty';
    vazio.textContent = 'nada para desfazer';
    lista.append(vazio);
  } else {
    for (const item of state.undo) lista.append(linhaDesfazer(item));
  }
  $('undoNote').textContent = state.undoErro ? 'diário indisponível'
    : state.undo.length ? `somente leitura · ${state.undo.length} de 10` : 'nada para desfazer';
}

function limparDiario() {
  state.undo = [];
  state.undoErro = false;
  pintarDiario();
}

async function carregarDiario() {
  if (state.status.session_desbloqueada !== true || state.undoBusy) return;
  state.undoBusy = true;
  try {
    const dados = await transport.undoList();
    state.undo = Array.isArray(dados?.itens) ? dados.itens : [];
    state.undoErro = dados?.indisponivel === true;
  } catch {
    state.undo = [];
    state.undoErro = true;
  } finally {
    state.undoBusy = false;
    pintarDiario();
  }
}

async function carregarHistorico() {
  const alvo = $('dockHistorico');
  if (state.status.session_desbloqueada !== true) { alvo.textContent = 'histórico local'; return; }
  try {
    const info = await transport.unlockInfo();
    const historico = info?.historico;
    alvo.textContent = historico
      ? `AES-256-GCM · ${historico.chave === 'indisponivel' ? 'chave indisponível' : 'cifrado'}`
      : 'histórico local';
  } catch {
    alvo.textContent = 'histórico local';
  }
}

/* ── relógio ─────────────────────────────────────────────────────────────── */
function updateClock() {
  const now = new Date();
  $('clockTime').textContent = now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  $('clockDate').textContent = now.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: 'short' }).replace('.', '');
}

/* ── conexão ─────────────────────────────────────────────────────────────── */
function connection(online) {
  if (!online) { state.status.api_running = undefined; state.status.core_running = undefined; }
  state.connected = online && state.status.core_running === true && state.status.api_running === true;
  if ($('sideStatus')) $('sideStatus').textContent = online ? 'CONECTADO' : 'DESCONECTADO';
  if ($('sideInfo')) $('sideInfo').textContent = online ? 'API local autenticada' : 'API local indisponível';
  $('sideDot')?.classList.toggle('offline', !online);
  if ($('heroStatus')) $('heroStatus').textContent = online ? 'API CONECTADA' : 'AGUARDANDO CONEXÃO';
  if ($('systemBadge')) $('systemBadge').textContent = online ? 'API CONECTADA' : 'API INDISPONÍVEL';
  setLed('headerLed', online ? 'online' : 'error');
  publishHudSnapshot();
}

function updateStatus(data) {
  const sessaoAntes = state.status.session_desbloqueada;
  data = state.status = { ...state.status, ...data };
  state.connected = data.api_running === true && data.core_running === true;
  state.paused = data.microphone_paused === true;
  sincronizarPalco(data.palco || null);
  desbloqueio.definirSessao(data.session_desbloqueada === true);
  const sessaoBotao = $('sessionButton');
  sessaoBotao.textContent = data.session_desbloqueada === true ? 'liberado' : 'bloqueado';
  sessaoBotao.dataset.state = data.session_desbloqueada === true ? 'on' : 'off';

  const mic = data.microphone_error ? 'erro' : state.paused ? 'pausado'
    : data.microphone_capturing ? 'capturando'
    : typeof data.microphone_state === 'string' && data.microphone_state ? data.microphone_state.toLowerCase()
    : 'indisponível';
  setMetric('micVal', mic);
  setMetric('coreVal', typeof data.core_running === 'boolean' ? (data.core_running ? 'Online' : 'Parado') : 'Indisponível');
  setMetric('apiServiceVal', typeof data.api_running === 'boolean' ? (data.api_running ? 'Conectada' : 'Parada') : 'Indisponível');
  setMetric('dockCore', $('coreVal').textContent);
  setMetric('dockApi', $('apiServiceVal').textContent);
  setMetric('dockMic', mic);
  $('dockSession').textContent = data.session_desbloqueada === true ? 'liberado' : 'bloqueado';
  setMetric('systemMicVal', mic);
  setMetric('coreState', data.core_running === true ? 'OPERACIONAL' : data.core_running === false ? 'NÚCLEO PARADO' : 'DESCONHECIDO');
  setMetric('signalCoreText', $('coreVal').textContent);
  setMetric('autostartVal', typeof data.autostart_installed === 'boolean' ? (data.autostart_installed ? 'início automático ativo' : 'início automático desligado') : 'início —');
  if ($('authStatus') && data.api_running) $('authStatus').textContent = 'sessão autenticada';
  if ($('uptime')) $('uptime').textContent = data.core_running && data.api_running ? 'CORE + API ONLINE' : 'AGUARDANDO NÚCLEO';

  setLed('headerLed', state.connected ? 'online' : data.api_running === false ? 'error' : 'warn');
  setLed('coreLed', data.core_running === true ? 'online' : data.core_running === false ? 'error' : 'warn');
  setLed('voiceLed', data.microphone_error ? 'error' : state.paused ? 'warn' : data.microphone_capturing ? 'online' : 'warn');

  /* nível do microfone vira uma linha fina sob a linha de comando */
  const threshold = Number(data.microphone_threshold);
  const level = Number(data.microphone_level);
  const hasLevel = Number.isFinite(threshold) && threshold > 0 && Number.isFinite(level) && level >= 0;
  const percent = hasLevel ? Math.min(100, Math.round(level / threshold * 100)) : null;
  const bar = $('micLevelBar');
  const meter = $('micMeter');
  bar.style.width = `${percent ?? 0}%`;
  meter.classList.toggle('live', percent !== null && !state.paused);
  setMetric('micLevelVal', percent === null ? '—' : `${percent}%`);
  const detalheMic = data.microphone_error || (state.paused ? 'Escuta pausada' : data.microphone_capturing ? 'Capturando áudio' : data.microphone_state || 'indisponível');
  if ($('micDetail')) $('micDetail').textContent = detalheMic;
  // #voiceSubStatus vive dentro do #reply[aria-live]: só escrever quando muda,
  // senão o polling de 750ms reanuncia a mesma frase a cada tique.
  const subVoz = $('voiceSubStatus');
  if (subVoz && subVoz.textContent !== detalheMic) subVoz.textContent = detalheMic;

  for (const [valueId, barId, value] of [['cpuVal', 'cpuBar', data.cpu_percent], ['ramVal', 'ramBar', data.ram_percent], ['diskVal', 'diskBar', data.disk_percent]]) {
    const n = value == null || !Number.isFinite(Number(value)) ? null : Math.max(0, Math.min(100, Number(value)));
    setMetric(valueId, n === null ? '—' : `${Math.round(n)}%`);
    const fill = $(barId);
    if (fill) fill.style.width = `${n ?? 0}%`;
  }

  const botao = $('micButton');
  const rotulo = $('micButtonLabel');
  botao.classList.toggle('active', !state.paused && Boolean(data.microphone_capturing));
  botao.setAttribute('aria-pressed', String(state.paused));
  botao.title = state.paused ? 'Retomar escuta contínua' : 'Pausar escuta contínua';
  botao.setAttribute('aria-label', botao.title);
  rotulo.textContent = state.paused ? 'pausado' : 'escutando';
  const live = $('commsLive');
  if (live) {
    const ativo = data.microphone_capturing && !state.paused && !data.microphone_error;
    live.classList.toggle('on', Boolean(ativo));
    live.textContent = ativo ? 'ao vivo' : state.paused ? 'pausado' : 'sem escuta';
    live.title = ativo ? 'Escuta contínua ativa' : state.paused ? 'Escuta pausada' : 'Microfone sem captura';
  }
  const voz = $('voiceStart');
  if (voz) voz.textContent = state.paused ? 'retomar escuta' : 'pausar escuta';
  setMetric('voicePageStatus', data.microphone_error || mic);

  if (state.pending === null) aplicarEstado(data);
  if (data.session_desbloqueada === true && sessaoAntes !== true) {
    carregarHistorico();
    carregarDiario();
  }
  if (data.session_desbloqueada !== true && (state.undo.length || state.undoErro)) limparDiario();
  if (data.session_desbloqueada !== true) $('dockHistorico').textContent = 'histórico local';
  publishHudSnapshot();
}

/* ── confirmação de segurança ────────────────────────────────────────────── */
function confirmation(event) {
  state.pending = event.request_id;
  const data = event.data || {};
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  const modal = document.createElement('div');
  modal.className = 'modal';

  const label = document.createElement('span');
  label.className = 'eyebrow';
  label.textContent = 'o núcleo precisa da sua autorização';
  const title = document.createElement('h2');
  title.textContent = 'Autorizar ação?';
  const message = document.createElement('p');
  message.textContent = data.message || 'O núcleo solicita autorização para continuar.';
  const risk = document.createElement('p');
  risk.className = 'muted';
  risk.textContent = `risco ${String(data.risk || 'não informado').toLowerCase()}`;

  const actions = document.createElement('div');
  actions.className = 'modal-actions';
  const deny = document.createElement('button');
  deny.className = 'ghost';
  deny.textContent = 'cancelar';
  const approve = document.createElement('button');
  approve.className = 'solid';
  approve.textContent = 'confirmar ação';

  let pin = null;
  if (data.requires_pin) {
    const pinLabel = document.createElement('label');
    pinLabel.textContent = 'PIN de segurança';
    pin = document.createElement('input');
    pin.type = 'password';
    pin.autocomplete = 'off';
    pin.inputMode = 'numeric';
    pin.maxLength = 128;
    pinLabel.append(pin);
    modal.append(pinLabel);
  }

  const answer = async approved => {
    approve.disabled = deny.disabled = true;
    try { await transport.confirm(state.pending, approved, approved ? pin?.value : undefined); }
    catch (error) { toast(`Não foi possível registrar a confirmação: ${error.message}`); }
    backdrop.remove();
    state.pending = null;
  };
  deny.onclick = () => answer(false);
  approve.onclick = () => answer(true);
  modal.addEventListener('keydown', ev => { if (ev.key === 'Escape') answer(false); });

  actions.append(deny, approve);
  modal.prepend(label);
  modal.append(title, message, risk, actions);
  backdrop.append(modal);
  document.body.append(backdrop);
  (pin || approve).focus();
}

/* ── palco: vídeo, imagem, PDF, site ou texto no lugar do núcleo ─────────── */
const PALCO_ROTULO = Object.freeze({ video: 'vídeo', imagem: 'imagem', pdf: 'PDF', site: 'site', texto: 'texto' });
// Vídeo começa mudo (autoplay confiável e sem susto). Em player de outra origem
// o som só liga recarregando sem o parâmetro de mudo — daí o estado fixo.
let palcoSomLigado = false;
let palcoSaindo = 0;

function palcoElemento(tag, atributos = {}) {
  const node = document.createElement(tag);
  for (const [nome, valor] of Object.entries(atributos)) {
    if (valor === undefined || valor === null || valor === false) continue;
    node.setAttribute(nome, String(valor));
  }
  return node;
}

function palcoAviso(texto) {
  const aviso = document.createElement('p');
  aviso.className = 'palco-aviso';
  aviso.textContent = texto;
  return aviso;
}

function esconderPalco({ avisar = false } = {}) {
  if (state.palco?.id) state.palcoIgnorado = state.palco.id;
  state.palco = null;
  palcoSomLigado = false;
  const painel = $('palco');
  $('chamber').dataset.palco = 'off';
  $('palcoSound').hidden = true;
  $('palcoSound').disabled = false;
  $('palcoSound').textContent = 'som';
  $('palcoSound').setAttribute('aria-pressed', 'false');
  $('palcoSound').title = 'Ligar o som do vídeo';
  $('palcoExternal').hidden = true;
  $('palcoExternal').dataset.url = '';
  $('palcoExternal').dataset.id = '';
  $('palcoExternal').textContent = 'abrir no navegador';
  $('palcoKind').textContent = 'palco';
  $('palcoTitle').textContent = '—';
  $('palcoNote').textContent = '—';
  $('palcoSource').textContent = '';
  // sai com o mesmo fade da gaveta; reabrir no meio cancela a saída
  clearTimeout(palcoSaindo);
  palcoSaindo = 0;
  const terminar = () => {
    painel.hidden = true;
    painel.classList.remove('saindo');
    $('palcoBody').replaceChildren();
  };
  if (painel.hidden || window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) {
    terminar();
  } else {
    painel.classList.add('saindo');
    palcoSaindo = setTimeout(terminar, 150);
  }
  if (avisar) transport.palcoFechar().catch(() => {});
}

function mostrarPalco(dados) {
  if (!dados || typeof dados !== 'object') return;
  const tipo = Object.hasOwn(PALCO_ROTULO, dados.tipo) ? dados.tipo : '';
  if (!tipo) return;
  const fonte = typeof dados.fonte === 'string' ? dados.fonte : '';
  const titulo = typeof dados.titulo === 'string' && dados.titulo
    ? dados.titulo : (PALCO_ROTULO[tipo] || 'palco');
  const local = fonte.startsWith('ultron-palco://media/');
  const corpo = $('palcoBody');
  corpo.replaceChildren();
  const botaoSom = $('palcoSound');
  palcoSomLigado = false;
  botaoSom.hidden = tipo !== 'video';
  botaoSom.disabled = false;
  botaoSom.textContent = 'som';
  botaoSom.setAttribute('aria-pressed', 'false');
  botaoSom.title = 'Ligar o som do vídeo';

  if (tipo === 'texto') {
    const pre = document.createElement('pre');
    pre.textContent = String(dados.conteudo || '');
    corpo.append(pre);
  } else if (tipo === 'video') {
    if (dados.embed && /^https:\/\//i.test(fonte)) {
      corpo.append(palcoElemento('iframe', {
        src: fonte, title: titulo, allowfullscreen: '',
        allow: 'autoplay; encrypted-media; picture-in-picture; fullscreen',
        referrerpolicy: 'strict-origin-when-cross-origin',
        sandbox: 'allow-scripts allow-same-origin allow-presentation',
      }));
    } else {
      const video = palcoElemento('video', {
        src: fonte, controls: '', autoplay: '', playsinline: '', preload: 'metadata', muted: '',
      });
      video.muted = true;
      video.addEventListener('error', () => corpo.replaceChildren(palcoAviso('Não consegui abrir este vídeo.')));
      corpo.append(video);
    }
  } else if (tipo === 'imagem') {
    const img = palcoElemento('img', { src: fonte, alt: titulo, decoding: 'async' });
    img.addEventListener('error', () => corpo.replaceChildren(palcoAviso('Não consegui abrir esta imagem.')));
    corpo.append(img);
  } else if (tipo === 'pdf') {
    // O visualizador embutido do Electron não abre o esquema ultron-palco.
    // O cartão diz o que é e o botão abre no visualizador do sistema, pelo id
    // opaco: o caminho do arquivo nunca chega ao renderer.
    const cartao = document.createElement('div');
    cartao.className = 'palco-doc';
    const selo = document.createElement('span');
    selo.className = 'palco-doc-selo';
    selo.textContent = 'PDF';
    const nome = document.createElement('p');
    nome.className = 'palco-doc-nome';
    nome.textContent = titulo;
    const dica = document.createElement('p');
    dica.className = 'palco-doc-dica';
    dica.textContent = local
      ? 'Abre no visualizador de PDF do Windows, fora do ULTRON.'
      : 'Abre no navegador do sistema, fora do ULTRON.';
    cartao.append(selo, nome, dica);
    corpo.append(cartao);
  } else if (tipo === 'site') {
    corpo.append(palcoElemento('iframe', {
      src: fonte, title: titulo, referrerpolicy: 'no-referrer',
      sandbox: 'allow-scripts allow-same-origin allow-forms',
    }));
  }

  $('palcoKind').textContent = PALCO_ROTULO[tipo] || 'palco';
  $('palcoTitle').textContent = titulo;
  $('palcoNote').textContent = typeof dados.nota === 'string' ? dados.nota : '';
  const externo = typeof dados.url === 'string' && /^https?:\/\//i.test(dados.url) ? dados.url : '';
  const abrirPdf = tipo === 'pdf' && local && Boolean(dados.id);
  const botaoExterno = $('palcoExternal');
  botaoExterno.hidden = !(externo || abrirPdf);
  botaoExterno.textContent = abrirPdf ? 'abrir PDF' : 'abrir no navegador';
  botaoExterno.dataset.url = externo;
  botaoExterno.dataset.id = abrirPdf ? String(dados.id) : '';
  $('palcoSource').textContent = externo
    ? (() => { try { return new URL(externo).hostname; } catch { return ''; } })()
    : (local ? 'arquivo local' : '');
  state.palco = dados;
  state.palcoIgnorado = null;
  const painel = $('palco');
  clearTimeout(palcoSaindo);
  palcoSaindo = 0;
  painel.classList.remove('saindo');
  painel.hidden = false;
  $('chamber').dataset.palco = 'on';
}

function palcoSom() {
  if (!state.palco || state.palco.tipo !== 'video' || palcoSomLigado) return;
  const botao = $('palcoSound');
  const corpo = $('palcoBody');
  const video = corpo.querySelector('video');
  if (video) {
    video.muted = !video.muted;
    botao.textContent = video.muted ? 'som' : 'mudo';
    botao.setAttribute('aria-pressed', String(!video.muted));
    botao.title = video.muted ? 'Ligar o som do vídeo' : 'Silenciar o vídeo';
    return;
  }
  const iframe = corpo.querySelector('iframe');
  const comSom = state.palco.fonte_com_som;
  if (!iframe || typeof comSom !== 'string' || !comSom) {
    botao.hidden = true;
    return;
  }
  // Player de outra origem: o áudio não pode ser mudado por dentro. Recarregar
  // sem o parâmetro de mudo é o caminho suportado pelos embeds.
  iframe.src = comSom;
  palcoSomLigado = true;
  botao.textContent = 'som ligado';
  botao.setAttribute('aria-pressed', 'true');
  botao.disabled = true;
  botao.title = 'Som ligado';
  $('palcoNote').textContent = 'som ligado';
}

function sincronizarPalco(dados) {
  if (!dados) {
    state.palcoIgnorado = null;
    if (state.palco) esconderPalco();
    return;
  }
  if (state.palco && state.palco.id === dados.id) return;
  if (state.palcoIgnorado && state.palcoIgnorado === dados.id) return;
  mostrarPalco(dados);
}

function fecharPalco() {
  if (!state.palco) return;
  esconderPalco({ avisar: true });
}

/* ── eventos do núcleo ───────────────────────────────────────────────────── */
function handleEvent(event) {
  if (event.event === 'ULTRON_ONLINE') {
    connection(true);
    aplicarEstado({ core_running: true, api_running: true });
  }
  if (event.event === 'ULTRON_OFFLINE') connection(false);
  if (event.event === 'SYSTEM_STATUS') updateStatus(event.data || {});
  if (event.event === 'NOTIFICATION') {
    const message = event.data.message || 'Notificação do núcleo.';
    const atividade = document.getElementById('activityText');
    if (atividade) atividade.textContent = message;
    toast(message);
  }
  if (event.event === 'CONVERSATION_TURN') {
    const turno = event.data || {};
    adicionarTurno({ role: turno.role, text: turno.text, source: turno.source || 'voz', at: turno.at || Date.now() / 1000 });
  }
  if (event.event === 'CONFIRMATION_REQUIRED') confirmation(event);
  if (event.event === 'SESSION_LOCKED') sessaoBloqueada();
  if (event.event === 'SPEECH_CONFIRM') confirmarFala(event);
  if (event.event === 'PALCO_SHOW') mostrarPalco(event.data || {});
  if (event.event === 'PALCO_HIDE') esconderPalco();
  if (event.event === 'COMMAND_RESULT') {
    const command = state.commands.get(event.request_id) || 'comando por voz';
    state.commands.delete(event.request_id);
    const value = event.data?.response;
    const text = typeof value === 'string' && value ? value : 'O núcleo recebeu o comando.';
    responder(text);
    carregarDiario();
    const escrito = state.writing > 0;
    if (escrito) state.writing -= 1;
    if (escrito) adicionarTurno({ role: 'assistant', text, source: 'texto', at: Date.now() / 1000 });
  }
}

/* ── envio ───────────────────────────────────────────────────────────────── */
async function send(text) {
  text = String(text || '').trim();
  if (!text) return false;
  if (!state.connected) { toast('O núcleo está desconectado.'); return false; }
  state.writing += 1;
  adicionarTurno({ role: 'user', text, source: 'texto', at: Date.now() / 1000 });
  responder('Enviado. Aguardando o núcleo…');
  $('stateWord').textContent = 'TRABALHANDO';
  orb.definir({ rotulo: 'TRABALHANDO', energia: 0.5, brilho: 1, humor: 'trabalhando', dica: 'Executando o pedido…' });
  try {
    const result = await transport.command(text);
    state.commands.set(result.operation_id, text);
    return true;
  } catch (error) {
    responder(error.message);
    toast(error.message);
    aplicarEstado(state.status);
    return false;
  }
}

async function toggleMicrophone() {
  try {
    const result = await transport.setMicrophonePaused(!state.paused);
    state.paused = result.paused;
    updateStatus({ core_running: true, microphone_paused: state.paused, microphone_state: state.paused ? 'pausado' : 'ativo' });
    toast(state.paused ? 'Escuta pausada.' : 'Escuta retomada. Diga “Ei, Ultron”.');
  } catch (error) { toast(`Não foi possível alterar o microfone: ${error.message}`); }
}

async function refreshMicrophones() {
  const select = $('microphoneSelect');
  const status = $('microphoneDeviceStatus');
  try {
    const result = await transport.listMicrophones();
    select.replaceChildren();
    if (!result.selected_available) {
      const missing = document.createElement('option');
      missing.value = '__missing__';
      missing.textContent = `indisponível — ${result.selected_name}`;
      select.append(missing);
    }
    for (const device of result.devices || []) {
      const option = document.createElement('option');
      option.value = device.id ?? '';
      option.textContent = device.name;
      select.append(option);
    }
    select.value = result.selected_available ? (result.selected_id ?? '') : '__missing__';
    status.textContent = result.selected_available
      ? `ativo: ${result.active_name || result.selected_name}`
      : `o microfone salvo (“${result.selected_name}”) não está conectado; escolha outra entrada.`;
  } catch (error) {
    status.textContent = `não foi possível listar as entradas: ${error.message}`;
  }
}

async function saveMicrophone() {
  const id = $('microphoneSelect').value;
  if (id === '__missing__') { toast('Escolha uma entrada disponível antes de aplicar.'); return; }
  $('saveMicrophone').disabled = true;
  try {
    const result = await transport.selectMicrophone(id || null);
    $('microphoneDeviceStatus').textContent = `ativo: ${result.active_name || result.selected_name}`;
    toast(`Microfone: ${result.selected_name}.`);
    await refreshMicrophones();
  } catch (error) {
    $('microphoneDeviceStatus').textContent = `não foi possível aplicar: ${error.message}`;
  } finally {
    $('saveMicrophone').disabled = false;
  }
}

async function refreshStatus(show = false) {
  try {
    const [health, status] = await Promise.all([window.ultron.health(), window.ultron.status()]);
    if (!health.ok || !status.core_running) throw new Error('Núcleo local indisponível.');
    connection(true);
    updateStatus(status);
    if (show) toast('Conexão com o núcleo confirmada.');
  } catch (error) {
    connection(false);
    if (show) toast(error.message);
  }
}


/* ── voz e jeito: testar microfone, escolher voz, estilo e dados ─────────── */
let vozCache = null;
let vozEscolhida = '';

function vozNota(texto, classe = '') {
  const alvo = $('testResult');
  if (!alvo) return;
  alvo.textContent = texto;
  alvo.className = `micro nano ${classe}`;
}

function separarRotulo(rotulo) {
  const texto = String(rotulo || '').trim();
  const achado = texto.match(/^(.+?)\s*\((.+)\)$/);
  return achado ? { nome: achado[1].trim(), detalhe: achado[2].trim() } : { nome: texto, detalhe: '' };
}

function pintarVoz(id) {
  vozEscolhida = id || '';
  const select = $('voiceSelect');
  if (select) select.value = vozEscolhida;
  document.querySelectorAll('#voiceCards [data-voz]').forEach(node => {
    node.setAttribute('aria-checked', String(node.dataset.voz === vozEscolhida));
  });
}

function renderVoiceCards(vozes, atual) {
  const grade = $('voiceCards');
  if (!grade) return;
  grade.replaceChildren();
  if (!vozes.length) {
    const vazio = document.createElement('p');
    vazio.className = 'choice-empty';
    vazio.textContent = 'nenhuma voz disponível agora. A reserva local continua funcionando.';
    grade.append(vazio);
    return;
  }
  for (const voz of vozes) {
    const { nome, detalhe } = separarRotulo(voz.rotulo || voz.id);
    const cartao = document.createElement('button');
    cartao.type = 'button';
    cartao.className = 'choice-card';
    cartao.dataset.voz = voz.id;
    cartao.setAttribute('role', 'radio');
    cartao.setAttribute('aria-checked', 'false');
    const titulo = document.createElement('b');
    titulo.textContent = nome || voz.id;
    const nota = document.createElement('span');
    nota.textContent = detalhe || voz.id;
    cartao.append(titulo, nota);
    cartao.addEventListener('click', () => escolherVoz(voz.id));
    grade.append(cartao);
  }
  pintarVoz(atual);
}

async function carregarVoz() {
  try {
    vozCache = await window.ultron.vozInfo();
    const select = $('voiceSelect');
    select.replaceChildren();
    const padrao = document.createElement('option');
    padrao.value = '';
    padrao.textContent = 'voz padrão do ULTRON';
    select.append(padrao);
    for (const voz of vozCache.vozes || []) {
      const opcao = document.createElement('option');
      opcao.value = voz.id;
      opcao.textContent = voz.rotulo || voz.id;
      select.append(opcao);
    }
    const atual = vozCache.preferencias?.voz || vozCache.ativas?.id || '';
    select.value = [...select.options].some(o => o.value === atual) ? atual : '';
    renderVoiceCards(vozCache.vozes || [], atual);
    $('voiceActive').textContent = `voz ativa: ${vozCache.ativas?.id || atual || '—'} · reserva: ${vozCache.ativas?.reserva || 'pyttsx3'}`;
  } catch (error) {
    vozNota(`não consegui ler as vozes (${error.message})`, 'err');
  }
}

async function escolherVoz(id) {
  if (!id) return;
  pintarVoz(id);
  vozNota('salvando a voz…');
  try {
    await window.ultron.vozSalvar({ voz: id });
    await carregarVoz();
    vozNota('voz salva. ouça o teste…');
    const r = await window.ultron.vozTestar('Olá. Esta é a minha voz.');
    if (r.ok) vozNota(`voz em uso: ${r.voz?.id || id}`, 'ok');
    else vozNota(r.erro || 'a voz foi salva, mas o teste não respondeu', 'err');
  } catch (error) {
    vozNota(`não consegui salvar a voz (${error.message})`, 'err');
  }
}

async function testarMicrofone() {
  vozNota('medindo o nível do microfone (1,2 s)…');
  try {
    const r = await window.ultron.microfoneTestar();
    if (r.ok) vozNota(`microfone ok · nível ${r.nivel} · limiar sugerido ${r.limiar_padrao}`, 'ok');
    else vozNota(r.erro || 'o microfone não respondeu', 'err');
  } catch (error) {
    vozNota(`falha no teste de microfone (${error.message})`, 'err');
  }
}

async function testarVoz() {
  vozNota('gerando o áudio de teste…');
  try {
    const r = await window.ultron.vozTestar('Ultrason, teste de voz concluído.');
    if (r.ok) vozNota(`${r.aviso || ''} voz: ${r.voz?.id || '—'}`, 'ok');
    else vozNota(r.erro || 'não consegui falar', 'err');
  } catch (error) {
    vozNota(`falha no teste de voz (${error.message})`, 'err');
  }
}

async function salvarVoz() {
  const voz = $('voiceSelect').value;
  if (!voz) { vozNota('escolha uma voz na lista antes de aplicar.'); return; }
  try {
    await window.ultron.vozSalvar({ voz });
    await carregarVoz();
    vozNota('voz salva. Use "testar voz" para ouvir.', 'ok');
  } catch (error) {
    vozNota(`não consegui salvar a voz (${error.message})`, 'err');
  }
}

/* ── personalidade: identidade, jeito, dados do usuário e saudação ────────── */
let perfilAtual = 'ultron';
let jeitoAtual = 'equilibrado';
let jeitosCache = [];
let saudacaoLigada = true;
// tratamento guardado por perfil: trocar de perfil não herda o do anterior
let tratamentosPorPerfil = {};

function pintarPerfil(perfil) {
  perfilAtual = perfil;
  document.querySelectorAll('[data-profile]').forEach(node => {
    node.setAttribute('aria-checked', String(node.dataset.profile === perfil));
  });
  const salvo = tratamentosPorPerfil[perfil];
  if (typeof salvo === 'string') $('tratamentoInput').value = salvo;
  $('headerProfile').textContent = String(perfil || 'ultron').toUpperCase();
}

function renderStyleCards(jeitos) {
  const grade = $('styleCards');
  if (!grade) return;
  grade.replaceChildren();
  for (const jeito of jeitos) {
    const cartao = document.createElement('button');
    cartao.type = 'button';
    cartao.className = 'choice-card';
    cartao.dataset.jeito = jeito.id;
    cartao.setAttribute('role', 'radio');
    cartao.setAttribute('aria-checked', 'false');
    const titulo = document.createElement('b');
    titulo.textContent = jeito.rotulo || jeito.id;
    const nota = document.createElement('span');
    nota.textContent = jeito.descricao || '';
    cartao.append(titulo, nota);
    cartao.addEventListener('click', () => escolherJeito(jeito.id));
    grade.append(cartao);
  }
}

function pintarJeito(jeito) {
  jeitoAtual = jeito || 'equilibrado';
  document.querySelectorAll('#styleCards [data-jeito]').forEach(node => {
    node.setAttribute('aria-checked', String(node.dataset.jeito === jeitoAtual));
  });
  $('headerStyle').textContent = jeitosCache.find(j => j.id === jeitoAtual)?.rotulo || jeitoAtual;
}

function pintarSaudacao(ligada) {
  saudacaoLigada = Boolean(ligada);
  const botao = $('greetingToggle');
  if (!botao) return;
  botao.setAttribute('aria-checked', String(saudacaoLigada));
  botao.textContent = `saudação ao abrir: ${saudacaoLigada ? 'ligada' : 'desligada'}`;
}

function preencherUsuario(usuario = {}) {
  if ($('userName')) $('userName').value = usuario.nome || '';
  if ($('userNickname')) $('userNickname').value = usuario.apelido || '';
  if ($('userAge')) $('userAge').value = usuario.idade || '';
  if ($('userGender')) $('userGender').value = usuario.genero || '';
  if ($('userAbout')) $('userAbout').value = usuario.sobre || '';
}

function dadosDoUsuario() {
  return {
    nome: $('userName')?.value.trim() || '',
    apelido: $('userNickname')?.value.trim() || '',
    idade: $('userAge')?.value.trim() || '',
    genero: $('userGender')?.value || '',
    sobre: $('userAbout')?.value.trim() || '',
  };
}

async function carregarPersonalidade() {
  try {
    const info = await window.ultron.personalidadeInfo();
    const atual = info.atual || {};
    tratamentosPorPerfil = { ...(atual.tratamentos || {}) };
    for (const p of info.perfis || []) {
      if (typeof p.tratamento === 'string') tratamentosPorPerfil[p.id] = p.tratamento;
    }
    jeitosCache = Array.isArray(info.jeitos) ? info.jeitos : [];
    renderStyleCards(jeitosCache);
    pintarPerfil(atual.perfil || 'ultron');
    pintarJeito(atual.jeito || 'equilibrado');
    $('tratamentoInput').value = atual.tratamento || tratamentosPorPerfil[atual.perfil] || '';
    preencherUsuario(atual.usuario || {});
    pintarSaudacao(atual.saudacao !== false);
    $('profileNote').textContent = `perfil ${atual.perfil || 'ultron'} · jeito ${atual.jeito || 'equilibrado'} · tratamento “${atual.tratamento || '—'}”`;
    $('profileNote').className = 'micro nano ok';
  } catch (error) {
    $('profileNote').textContent = `não consegui ler a personalidade (${error.message})`;
    $('profileNote').className = 'micro nano err';
  }
}

async function salvarPersonalidade({ usuario = false, saudacao = false } = {}) {
  try {
    const dados = {
      perfil: perfilAtual,
      tratamento: $('tratamentoInput').value.trim(),
      jeito: jeitoAtual,
    };
    if (usuario) dados.usuario = dadosDoUsuario();
    if (saudacao) dados.saudacao = saudacaoLigada;
    const salvo = await window.ultron.personalidadeSalvar(dados);
    tratamentosPorPerfil = { ...tratamentosPorPerfil, ...(salvo.tratamentos || {}) };
    tratamentosPorPerfil[salvo.perfil] = salvo.tratamento;
    pintarPerfil(salvo.perfil);
    pintarJeito(salvo.jeito);
    $('tratamentoInput').value = salvo.tratamento || '';
    // só repinta os campos quando eles vieram do servidor (botão aplicar):
    // salvar jeito/perfil/saudação não pode apagar o que ainda está sendo digitado
    if (usuario && salvo.usuario) preencherUsuario(salvo.usuario);
    pintarSaudacao(salvo.saudacao !== false);
    const nomeJeito = jeitosCache.find(j => j.id === salvo.jeito)?.rotulo || salvo.jeito;
    $('profileNote').textContent = `aplicado: ${salvo.perfil} · ${nomeJeito} · tratamento “${salvo.tratamento}”`;
    $('profileNote').className = 'micro nano ok';
    return salvo;
  } catch (error) {
    $('profileNote').textContent = `não consegui aplicar (${error.message})`;
    $('profileNote').className = 'micro nano err';
    return null;
  }
}

async function escolherJeito(jeito) {
  if (!jeito) return;
  pintarJeito(jeito);
  await salvarPersonalidade();
}

async function alternarSaudacao() {
  pintarSaudacao(!saudacaoLigada);
  try {
    // caminho próprio: salva apenas a saudação, sem reenviar campos em edição
    const salvo = await window.ultron.personalidadeSalvar({ saudacao: saudacaoLigada });
    pintarSaudacao(salvo.saudacao !== false);
    $('profileNote').textContent = `saudação ao abrir: ${saudacaoLigada ? 'ligada' : 'desligada'}`;
    $('profileNote').className = 'micro nano ok';
  } catch (error) {
    pintarSaudacao(!saudacaoLigada);
    $('profileNote').textContent = `não consegui salvar a saudação (${error.message})`;
    $('profileNote').className = 'micro nano err';
  }
}

async function previaPersonalidade() {
  try {
    const r = await window.ultron.personalidadePrevia();
    $('profileNote').textContent = r.instrucao;
    $('profileNote').className = 'micro nano';
  } catch (error) {
    $('profileNote').textContent = `não consegui montar a prévia (${error.message})`;
    $('profileNote').className = 'micro nano err';
  }
}

async function restaurarPersonalidade() {
  try {
    await window.ultron.personalidadeRestaurar();
    await carregarPersonalidade();
    $('profileNote').textContent = 'personalidade restaurada ao padrão.';
  } catch (error) {
    $('profileNote').textContent = `não consegui restaurar (${error.message})`;
  }
}

/* abas internas: voz · jeito · microfone · sobre você */
function mostrarAba(nome) {
  const abas = { voz: 'paneVoice', jeito: 'paneStyle', microfone: 'paneMic', sobre: 'paneAbout' };
  const botoes = { voz: 'tabVoice', jeito: 'tabStyle', microfone: 'tabMic', sobre: 'tabAbout' };
  for (const [chave, idPainel] of Object.entries(abas)) {
    const painel = $(idPainel);
    const botao = $(botoes[chave]);
    const ativo = chave === nome;
    if (painel) painel.hidden = !ativo;
    if (botao) botao.setAttribute('aria-selected', String(ativo));
  }
}


/* Confirmação de fala incerta: mostramos as interpretações e NADA é executado
   sem escolha. Cancelar significa não executar. */
function confirmarFala(event) {
  const dados = event.data || {};
  const opcoes = Array.isArray(dados.alternativas) && dados.alternativas.length ? dados.alternativas : [dados.fala];
  const linha = opcoes.map((opcao, indice) => `${indice + 1}. ${opcao}`).join('\n');
  const aceito = window.confirm(`Não entendi com certeza. ${dados.motivo || ''}\n\n${linha}\n\nExecutar a primeira interpretação?`);
  toast(aceito ? `confirmado: ${opcoes[0]}` : `descartado: ${opcoes[0]}`);
  // responde pelo canal oficial de confirmações (sem PIN: não é ação crítica)
  if (dados.request_id) {
    transport.confirm(dados.request_id, aceito).catch(() => {});
  }
}



/* ── cofre de chaves: salvar cifrado, testar e remover ───────────────────── */
/* A chave NUNCA volta para a tela: o status traz só o final mascarado e a fonte. */
function notaCofre(texto, classe = '') {
  const alvo = $('cofreNote');
  alvo.textContent = texto;
  alvo.className = `micro nano ${classe}`;
}

function pintarCofre(status) {
  const lista = $('cofreList');
  lista.replaceChildren();
  for (const item of status.itens || []) {
    const linha = document.createElement('div');
    linha.className = 'cofre-item';
    const nome = document.createElement('span');
    nome.textContent = item.rotulo;
    const estado = document.createElement('b');
    estado.className = item.configurada ? 'ok' : 'nok';
    estado.textContent = item.configurada
      ? `${item.fonte === 'cofre' ? 'cofre' : '.env'} · ${item.dica || '••••'}`
      : 'não configurada';
    const acoes = document.createElement('div');

    if (item.link) {
      const link = document.createElement('button');
      link.type = 'button';
      link.textContent = 'obter chave';
      link.title = 'Abrir a página oficial no navegador';
      link.onclick = async () => {
        try {
          const aberto = await window.ultron.abrirLink(item.link);
          if (!aberto) notaCofre('não consegui abrir o link oficial.', 'err');
        } catch (error) { notaCofre(`falha ao abrir o link (${error.message})`, 'err'); }
      };
      acoes.append(link);
    }
    if (item.testavel) {
      const testar = document.createElement('button');
      testar.type = 'button';
      testar.textContent = 'testar';
      testar.disabled = !item.configurada;
      testar.onclick = async () => {
        notaCofre('testando a chave com o provedor…');
        try {
          const r = await window.ultron.cofreTestar(item.nome);
          notaCofre(r.mensagem, r.ok ? 'ok' : 'err');
        } catch (error) { notaCofre(`falha no teste (${error.message})`, 'err'); }
      };
      acoes.append(testar);
    }
    if (item.fonte === 'cofre') {
      const remover = document.createElement('button');
      remover.type = 'button';
      remover.textContent = 'remover';
      remover.onclick = async () => {
        if (!window.confirm(`Remover a credencial ${item.rotulo} do cofre?\n\nSe houver chave no .env, ela volta a ser usada.`)) return;
        try {
          const novo = await window.ultron.cofreRemover(item.nome);
          pintarCofre(novo);
          notaCofre('credencial removida do cofre.', 'ok');
        } catch (error) { notaCofre(`não consegui remover (${error.message})`, 'err'); }
      };
      acoes.append(remover);
    }
    linha.append(nome, estado, acoes);
    lista.append(linha);
  }
  $('cofreProtecao').textContent = `proteção: ${status.protecao} · precedência: ${status.precedencia}`;
  $('cofreArquivo').textContent = status.arquivo || 'dados/cofre.json';
}

async function carregarCofre() {
  try {
    pintarCofre(await window.ultron.cofreStatus());
  } catch (error) {
    notaCofre(`não consegui ler o cofre (${error.message})`, 'err');
  }
}

async function salvarNoCofre() {
  const nome = $('cofreNome').value;
  const campo = $('cofreValor');
  const valor = campo.value.trim();
  if (!valor) { notaCofre('cole a chave antes de salvar.'); return; }
  notaCofre('salvando cifrado…');
  try {
    const status = await window.ultron.cofreGuardar(nome, valor);
    campo.value = '';                    // o valor não fica na tela
    pintarCofre(status);
    notaCofre('credencial guardada cifrada. Use "testar" para confirmar que o provedor aceita.', 'ok');
    carregarVoz();
  } catch (error) {
    notaCofre(`não consegui salvar (${error.message})`, 'err');
  }
}

/* ── memória: consultar, corrigir e apagar fatos ─────────────────────────── */
/* Nada é apagado sem confirmação: cada botão pede "sim" antes de agir. */
function fatoLinha(fato) {
  const item = document.createElement('div');
  item.className = 'fact';
  item.dataset.id = String(fato.id);
  const texto = document.createElement('p');
  texto.textContent = fato.texto;
  const acoes = document.createElement('div');
  acoes.className = 'fact-actions';

  const editar = document.createElement('button');
  editar.type = 'button';
  editar.textContent = 'editar';
  editar.title = 'Corrigir este fato';
  editar.onclick = async () => {
    const novo = window.prompt('Corrigir o fato:', fato.texto);
    if (novo === null) return;
    const limpo = novo.trim();
    if (!limpo || limpo === fato.texto) return;
    try {
      const r = await window.ultron.fatoCorrigir(fato.id, limpo);
      pintarFatos(r.fatos, 'fato corrigido.');
    } catch (error) {
      notaFatos(`não consegui corrigir (${error.message})`, 'err');
    }
  };

  const apagar = document.createElement('button');
  apagar.type = 'button';
  apagar.textContent = 'apagar';
  apagar.title = 'Apagar este fato';
  apagar.onclick = async () => {
    if (!window.confirm(`Apagar este fato?\n\n“${fato.texto}”`)) return;
    try {
      const r = await window.ultron.fatoApagar(fato.id);
      pintarFatos(r.fatos, 'fato apagado.');
    } catch (error) {
      notaFatos(`não consegui apagar (${error.message})`, 'err');
    }
  };

  acoes.append(editar, apagar);
  item.append(texto, acoes);
  return item;
}

function notaFatos(texto, classe = '') {
  const alvo = $('factsNote');
  alvo.textContent = texto;
  alvo.className = `micro nano ${classe}`;
}

function pintarFatos(fatos, aviso = '') {
  const lista = $('factsList');
  lista.replaceChildren();
  if (!fatos || !fatos.length) {
    const vazio = document.createElement('span');
    vazio.className = 'micro nano';
    vazio.textContent = 'nenhum fato guardado';
    lista.append(vazio);
  } else {
    for (const fato of fatos) lista.append(fatoLinha(fato));
  }
  if (aviso) notaFatos(`${aviso} (${fatos?.length ?? 0} guardados)`, 'ok');
}

async function carregarFatos() {
  try {
    const r = await window.ultron.fatosListar($('factsSearch').value.trim());
    pintarFatos(r.fatos, '');
    notaFatos(`${r.fatos.length} de até ${r.limite} fatos`);
  } catch (error) {
    notaFatos(`não consegui ler a memória (${error.message})`, 'err');
  }
}

function paginaLembretes(itens, aviso = '') {
  const lista = $('lembretesList');
  lista.replaceChildren();
  if (!itens || !itens.length) {
    const vazio = document.createElement('span');
    vazio.className = 'micro nano';
    vazio.textContent = 'nenhum lembrete pendente';
    lista.append(vazio);
  }
  for (const item of itens || []) {
    const linha = document.createElement('div');
    linha.className = 'fact';
    const texto = document.createElement('p');
    texto.textContent = `${item.hora_local} — ${item.texto}`;
    const acoes = document.createElement('div');
    acoes.className = 'fact-actions';
    const cancelar = document.createElement('button');
    cancelar.type = 'button';
    cancelar.textContent = 'cancelar';
    cancelar.title = 'Apagar este lembrete';
    cancelar.onclick = async () => {
      if (!window.confirm(`Cancelar o lembrete “${item.texto}”?`)) return;
      try {
        const r = await window.ultron.lembreteCancelar(item.numero, '');
        paginaLembretes(r.lembretes, r.mensagem);
      } catch (error) {
        $('lembretesNote').textContent = `não consegui cancelar (${error.message})`;
      }
    };
    acoes.append(cancelar);
    linha.append(texto, acoes);
    lista.append(linha);
  }
  if (aviso) $('lembretesNote').textContent = `${aviso} · ${(itens || []).length} pendente(s)`;
}

async function carregarLembretes() {
  try {
    const r = await window.ultron.lembretesListar();
    paginaLembretes(r.lembretes, '');
    $('lembretesNote').textContent = (r.lembretes || []).length
      ? `${r.lembretes.length} pendente(s) · ${r.aviso}`
      : r.aviso;
  } catch {
    $('lembretesNote').textContent = 'não consegui ler os lembretes';
  }
}

/* Fluxos: o núcleo executa etapa por etapa e devolve o resultado de cada uma. */
async function rodarFluxo(id) {
  const nota = $('fluxoNote');
  nota.textContent = 'executando…';
  nota.className = 'micro nano';
  try {
    await send(`Execute o fluxo ${id}`);
    nota.textContent = `fluxo ${id} enviado ao núcleo — o resultado por etapa aparece na câmara e na conversa.`;
    nota.className = 'micro nano ok';
  } catch (error) {
    nota.textContent = `não consegui iniciar o fluxo (${error.message})`;
    nota.className = 'micro nano err';
  }
}

/* ── atualização pelo GitHub ─────────────────────────────────────────────── */
/* Fluxo do botão "atualizar ULTRON":
     1. verificar se há versão nova no GitHub;
     2. baixar, conferir o SHA-256 e aplicar;
     3. se sobrar arquivo em uso, pedir o reinício (ou reiniciar na hora, se o
        usuário confirmar). O progresso aparece na própria barra.               */
const updateUi = { job: null, timer: null, version: '1.9.8', busy: false };

function updateLinha(texto, classe = '') {
  const alvo = $('updateState');
  alvo.textContent = texto;
  alvo.className = classe;
}

function progresso(percent) {
  const caixa = $('updateProgress');
  const barra = $('updateProgressBar');
  const valor = Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : null;
  caixa.hidden = valor === null;
  barra.style.width = `${valor ?? 0}%`;
}

function botaoAtualizar(estado) {
  const botao = $('updateAction');
  botao.disabled = estado === 'ocupado';
  botao.textContent = estado === 'ocupado' ? 'atualizando…' : 'atualizar ULTRON';
}

function mostrarVersao(info) {
  if (!info) return;
  if (info.current_version) {
    updateUi.version = info.current_version;
    $('updateVersion').textContent = info.current_version;
    $('dockVersion').textContent = info.current_version;
  }
  const check = info.last_check;
  if (check?.status === 'erro') updateLinha(check.message || 'não foi possível verificar', 'err');
  else if (check?.status === 'sem_release') updateLinha('sem release no GitHub');
  else if (check?.update_available) updateLinha(`versão ${check.latest_version} disponível`, 'warn');
  else if (check) updateLinha('atualizado ✓', 'ok');
  if (info.needs_restart) {
    $('updateRestart').hidden = false;
    updateLinha('reinicie para concluir', 'warn');
  }
}

async function acompanharAtualizacao() {
  clearInterval(updateUi.timer);
  updateUi.timer = setInterval(async () => {
    try {
      const info = await window.ultron.updateInfo();
      const job = info?.job;
      if (!job) return;
      updateUi.job = job;
      progresso(job.percent);
      if (job.status === 'baixando' || job.status === 'aplicando') {
        updateLinha(job.message || 'baixando…', 'warn');
      } else if (job.status === 'pronto') {
        clearInterval(updateUi.timer);
        progresso(100);
        botaoAtualizar('livre');
        if (job.needs_restart) {
          updateLinha(job.message || 'reinicie para concluir', 'warn');
          $('updateRestart').hidden = false;
          $('updateRollback').hidden = false;
          pedirReinicio(job);
        } else {
          updateLinha(job.message || 'atualização aplicada ✓', 'ok');
        }
      } else if (job.status === 'erro') {
        clearInterval(updateUi.timer);
        botaoAtualizar('livre');
        progresso(null);
        updateLinha(job.message || 'falhou', 'err');
      } else if (job.status === 'atualizado') {
        clearInterval(updateUi.timer);
        botaoAtualizar('livre');
        updateLinha(job.message || 'já está atualizado', 'ok');
      }
    } catch { /* núcleo ocupado: tenta de novo no próximo tique */ }
  }, 900);
}

/* Passo 3: perguntar antes de reiniciar (com opção de depois). */
function pedirReinicio(job) {
  const versao = job?.version ? ` ${job.version}` : '';
  if (window.confirm(`Atualização${versao} aplicada.\n\nReiniciar o ULTRON agora para concluir?`)) {
    reiniciarAgora();
  } else {
    updateLinha('reinicie quando quiser para concluir', 'warn');
  }
}

async function reiniciarAgora() {
  $('updateRestart').disabled = true;
  updateLinha('aplicando e reiniciando…', 'warn');
  try { await window.ultron.updateLaunch(); }
  catch (error) {
    updateLinha(`não consegui reiniciar: ${error.message}`, 'err');
    $('updateRestart').disabled = false;
  }
}

/* Passo 1 + 2: um clique faz tudo. */
async function atualizarUltron() {
  if (updateUi.busy) return;
  updateUi.busy = true;
  botaoAtualizar('ocupado');
  progresso(4);
  updateLinha('verificando no GitHub…');
  try {
    const info = await window.ultron.updateCheck();
    if (info.status === 'erro') { updateLinha(info.message || 'falha ao consultar', 'err'); return; }
    if (info.status === 'sem_release') { updateLinha('ainda não há release publicado', 'warn'); progresso(null); return; }
    if (!info.update_available) {
      progresso(100);
      updateLinha(`você já está na versão mais recente (${info.current_version}) ✓`, 'ok');
      return;
    }
    updateLinha(`versão ${info.latest_version} encontrada · baixando…`, 'warn');
    progresso(12);
    await window.ultron.updateApply(true);
    acompanharAtualizacao();
  } catch (error) {
    updateLinha(`falha na atualização (${error.message})`, 'err');
    progresso(null);
  } finally {
    updateUi.busy = false;
    if (!updateUi.timer) botaoAtualizar('livre');
  }
}

async function desfazerAtualizacao() {
  try {
    await window.ultron.updateRollback();
    updateLinha('backup restaurado ✓', 'ok');
    toast('Versão anterior restaurada.');
  } catch {
    updateLinha('não há backup para restaurar', 'err');
  }
}

/* ── barras recolhíveis (bate-papo e diário) ──────────────────────────────── */
/* Nascem abertas nos docks, lembram a escolha e recolhem para 46px. O diário
   começa recolhido abaixo de 1280px; a preferência salva vence o padrão. */
const RAILS = {
  chat: { chave: 'ultron-chat-aberto', attr: 'data-chat', botoes: ['collapseChat'],
    alternador: 'toggleChat', rotulo: 'bate-papo', tecla: 'Ctrl+1', painel: 'drawerChat' },
  sys: { chave: 'ultron-sys-aberto', attr: 'data-sys', botoes: ['collapseSystem'],
    alternador: 'toggleSystem', rotulo: 'diário', tecla: 'Ctrl+2', painel: 'sidePanel' },
};

function aplicarRail(nome, aberto, { persistir = true } = {}) {
  const rail = RAILS[nome];
  document.documentElement.setAttribute(rail.attr, aberto ? 'on' : 'off');
  const titulo = `${aberto ? 'Recolher' : 'Abrir'} ${rail.rotulo} (${rail.tecla})`;
  for (const id of rail.botoes) {
    const botao = $(id);
    botao.setAttribute('aria-pressed', String(aberto));
    botao.setAttribute('aria-expanded', String(aberto));
    botao.title = titulo;
  }
  const alternador = $(rail.alternador);
  alternador.setAttribute('aria-expanded', String(aberto));
  alternador.title = titulo;
  const painel = $(rail.painel);
  painel.setAttribute('aria-hidden', String(!aberto));
  // só a escolha do usuário é lembrada; o padrão por largura não vira preferência
  if (persistir) { try { localStorage.setItem(rail.chave, aberto ? '1' : '0'); } catch {} }
  if (nome === 'sys' && aberto) carregarDiario();
  return aberto;
}

function railAberto(nome) {
  return document.documentElement.getAttribute(RAILS[nome].attr) !== 'off';
}

function alternarRail(nome) {
  return aplicarRail(nome, !railAberto(nome));
}

function restaurarRails() {
  const padrao = { chat: '1', sys: window.innerWidth >= 1280 ? '1' : '0' };
  for (const nome of Object.keys(RAILS)) {
    let salvo = null;
    try { salvo = localStorage.getItem(RAILS[nome].chave); } catch {}
    aplicarRail(nome, (salvo ?? padrao[nome]) !== '0', { persistir: false });
  }
}


/* Mesma família do bate-papo: entra pela direita, encostada na câmara, sem
   cobrir o conteúdo. Fecha pela seta "fechar", pelo Esc ou clicando fora. */
let gavetaAberta = false;
let gavetaSaindo = 0;

function posicionarBarra() {
  // a barra nasce abaixo da ponte e acompanha a altura real da câmara
  const topo = document.querySelector('.bridge')?.getBoundingClientRect().bottom ?? 64;
  document.documentElement.style.setProperty('--stage-top', `${Math.round(topo + 8)}px`);
}

function drawer(open, { focar = true } = {}) {
  const painel = $('drawer');
  const fundo = $('drawerBackdrop');
  gavetaAberta = Boolean(open);
  document.documentElement.dataset.drawer = open ? 'on' : 'off';
  painel.setAttribute('aria-hidden', String(!open));
  $('openSettings').setAttribute('aria-expanded', String(Boolean(open)));
  $('openSettings').setAttribute('aria-pressed', String(Boolean(open)));

  // reabrir cancela uma saída em curso: o painel volta de onde está
  clearTimeout(gavetaSaindo);
  gavetaSaindo = 0;
  painel.classList.remove('closing');

  if (open) {
    painel.hidden = false;
    fundo.hidden = false;
    // um quadro no estado inicial antes de aplicar .open: é isso que faz a
    // transição existir (sem depender de @starting-style)
    void painel.offsetWidth;
    painel.classList.add('open');
    // abrir ajustes começa pelo topo: o painel é longo e a primeira coisa
    // que se procura é o tema, não o fim da lista
    const corpo = painel.querySelector('.drawer-body');
    if (corpo) corpo.scrollTop = 0;
    posicionarBarra();
    refreshMicrophones();
    carregarVoz();
    carregarPersonalidade();
    carregarFatos();
    carregarLembretes();
    carregarCofre();
    // ao abrir sozinha no carregamento não há interação: focar aqui desenharia
    // um anel de foco que ninguém pediu
    if (focar) $('closeDrawer')?.focus();
    return;
  }

  const esconder = () => {
    painel.hidden = true;
    painel.classList.remove('open', 'closing');
    fundo.hidden = true;
  };
  const semMovimento = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (painel.hidden || semMovimento) {
    esconder();
  } else {
    // sai pelo mesmo lado que entrou, mais rápido do que veio
    painel.classList.remove('open');
    painel.classList.add('closing');
    fundo.hidden = true;
    gavetaSaindo = setTimeout(esconder, 170);
  }
  $('openSettings')?.focus();
}

function fecharGaveta() {
  if (gavetaAberta || !$('drawer').hidden) drawer(false);
}

/* ── ligação dos controles ───────────────────────────────────────────────── */
applyTheme((() => { try { return localStorage.getItem('ultron-theme') || 'ultron'; } catch { return 'ultron'; } })());
aplicarModoNucleo(modoNucleo);
$('coreMode').onclick = () => aplicarModoNucleo(modoNucleo === '3d' ? '2d' : '3d', { avisar: true });
document.querySelectorAll('[data-core]').forEach(node => node.onclick = () => aplicarModoNucleo(node.dataset.core, { avisar: true }));
document.querySelectorAll('[data-theme-pill]').forEach(node => node.onclick = () => applyTheme(node.dataset.themePill));
document.querySelectorAll('#themeSwatches .swatch').forEach(node => node.onclick = () => applyTheme(node.dataset.theme));
document.querySelectorAll('[data-command]').forEach(button => button.onclick = () => send(button.dataset.command));

$('consoleForm').addEventListener('submit', event => {
  event.preventDefault();
  const input = $('commandInput');
  const text = input.value;
  input.value = '';
  send(text);
});
$('commandInput').addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.target.value = ''; event.target.blur(); }
});
$('micButton').onclick = toggleMicrophone;
$('voiceStart').onclick = toggleMicrophone;
$('refreshMicrophones').onclick = () => refreshMicrophones();
$('saveMicrophone').onclick = saveMicrophone;
$('testConnection').onclick = () => refreshStatus(true);
document.querySelectorAll('[data-fluxo]').forEach(botao => botao.onclick = () => rodarFluxo(botao.dataset.fluxo));
$('cofreSalvar').onclick = salvarNoCofre;
$('cofreValor').addEventListener('keydown', event => { if (event.key === 'Enter') salvarNoCofre(); });
$('factsRefresh').onclick = carregarFatos;
$('factsSearch').addEventListener('keydown', event => { if (event.key === 'Enter') carregarFatos(); });
$('testMic').onclick = testarMicrofone;
$('testVoice').onclick = testarVoz;
$('saveVoice').onclick = salvarVoz;
document.querySelectorAll('[data-profile]').forEach(node => node.onclick = () => {
  pintarPerfil(node.dataset.profile);
  salvarPersonalidade();
});
$('savePersonality').onclick = () => salvarPersonalidade({ usuario: true, saudacao: true });
$('greetingToggle').onclick = alternarSaudacao;
$('tabVoice').onclick = () => mostrarAba('voz');
$('tabStyle').onclick = () => mostrarAba('jeito');
$('tabMic').onclick = () => mostrarAba('microfone');
$('tabAbout').onclick = () => mostrarAba('sobre');
$('updateAction').onclick = atualizarUltron;
$('previewPersonality').onclick = previaPersonalidade;
$('resetPersonality').onclick = restaurarPersonalidade;
$('updateRestart').onclick = reiniciarAgora;
$('updateRollback').onclick = desfazerAtualizacao;
$('scrollLatest').onclick = () => { const lista = $('commsList'); lista.scrollTop = lista.scrollHeight; };
$('clearHistory').onclick = async () => {
  let confirmado = true;
  try { await transport.clearConversation(); } catch { confirmado = false; }
  state.history = [];
  renderTurnos([]);
  if ($('memoryList')) $('memoryList').replaceChildren();
  if ($('recentList')) $('recentList').replaceChildren();
  toast(confirmado ? 'Sessão limpa.' : 'Tela limpa. O núcleo não confirmou a limpeza.');
};
$('toggleChat')?.addEventListener('click', () => alternarRail('chat'));
$('toggleSystem')?.addEventListener('click', () => alternarRail('sys'));
$('sessionButton').addEventListener('click', async () => {
  if (state.status.session_desbloqueada === true) {
    try { await transport.lock(); } catch { /* o polling reconcilia */ }
    state.status.session_desbloqueada = false;
    limparDiario();
  }
  desbloqueio.abrir();
});
function sessaoBloqueada() {
  // bloqueio vindo do Windows (tela bloqueada/suspensão) ou por inatividade:
  // o diário não fica na tela
  state.status.session_desbloqueada = false;
  limparDiario();
  desbloqueio.abrir();
}
transport.onSessionLocked(sessaoBloqueada);
$('collapseChat').onclick = () => alternarRail('chat');
$('collapseSystem').onclick = () => alternarRail('sys');
$('undoAction').onclick = async () => {
  $('undoAction').disabled = true;          // duplo clique não envia o comando duas vezes
  await send('Desfazer a última operação');
  pintarDiario();                           // reabilita conforme a lista real
};
$('openSettings').onclick = () => drawer(!gavetaAberta);
/* fechar: seta, clique fora (o backdrop cobre o resto da tela) e Esc */
$('closeDrawer').addEventListener('click', event => { event.preventDefault(); fecharGaveta(); });
$('drawerBackdrop').addEventListener('pointerdown', event => { event.preventDefault(); fecharGaveta(); });
/* botões com data-fechar (usados em blocos) também fecham */
document.querySelectorAll('[data-fechar]').forEach(botao => botao.addEventListener('click', fecharGaveta));
$('toggleHud').onclick = () => window.ultron.toggleHud();
$('palcoClose').onclick = () => fecharPalco();
$('palcoSound').onclick = () => palcoSom();
$('palcoExternal').onclick = async () => {
  const botao = $('palcoExternal');
  const id = botao.dataset.id || '';
  if (id) {
    try {
      const aberto = await transport.palcoAbrir(id);
      if (!aberto) toast('Não consegui abrir este PDF.');
    } catch {
      toast('Não foi possível abrir o visualizador de PDF.');
    }
    return;
  }
  const url = botao.dataset.url || '';
  if (!url) return;
  try {
    const aberto = await window.ultron.abrirExterno(url);
    if (!aberto) toast('Não abri esse endereço: ele não passou na verificação de segurança.');
  } catch {
    toast('Não foi possível abrir o navegador do sistema.');
  }
};
window.ultron.onHudVisibility(visible => {
  $('toggleHud').textContent = visible ? 'fechar flutuante' : 'janela flutuante';
  $('toggleHud').title = visible ? 'Fechar painel flutuante' : 'Abrir painel flutuante';
});
window.ultron.onHudAction(async request => {
  if (!request || !Number.isSafeInteger(request.requestId) || !Object.hasOwn(hudActions, request.actionId)) return;
  $('commandInput').focus();
  window.ultron.hudActionResult(request.requestId, await send(hudActions[request.actionId]));
});
$('emergencyStopButton').onclick = async () => {
  if (!window.confirm('Acionar a parada de emergência do ULTRON?')) return;
  pararTudo();
};

/* parada de emergência sem confirmação: usada pelo botão e pelo Esc duplo */
async function pararTudo() {
  try { await transport.emergencyStop(); toast('Parada de emergência enviada ao núcleo.'); }
  catch (error) { toast(`A parada de emergência falhou: ${error.message}`); }
}

/* atalhos: Ctrl+1 bate-papo · Ctrl+2 diário · Ctrl+, ajustes · Ctrl+K comando · Esc · Esc Esc para tudo */
let ultimoEsc = 0;
function atalhos(event) {
  if (event.ctrlKey && event.key === ',') { event.preventDefault(); event.stopPropagation(); drawer(!gavetaAberta); return; }
  if (event.ctrlKey && (event.key === '1' || event.key === '!')) { event.preventDefault(); event.stopPropagation(); alternarRail('chat'); return; }
  if (event.ctrlKey && (event.key === '2' || event.key === '@')) { event.preventDefault(); event.stopPropagation(); alternarRail('sys'); return; }
  if (event.ctrlKey && event.key.toLowerCase() === 'k') { event.preventDefault(); $('commandInput').focus(); return; }
  if (event.key === 'Escape') {
    const agora = Date.now();
    if (agora - ultimoEsc < 1200) {
      ultimoEsc = 0;
      event.preventDefault();
      event.stopPropagation();
      pararTudo();
      return;
    }
    ultimoEsc = agora;
    const alvo = event.target;
    const digitando = Boolean(alvo && typeof alvo.tagName === 'string' &&
      /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName));
    if (!$('drawer').hidden) { event.preventDefault(); event.stopPropagation(); fecharGaveta(); return; }
    if (state.palco && !digitando) { event.preventDefault(); event.stopPropagation(); fecharPalco(); }
  }
}
/* captura: funciona mesmo quando o foco está num select/botão dentro da barra */
window.addEventListener('keydown', atalhos, { capture: true });
document.addEventListener('keydown', atalhos);

/* ── ciclo de vida ───────────────────────────────────────────────────────── */
restaurarRails();
updateClock();
setInterval(updateClock, 1000);
window.addEventListener('resize', () => { if (gavetaAberta) posicionarBarra(); });
document.addEventListener('visibilitychange', () => orbLoop(!document.hidden));
window.addEventListener('beforeunload', () => { orb.parar(); campo.parar(); desbloqueio.parar(); transport.disconnect(); });

(async () => {
  // AO ABRIR: a câmara aparece inteira; ajustes só quando forem pedidos.
  // A conexão com o núcleo chega depois e não deve segurar a interface vazia.
  desbloqueio.abrir();
  pintarDiario();
  try {
    await transport.connect();
    connection(true);
    carregarPersonalidade();
    carregarHistorico();
  } catch (est) {
    if (est && typeof est.message === 'string') {
      $('updateLine').textContent = 'Aguardando o núcleo local... (abra pelo atalho ULTRON Desktop)';
    }
  }
  // catch protegida pelo bloco externo; não quebra a inicialização
  orbLoop(true);
  carregarConversa();                       // falas que aconteceram antes do painel abrir
  window.ultron?.updateInfo?.().then(info => {
    mostrarVersao(info);
    if (info?.needs_restart) $('updateRestart').hidden = false;
  }).catch(() => {});
  setInterval(carregarConversa, 20000);     // reconcilia se algum evento se perder
  setInterval(() => refreshStatus(), 5000);
})();
