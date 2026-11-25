import { criarOrbe } from './src/orb.js';

/* Segundo plano do U.L.T.R.O.N.:
   - Estilo "island": Dynamic Island (Notch configurável no topo ou laterais)
   - Estilo "orb": Núcleo Solto (Orbe 3D 96px arrastável + projeção holográfica + mini palco) */
const $ = id => document.getElementById(id);
const TITULO_POR_TEMA = {
  ultron: 'U.L.T.R.O.N.',
  jarvis: 'JARVIS',
  amber: 'VISÃO',
  emerald: 'EDITH',
};

const island = $('island');
const freeCore = $('freeCore');
const coreAnchor = $('coreAnchor');
const coreOrbBtn = $('coreOrbBtn');
const waves = Array.from($('islandWaves').querySelectorAll('i'));

const islandOrb = criarOrbe($('hudOrb'), { modo: '2d' });
const freeOrb = criarOrbe($('freeOrbCanvas'), { modo: '3d' });

let activeStyle = 'island';
let expanded = false;
let pinned = false;
let islandMode = 'auto';
let islandPos = 'top-center';
let collapseTimer = null;
let shrinkWindowTimer = null;
let autoActivityTimer = null;
let quitArmTimer = null;
let animSeq = 0;
let lastResponseSeen = '';
let lastPalcoKey = '';
let lastTeleportSeq = 0;
let lastTeleportOutSeq = 0;
let teleportAnimTimer = null;
let wavePhase = 0;
let waveEnergy = 0.1;

function sincronizarMotoresOrbe() {
  if (document.hidden) {
    islandOrb.parar();
    freeOrb.parar();
    return;
  }
  if (activeStyle === 'orb') {
    islandOrb.parar();
    freeOrb.iniciar();
  } else {
    freeOrb.parar();
    islandOrb.iniciar();
  }
}

sincronizarMotoresOrbe();

function aplicarLayoutOrbe(info) {
  if (!info || typeof info !== 'object') return;
  if (info.side === 'left' || info.side === 'right') {
    freeCore.dataset.side = info.side;
  }
  if (Number.isFinite(info.orbOffsetY)) {
    coreAnchor.style.setProperty('--orb-y', `${Math.round(info.orbOffsetY)}px`);
  }
}

function inputFocado() {
  return document.activeElement === $('islandInput') || document.activeElement === $('coreInput');
}

function mouseSobreAtivo() {
  return activeStyle === 'orb' ? freeCore.matches(':hover') : island.matches(':hover');
}

async function aplicarExpansao(abrir) {
  const proximo = Boolean(abrir);
  if (proximo === expanded) return;
  const seq = ++animSeq;
  clearTimeout(shrinkWindowTimer);
  shrinkWindowTimer = null;

  if (proximo) {
    expanded = true;
    const layout = await window.ultron?.setIslandExpanded?.(true).catch(() => null);
    if (seq !== animSeq) return;
    if (activeStyle === 'orb') aplicarLayoutOrbe(layout);
    requestAnimationFrame(() => {
      if (seq !== animSeq) return;
      island.dataset.expanded = 'true';
      freeCore.dataset.expanded = 'true';
    });
  } else {
    expanded = false;
    pinned = false;
    desarmarQuit();
    island.dataset.expanded = 'false';
    freeCore.dataset.expanded = 'false';
    shrinkWindowTimer = setTimeout(async () => {
      if (seq !== animSeq || expanded) return;
      const layout = await window.ultron?.setIslandExpanded?.(false).catch(() => null);
      if (activeStyle === 'orb') aplicarLayoutOrbe(layout);
    }, 310);
  }
}

function agendarRecolher(ms = 280) {
  clearTimeout(collapseTimer);
  collapseTimer = setTimeout(() => {
    if (pinned || inputFocado()) return;
    aplicarExpansao(false);
  }, ms);
}

function expandirPorAtividade(ms = 5200) {
  if (islandMode !== 'auto' && islandMode !== 'activity') return;
  clearTimeout(autoActivityTimer);
  aplicarExpansao(true);
  autoActivityTimer = setTimeout(() => {
    if (!pinned && !inputFocado() && !mouseSobreAtivo()) {
      aplicarExpansao(false);
    }
  }, ms);
}

function desarmarQuit() {
  clearTimeout(quitArmTimer);
  quitArmTimer = null;
  for (const id of ['hudQuit', 'coreQuit']) {
    const btn = $(id);
    if (btn) {
      btn.dataset.armed = 'false';
      btn.title = 'Encerrar ULTRON';
    }
  }
}

function acionarQuit(btn) {
  if (btn.dataset.armed === 'true') {
    window.ultron?.quitApp?.();
    return;
  }
  btn.dataset.armed = 'true';
  btn.title = 'Clique novamente para encerrar o ULTRON';
  $('ctxTag').textContent = 'SAIR';
  $('ctxText').textContent = 'Clique de novo no botão desligar para encerrar';
  $('coreResponse').textContent = 'Clique novamente no botão desligar para encerrar o ULTRON.';
  clearTimeout(quitArmTimer);
  quitArmTimer = setTimeout(desarmarQuit, 3500);
}

/* ── Interações Dynamic Island ───────────────────────────────────────────── */
island.addEventListener('mouseenter', () => {
  clearTimeout(collapseTimer);
  if (islandMode === 'auto' || islandMode === 'hover') aplicarExpansao(true);
});
island.addEventListener('mouseleave', () => {
  if (pinned) return;
  if (islandMode === 'auto' || islandMode === 'hover') agendarRecolher(280);
});
$('islandToggleArea').addEventListener('click', () => {
  pinned = !expanded;
  aplicarExpansao(!expanded);
});
$('islandToggleArea').addEventListener('dblclick', () => window.ultron?.returnToMain?.());
$('islandToggleArea').addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    $('islandToggleArea').click();
  }
});

/* ── Interações Núcleo Solto (arrastar + clique + hover) ─────────────────── */
let dragState = null;

coreOrbBtn.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  clearTimeout(collapseTimer);
  dragState = {
    pointerId: event.pointerId,
    startX: event.screenX,
    startY: event.screenY,
    lastX: event.screenX,
    lastY: event.screenY,
    moved: false,
  };
  coreOrbBtn.setPointerCapture(event.pointerId);
});

coreOrbBtn.addEventListener('pointermove', event => {
  if (!dragState || event.pointerId !== dragState.pointerId) return;
  const dx = event.screenX - dragState.lastX;
  const dy = event.screenY - dragState.lastY;
  const total = Math.hypot(event.screenX - dragState.startX, event.screenY - dragState.startY);
  if (!dragState.moved && total > 5) {
    dragState.moved = true;
    coreOrbBtn.classList.add('dragging');
  }
  if (dragState.moved && (dx !== 0 || dy !== 0)) {
    dragState.lastX = event.screenX;
    dragState.lastY = event.screenY;
    window.ultron?.moveOrb?.(dx, dy, false).then(aplicarLayoutOrbe).catch(() => {});
  }
});

function finalizarArraste(event) {
  if (!dragState || event.pointerId !== dragState.pointerId) return;
  const foiArraste = dragState.moved;
  dragState = null;
  coreOrbBtn.classList.remove('dragging');
  try { coreOrbBtn.releasePointerCapture(event.pointerId); } catch {}
  if (foiArraste) {
    window.ultron?.moveOrb?.(0, 0, true).then(aplicarLayoutOrbe).catch(() => {});
    return;
  }
  /* Clique curto alterna o cartão holográfico ao lado do núcleo */
  pinned = !expanded;
  aplicarExpansao(!expanded);
}

coreOrbBtn.addEventListener('pointerup', finalizarArraste);
coreOrbBtn.addEventListener('pointercancel', finalizarArraste);
coreOrbBtn.addEventListener('dblclick', () => window.ultron?.returnToMain?.());
coreOrbBtn.addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    pinned = !expanded;
    aplicarExpansao(!expanded);
  }
});

freeCore.addEventListener('mouseenter', () => {
  clearTimeout(collapseTimer);
  if (!dragState && (islandMode === 'auto' || islandMode === 'hover')) aplicarExpansao(true);
});
freeCore.addEventListener('mouseleave', () => {
  if (pinned || dragState) return;
  if (islandMode === 'auto' || islandMode === 'hover') agendarRecolher(320);
});

/* Botões comuns */
$('hudReturn').onclick = () => window.ultron?.returnToMain?.();
$('coreReturn').onclick = () => window.ultron?.returnToMain?.();
$('corePalcoOpen').onclick = () => window.ultron?.returnToMain?.();
$('hudQuit').onclick = () => acionarQuit($('hudQuit'));
$('coreQuit').onclick = () => acionarQuit($('coreQuit'));

/* Envio rápido de comandos (ambos os estilos) */
function vincularForm(formId, inputId, btnId) {
  const form = $(formId);
  const input = $(inputId);
  const sendBtn = $(btnId);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.disabled = true;
    sendBtn.disabled = true;
    try {
      const ok = await window.ultron?.sendHudCommand?.(text);
      if (ok) input.value = '';
    } finally {
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    }
  });
  input.addEventListener('blur', () => {
    if (!pinned && (islandMode === 'auto' || islandMode === 'hover') && !mouseSobreAtivo()) {
      agendarRecolher(350);
    }
  });
}
vincularForm('islandForm', 'islandInput', 'islandSend');
vincularForm('coreForm', 'coreInput', 'coreSend');

/* Ações rápidas whitelisted */
document.querySelectorAll('[data-hud-action]').forEach(botao => {
  botao.onclick = async event => {
    event.stopPropagation();
    const alvo = botao.dataset.hudAction;
    botao.disabled = true;
    try { await window.ultron?.runHudAction?.(alvo); }
    finally { setTimeout(() => { botao.disabled = false; }, 500); }
  };
});

/* Animação contínua leve das ondas na Dynamic Island */
const waveTimer = setInterval(() => {
  if (document.hidden || activeStyle !== 'island') return;
  wavePhase += 0.35;
  const base = Math.max(0.08, Math.min(1, waveEnergy));
  waves.forEach((bar, i) => {
    const osc = 0.55 + 0.45 * Math.sin(wavePhase + i * 1.15);
    bar.style.height = `${Math.round(3 + base * 12 * osc)}px`;
  });
}, 90);

/* Atualização visual a partir do snapshot real */
function pintar(snapshot) {
  if (!snapshot) return;
  const theme = snapshot.theme || 'ultron';
  document.documentElement.dataset.theme = theme;

  const nextStyle = snapshot.islandStyle === 'orb' ? 'orb' : 'island';
  if (nextStyle !== activeStyle) {
    activeStyle = nextStyle;
    document.body.dataset.style = activeStyle;
    sincronizarMotoresOrbe();
  } else {
    document.body.dataset.style = activeStyle;
  }

  islandMode = snapshot.islandMode || 'auto';
  island.dataset.mode = islandMode;
  islandPos = snapshot.islandPos || 'top-center';
  document.body.dataset.pos = islandPos;

  if (activeStyle === 'orb') {
    aplicarLayoutOrbe({ side: snapshot.orbSide, orbOffsetY: snapshot.orbOffsetY });
    if (snapshot.orbTeleportPhase === 'idle') {
      coreOrbBtn.classList.remove('teleport-out');
    }
    if (Number.isFinite(snapshot.orbTeleportOutSeq) && snapshot.orbTeleportOutSeq !== lastTeleportOutSeq) {
      if (lastTeleportOutSeq !== 0 || snapshot.orbTeleportPhase === 'out') {
        clearTimeout(teleportAnimTimer);
        coreOrbBtn.classList.remove('teleport-in');
        coreOrbBtn.classList.add('teleport-out');
      }
      lastTeleportOutSeq = snapshot.orbTeleportOutSeq;
    }
    if (Number.isFinite(snapshot.orbTeleportSeq) && snapshot.orbTeleportSeq !== lastTeleportSeq) {
      if (lastTeleportSeq !== 0 || snapshot.orbTeleportPhase === 'in') {
        clearTimeout(teleportAnimTimer);
        coreOrbBtn.classList.remove('teleport-out', 'teleport-in');
        void coreOrbBtn.offsetWidth;
        coreOrbBtn.classList.add('teleport-in');
        teleportAnimTimer = setTimeout(() => coreOrbBtn.classList.remove('teleport-in'), 420);
      }
      lastTeleportSeq = snapshot.orbTeleportSeq;
    }
  }

  const titulo = TITULO_POR_TEMA[theme] || 'U.L.T.R.O.N.';
  const wake = snapshot.wake || 'Ultron';
  $('hudTitle').textContent = titulo;
  $('coreTitle').textContent = titulo;
  $('islandInput').placeholder = `Comando rápido para ${wake}...`;
  $('coreInput').placeholder = `Pergunte ao ${wake}...`;

  const online = snapshot.core === 'Online' && snapshot.api === 'Conectada';
  const paused = snapshot.paused === true;
  const speaking = snapshot.speaking === true;
  const capturing = snapshot.capturing === true;
  const processing = snapshot.processing === true;

  const estado = !online ? 'offline'
    : paused ? 'paused'
    : speaking ? 'speaking'
    : capturing ? 'capturing'
    : 'idle';
  island.dataset.state = estado;
  freeCore.dataset.state = estado;

  const rotuloEstado = {
    offline: 'offline',
    paused: 'pausado',
    speaking: 'falando',
    capturing: 'ouvindo',
    idle: 'pronto',
  }[estado];
  $('hudStateBadge').textContent = rotuloEstado;
  $('coreStateBadge').textContent = rotuloEstado;
  $('hudDot').className = `ctx-dot ${online ? 'online' : snapshot.core ? 'warn' : 'error'}`;

  const cpuTxt = snapshot.cpu !== null && snapshot.cpu !== undefined ? `CPU ${snapshot.cpu}%` : 'CPU --';
  const ramTxt = snapshot.ram !== null && snapshot.ram !== undefined ? `RAM ${snapshot.ram}%` : 'RAM --';
  $('hudCpu').textContent = cpuTxt;
  $('hudRam').textContent = ramTxt;
  $('coreCpu').textContent = cpuTxt;
  $('coreRam').textContent = ramTxt;

  /* Microfone (pílula + fab + docks) */
  $('islandMicQuick').setAttribute('aria-pressed', String(paused));
  $('islandMicQuick').title = paused ? 'Retomar microfone' : 'Mutar microfone';
  $('coreMicFab').setAttribute('aria-pressed', String(paused));
  $('coreMicFab').title = paused ? 'Retomar microfone' : 'Mutar microfone';
  for (const id of ['actMic', 'coreActMic']) {
    $(id).dataset.active = String(paused);
    $(id).textContent = paused ? 'Mudo' : 'Mic';
  }

  /* Contexto Dynamic Island */
  if ($('hudQuit').dataset.armed !== 'true') {
    if (speaking) {
      $('ctxTag').textContent = 'VOZ';
      $('ctxText').textContent = `${titulo} falando agora...`;
    } else if (processing) {
      $('ctxTag').textContent = 'ATIVO';
      $('ctxText').textContent = 'Processando comando...';
    } else if (snapshot.palcoTitulo) {
      $('ctxTag').textContent = (snapshot.palcoTipo || 'PALCO').toUpperCase().slice(0, 8);
      $('ctxText').textContent = snapshot.palcoTitulo;
    } else if (paused) {
      $('ctxTag').textContent = 'PAUSADO';
      $('ctxText').textContent = 'Microfone silenciado · clique em Mic para retomar';
    } else {
      $('ctxTag').textContent = 'PRONTO';
      $('ctxText').textContent = `Diga "Ei, ${wake}" · ouvindo em segundo plano`;
    }
  }

  /* Mini Palco holográfico no Núcleo Solto */
  const temPalco = Boolean(snapshot.palcoTitulo);
  $('corePalco').hidden = !temPalco;
  if (temPalco) {
    $('corePalcoTag').textContent = (snapshot.palcoTipo || 'PALCO').toUpperCase().slice(0, 9);
    $('corePalcoTitle').textContent = snapshot.palcoTitulo;
    $('corePalcoSummary').textContent = snapshot.palcoResumo || 'Conteúdo pronto no palco principal.';
  }

  const resp = snapshot.response && snapshot.response !== 'Indisponível'
    ? snapshot.response
    : `Pronto ao seu lado. Diga "Ei, ${wake}".`;
  $('hudResponse').textContent = resp;
  if ($('coreQuit').dataset.armed !== 'true') {
    $('coreResponse').textContent = resp;
  }

  /* Auto-expansão em atividade real (nova resposta, fala ou novo palco) */
  const palcoKey = `${snapshot.palcoTipo || ''}|${snapshot.palcoTitulo || ''}`;
  if ((lastResponseSeen && resp !== lastResponseSeen) || (temPalco && palcoKey !== lastPalcoKey)) {
    expandirPorAtividade(5800);
  } else if (speaking || processing) {
    expandirPorAtividade(4500);
  }
  lastResponseSeen = resp;
  lastPalcoKey = palcoKey;

  /* Energia dos orbes */
  const micNorm = Math.min(1, Math.max(0, (Number(snapshot.micLevel) || 0) / 100));
  waveEnergy = paused || !online ? 0.05 : speaking ? 0.85 : capturing ? Math.max(0.35, micNorm) : 0.14;
  const orbEstado = {
    energia: speaking ? 0.82 : capturing ? Math.max(0.35, micNorm) : 0.16,
    brilho: online ? 0.94 : 0.35,
  };
  islandOrb.definir(orbEstado);
  freeOrb.definir(orbEstado);
}

const pararSnapshot = window.ultron?.onHudSnapshot?.(pintar);
window.ultron?.getHudSnapshot?.().then(snapshot => { if (snapshot) pintar(snapshot); });

document.addEventListener('visibilitychange', sincronizarMotoresOrbe);

window.addEventListener('beforeunload', () => {
  clearInterval(waveTimer);
  clearTimeout(collapseTimer);
  clearTimeout(shrinkWindowTimer);
  clearTimeout(autoActivityTimer);
  clearTimeout(quitArmTimer);
  clearTimeout(teleportAnimTimer);
  if (typeof pararSnapshot === 'function') pararSnapshot();
  (islandOrb.destruir || islandOrb.parar).call(islandOrb);
  (freeOrb.destruir || freeOrb.parar).call(freeOrb);
});
