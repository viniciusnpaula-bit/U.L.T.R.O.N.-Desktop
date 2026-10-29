import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { criarDesbloqueio, motivoCamera } from '../src/unlock.js';

const IDS = ['unlock', 'stage', 'unlockCameraVideo', 'unlockStatus', 'unlockPin',
  'unlockPinBlock', 'unlockPinForm', 'unlockHello', 'unlockLater', 'unlockLog',
  'unlockHelloState', 'unlockPinState', 'unlockCameraState', 'unlockCameraError',
  'unlockIrreversiveis', 'unlockHistorico', 'unlockVersion', 'unlockSession'];

function elemento(id) {
  return { id, hidden: false, textContent: '', value: '', disabled: false, dataset: {},
    srcObject: null, filhos: [], listeners: {}, focado: false,
    addEventListener(tipo, callback) { this.listeners[tipo] = callback; },
    focus() { this.focado = true; },
    replaceChildren(...itens) { this.filhos = itens; },
    play() { return Promise.resolve(); } };
}

function documentoFalso() {
  const mapa = Object.fromEntries(IDS.map(id => [id, elemento(id)]));
  return { mapa, getElementById: id => mapa[id] || null, createElement: () => elemento('novo') };
}

function transporteFalso() {
  return {
    chamadas: [],
    unlockInfo: async () => ({ session: { desbloqueada: false }, hello: { disponivel: true, motivo: 'pronto' },
      pin_configurado: true, irreversiveis: ['apagar_arquivo'], versao: '1.19.0',
      historico: { cifrado: true, chave: 'DPAPI', migrado: true } }),
    unlockHello: async function () { this.chamadas.push(['hello']); return { unlocked: true, method: 'hello' }; },
    unlockPin: async function (pin) { this.chamadas.push(['pin', pin]); return { unlocked: false, error: 'pin_invalid' }; },
    lock: async () => ({ locked: true }),
  };
}

test('motivoCamera traduz só os erros reais conhecidos', () => {
  assert.equal(motivoCamera({ name: 'NotAllowedError' }), 'Permissão da câmera negada');
  assert.equal(motivoCamera({ name: 'NotFoundError' }), 'Nenhuma câmera encontrada');
  assert.equal(motivoCamera({ name: 'NotReadableError' }), 'Câmera em uso por outro app');
  assert.equal(motivoCamera({ name: 'Outro' }), 'Câmera indisponível');
});

test('abrir mostra o overlay, liga só vídeo e parar solta as faixas', async () => {
  const doc = documentoFalso();
  const paradas = [];
  const faixa = { stop: () => paradas.push('stop') };
  const chamadas = [];
  const midia = { getUserMedia: async restricoes => (chamadas.push(restricoes),
    { getTracks: () => [faixa] }) };
  const desbloqueio = criarDesbloqueio({ transport: transporteFalso(), doc, midia });
  await desbloqueio.abrir();
  assert.equal(doc.mapa.unlock.hidden, false);
  assert.equal(doc.mapa.stage.inert, true);
  assert.deepEqual(chamadas, [{ video: true, audio: false }]);
  assert.equal(doc.mapa.unlockCameraState.textContent, 'ativa');
  desbloqueio.parar();
  assert.deepEqual(paradas, ['stop']);
  assert.equal(doc.mapa.unlock.hidden, false);
});

test('sem Windows Hello não liga a câmera e explica o PIN', async () => {
  const doc = documentoFalso();
  const chamadas = [];
  const transporte = transporteFalso();
  transporte.unlockInfo = async () => ({ session: { desbloqueada: false },
    hello: { disponivel: false, motivo: 'Sem sensor' }, pin_configurado: true });
  const desbloqueio = criarDesbloqueio({ transport: transporte, doc,
    midia: { getUserMedia: async restricoes => (chamadas.push(restricoes),
      { getTracks: () => [] }) } });
  await desbloqueio.abrir();
  assert.deepEqual(chamadas, []);
  assert.equal(doc.mapa.unlockCameraState.textContent, 'desligada');
  assert.match(doc.mapa.unlockCameraError.textContent, /PIN/);
  assert.equal(doc.mapa.unlockHello.disabled, true);
});

test('definirSessao não reabre a cada polling e reabre na transição liberado/bloqueado', async () => {
  const doc = documentoFalso();
  const desbloqueio = criarDesbloqueio({ transport: transporteFalso(), doc,
    midia: { getUserMedia: async () => ({ getTracks: () => [] }) } });
  await desbloqueio.abrir();
  doc.mapa.unlockLater.listeners.click();
  assert.equal(doc.mapa.unlock.hidden, true);
  desbloqueio.definirSessao(false);
  assert.equal(doc.mapa.unlock.hidden, true);          // "Agora não" continua valendo
  desbloqueio.definirSessao(true);
  assert.equal(doc.mapa.unlock.hidden, true);
  desbloqueio.definirSessao(false);
  assert.equal(doc.mapa.unlock.hidden, false);         // liberado -> bloqueado reabre
});

test('Hello libera e esconde; PIN errado limpa o campo e explica', async () => {
  const doc = documentoFalso();
  const transporte = transporteFalso();
  let mudou = null;
  const desbloqueio = criarDesbloqueio({ transport: transporte, doc,
    aoMudarSessao: valor => { mudou = valor; },
    midia: { getUserMedia: async () => ({ getTracks: () => [] }) } });
  await desbloqueio.abrir();
  await doc.mapa.unlockHello.listeners.click();
  assert.deepEqual(transporte.chamadas, [['hello']]);
  assert.equal(doc.mapa.unlock.hidden, true);
  assert.equal(mudou, true);

  transporte.unlockHello = async () => ({ unlocked: false, error: 'not_verified' });
  await desbloqueio.abrir();
  await doc.mapa.unlockHello.listeners.click();
  assert.match(doc.mapa.unlockStatus.textContent, /Não foi possível verificar/);

  doc.mapa.unlockPin.value = '0000';
  await doc.mapa.unlockPinForm.listeners.submit({ preventDefault() {} });
  assert.deepEqual(transporte.chamadas.at(-1), ['pin', '0000']);
  assert.equal(doc.mapa.unlockPin.value, '');
  assert.equal(doc.mapa.unlockStatus.textContent, 'PIN incorreto.');
  assert.equal(doc.mapa.unlockLog.filhos.length, 3);
});

test('overlay usa dados reais, z-index abaixo do modal e CSP intacta', async () => {
  const site = new URL('../', import.meta.url);
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const css = await readFile(fileURLToPath(new URL('style.css', site)), 'utf8');
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  const unlock = await readFile(fileURLToPath(new URL('src/unlock.js', site)), 'utf8');
  assert.match(html, /id="unlock"[^>]*role="dialog"[^>]*aria-modal="true"[^>]*hidden/);
  assert.match(html, /id="unlockCameraVideo"[^>]*autoplay[^>]*muted[^>]*playsinline/);
  assert.match(html, /id="unlockPin"[^>]*type="password"[^>]*inputmode="numeric"/);
  assert.match(css, /\.unlock\s*\{[^}]*z-index:\s*30/s);
  assert.match(css, /\.modal-backdrop\s*\{[^}]*z-index:\s*40/s);
  assert.match(css, /prefers-reduced-motion[^}]*\.unlock-scan/s);
  assert.match(app, /desbloqueio\.definirSessao\(data\.session_desbloqueada === true\)/);
  assert.match(app, /transport\.onSessionLocked\(/);
  assert.match(app, /desbloqueio\.abrir\(\)/);
  assert.match(app, /desbloqueio\.parar\(\)/);
  assert.match(unlock, /getUserMedia\(\{ video: true, audio: false \}\)/);
  assert.doesNotMatch(unlock, /innerHTML/);
});
