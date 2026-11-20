import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { criarTelaCarregamento } from '../src/boot-screen.js';

const IDS = [
  'bootOverlay',
  'stage',
  'bootStarsCanvas',
  'bootOrbCanvas',
  'bootTimer',
  'bootStateWord',
  'bootStateHint',
  'bootStageLabel',
  'bootPctLabel',
  'bootProgressFill',
  'bootProgressSweep',
  'bootErrorBar',
  'bootErrorText',
  'bootRetryBtn',
  'bootBypassBtn',
];

function criarElemento(id, extra = {}) {
  const attrs = {};
  const listeners = {};
  const style = {};
  const classes = new Set();
  return {
    id,
    hidden: id === 'bootOverlay' || id === 'bootErrorBar' || id === 'bootBypassBtn',
    inert: false,
    textContent: '',
    dataset: {},
    style,
    listeners,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, force) => (force === undefined
        ? (classes.has(c) ? classes.delete(c) : classes.add(c))
        : (force ? classes.add(c) : classes.delete(c))),
      contains: c => classes.has(c),
    },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] ?? null; },
    addEventListener(tipo, fn) { listeners[tipo] = fn; },
    removeEventListener(tipo) { delete listeners[tipo]; },
    querySelector(sel) {
      if (sel === '.boot-stage-dot') return this._dot;
      if (sel === '.boot-stage-sub') return this._sub;
      return null;
    },
    ...extra,
  };
}

function criarDocumentoFalso() {
  const mapa = Object.fromEntries(IDS.map(id => [id, criarElemento(id)]));
  const cards = [0, 1, 2, 3].map(idx => {
    const card = criarElemento(`bootCard${idx}`);
    card.dataset.stage = String(idx);
    card._dot = criarElemento(`dot${idx}`);
    card._sub = criarElemento(`sub${idx}`);
    return card;
  });
  return {
    mapa,
    cards,
    getElementById: id => mapa[id] || null,
    querySelectorAll: sel => (sel === '.boot-stage-card' ? cards : []),
  };
}

test('iniciar exibe overlay pós-desbloqueio, trava stage e avança os 4 estágios reais até concluir', async () => {
  const doc = criarDocumentoFalso();
  let agora = 1000;
  let concluiu = 0;
  const boot = criarTelaCarregamento({
    doc,
    agoraMs: () => agora,
    duracaoMinMs: 200,
    fadeMs: 0,
    timeoutMs: 12000,
    aoConcluir: () => { concluiu += 1; },
  });

  boot.iniciar();
  assert.equal(boot.ativa(), true);
  assert.equal(doc.mapa.bootOverlay.hidden, false);
  assert.equal(doc.mapa.stage.inert, true);
  assert.equal(doc.mapa.bootStateWord.textContent, 'INICIALIZANDO');
  assert.equal(doc.mapa.bootPctLabel.textContent, '24%');

  boot.atualizar({ api_running: true, core_running: true, session_desbloqueada: true }, { historicoPronto: false });
  assert.equal(doc.mapa.bootStateWord.textContent, 'VERIFICANDO');
  assert.equal(doc.mapa.bootPctLabel.textContent, '52%');

  boot.atualizar(
    {
      api_running: true,
      core_running: true,
      session_desbloqueada: true,
      microphone_capturing: true,
      microphone_state: 'calibrando',
    },
    { historicoPronto: true },
  );
  assert.equal(doc.mapa.bootStateWord.textContent, 'CALIBRANDO');
  assert.equal(doc.mapa.bootPctLabel.textContent, '82%');
  assert.equal(boot.ativa(), true);

  boot.atualizar(
    { api_running: true, core_running: true, session_desbloqueada: true, microphone_state: 'aquecendo_afe' },
    { historicoPronto: true },
  );
  assert.equal(doc.mapa.bootStateWord.textContent, 'CALIBRANDO');
  assert.equal(doc.mapa.bootPctLabel.textContent, '82%');
  assert.equal(doc.cards[2]._sub.textContent, 'Aquecendo AFE');

  agora = 1350;
  boot.atualizar(
    { api_running: true, core_running: true, session_desbloqueada: true, microphone_state: 'ouvindo' },
    { historicoPronto: true },
  );
  assert.equal(doc.mapa.bootStateWord.textContent, 'ONLINE');
  assert.equal(doc.mapa.bootPctLabel.textContent, '100%');

  await new Promise(r => setTimeout(r, 380));
  assert.equal(concluiu, 1);
  assert.equal(boot.ativa(), false);
  assert.equal(doc.mapa.bootOverlay.hidden, true);
  assert.equal(doc.mapa.stage.inert, false);
});

test('modo texto (desativado) ou erro de microfone não travam o estágio 03', async () => {
  for (const statusVoz of [
    { microphone_state: 'desativado' },
    { microphone_state: 'erro', microphone_error: 'Sem microfone' },
    { microphone_state: 'calibrando', microphone_device_available: false },
  ]) {
    const doc = criarDocumentoFalso();
    let agora = 0;
    let concluiu = 0;
    const boot = criarTelaCarregamento({
      doc,
      agoraMs: () => agora,
      duracaoMinMs: 0,
      fadeMs: 0,
      timeoutMs: 12000,
      aoConcluir: () => { concluiu += 1; },
    });
    boot.iniciar();
    agora = 50;
    boot.atualizar(
      { api_running: true, core_running: true, session_desbloqueada: true, ...statusVoz },
      { historicoPronto: true },
    );
    assert.equal(doc.mapa.bootPctLabel.textContent, '100%');
    await new Promise(r => setTimeout(r, 380));
    assert.equal(concluiu, 1);
    assert.equal(doc.mapa.bootOverlay.hidden, true);
  }
});

test('timeout de 12s entra em FALHA DE CANAL, libera bypass só após estágio 01+02 e retry reinicia prazo', () => {
  const doc = criarDocumentoFalso();
  let agora = 0;
  let tentativas = 0;
  let concluiu = 0;
  const boot = criarTelaCarregamento({
    doc,
    agoraMs: () => agora,
    duracaoMinMs: 0,
    fadeMs: 0,
    timeoutMs: 12000,
    aoTentarNovamente: () => { tentativas += 1; },
    aoConcluir: () => { concluiu += 1; },
  });

  boot.iniciar();
  // Travado no estágio 01: sem bypass
  agora = 12500;
  boot.atualizar({ api_running: false, core_running: false }, { historicoPronto: false });
  assert.equal(doc.mapa.bootStateWord.textContent, 'FALHA DE CANAL');
  assert.equal(doc.mapa.bootErrorBar.hidden, false);
  assert.equal(doc.mapa.bootBypassBtn.hidden, true);

  // Retry limpa erro e reinicia relógio
  doc.mapa.bootRetryBtn.listeners.click();
  assert.equal(tentativas, 1);
  assert.equal(doc.mapa.bootErrorBar.hidden, true);

  // Agora 01+02 prontos, mas 03 travado em aquecendo_afe -> timeout libera bypass
  agora = 25000;
  boot.atualizar(
    { api_running: true, core_running: true, session_desbloqueada: true, microphone_state: 'aquecendo_afe' },
    { historicoPronto: true },
  );
  assert.equal(doc.mapa.bootStateWord.textContent, 'FALHA DE CANAL');
  assert.equal(doc.mapa.bootBypassBtn.hidden, false);

  doc.mapa.bootBypassBtn.listeners.click();
  assert.equal(concluiu, 1);
  assert.equal(boot.ativa(), false);
  assert.equal(doc.mapa.bootOverlay.hidden, true);
  assert.equal(doc.mapa.stage.inert, false);
});

test('cancelar (re-bloqueio) fecha imediatamente o overlay sem concluir boot nem deixar stage preso', () => {
  const doc = criarDocumentoFalso();
  let concluiu = 0;
  const boot = criarTelaCarregamento({
    doc,
    duracaoMinMs: 0,
    fadeMs: 0,
    aoConcluir: () => { concluiu += 1; },
  });
  boot.iniciar();
  assert.equal(doc.mapa.bootOverlay.hidden, false);
  boot.cancelar();
  assert.equal(boot.ativa(), false);
  assert.equal(doc.mapa.bootOverlay.hidden, true);
  assert.equal(doc.mapa.stage.inert, false);
  assert.equal(concluiu, 0);
});

test('atualizar após concluir nunca reabre o overlay', async () => {
  const doc = criarDocumentoFalso();
  let agora = 0;
  const boot = criarTelaCarregamento({
    doc,
    agoraMs: () => agora,
    duracaoMinMs: 0,
    fadeMs: 0,
  });
  boot.iniciar();
  agora = 100;
  boot.atualizar(
    { api_running: true, core_running: true, session_desbloqueada: true, microphone_state: 'ouvindo' },
    { historicoPronto: true },
  );
  await new Promise(r => setTimeout(r, 380));
  assert.equal(doc.mapa.bootOverlay.hidden, true);
  boot.atualizar(
    { api_running: true, core_running: true, session_desbloqueada: true, microphone_state: 'ouvindo' },
    { historicoPronto: true },
  );
  assert.equal(boot.ativa(), false);
  assert.equal(doc.mapa.bootOverlay.hidden, true);
});

test('index.html, app.js e package.json incluem #bootOverlay respeitando a CSP', async () => {
  const site = new URL('../', import.meta.url);
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  const pkg = await readFile(fileURLToPath(new URL('../package.json', site)), 'utf8');

  for (const id of [
    'bootOverlay', 'bootStarsCanvas', 'bootOrbCanvas', 'bootTimer',
    'bootStateWord', 'bootStateHint', 'bootStageLabel', 'bootPctLabel',
    'bootProgressFill', 'bootProgressSweep', 'bootStageGrid',
    'bootErrorBar', 'bootRetryBtn', 'bootBypassBtn',
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /<meta http-equiv="Content-Security-Policy"[^>]*script-src 'self'/);
  assert.match(app, /import\s+\{\s*criarTelaCarregamento\s*\}\s+from\s+'\.\/src\/boot-screen\.js'/);
  assert.match(app, /bootScreen\.iniciar\(\)/);
  assert.match(app, /bootScreen\.cancelar\(\)/);
  assert.match(pkg, /"site\/src\/boot-screen\.js"/);
});
