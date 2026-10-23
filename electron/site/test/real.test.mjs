import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { RealTransport } from '../src/real.js';

function makeBridge() {
  const calls = [];
  const bridge = {
    health: async () => ({ ok: true }),
    status: async () => ({ core_running: true, microphone_paused: false }),
    events: async () => ({ events: [{ type: 'notification', message: 'Pronto' }] }),
    command: async text => (calls.push(['command', text]), { operation_id: 'op-1' }),
    microphone: async paused => (calls.push(['microphone', paused]), { paused }),
    microphones: async () => ({ devices: [{ id: null, name: 'Padrão do sistema' }] }),
    selectMicrophone: async deviceId => (calls.push(['selectMicrophone', deviceId]), { selected_name: 'Webcam Mic' }),
    confirmation: async (...args) => (calls.push(['confirmation', ...args]), { accepted: true }),
    emergencyStop: async () => ({ stopped: true }),
    shutdown: async () => ({ shutdown_requested: true }),
  };
  return { bridge, calls };
}

test('transport uses only the named API bridge and maps current runtime events', async () => {
  const { bridge, calls } = makeBridge();
  const events = [];
  const transport = new RealTransport({ bridge, onEvent: event => events.push(event) });
  await transport.connect({ poll: false });
  assert.deepEqual(await transport.command('Olá'), { operation_id: 'op-1' });
  await transport.setMicrophonePaused(true);
  assert.equal((await transport.listMicrophones()).devices[0].name, 'Padrão do sistema');
  await transport.selectMicrophone('input-1');
  await transport.confirm('req-1', true, '1234');
  await transport.poll();
  assert.deepEqual(calls, [['command', 'Olá'], ['microphone', true], ['selectMicrophone', 'input-1'], ['confirmation', 'req-1', true, '1234']]);
  assert.ok(events.some(event => event.event === 'NOTIFICATION' && event.data.message === 'Pronto'));
  assert.ok(events.some(event => event.event === 'SYSTEM_STATUS'));
  transport.disconnect();
});

test('microphone settings reuse the secured core bridge and never create renderer capture', async () => {
  const site = new URL('../', import.meta.url);
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const main = await readFile(fileURLToPath(new URL('../main.js', site)), 'utf8');
  const preload = await readFile(fileURLToPath(new URL('../preload.js', site)), 'utf8');
  assert.match(html, /id="microphoneSelect"/);
  assert.match(html, /id="refreshMicrophones"/);
  assert.match(html, /id="saveMicrophone"/);
  assert.match(app, /transport\.listMicrophones\(\)/);
  assert.match(app, /transport\.selectMicrophone\(id \|\| null\)/);
  assert.doesNotMatch(app, /getUserMedia|SpeechRecognition/);
  assert.match(main, /isSender\(event, mainWindow\).*api\.selectMicrophone/s);
  assert.match(preload, /selectMicrophone: deviceId => ipcRenderer\.invoke\('api:microphone-device', deviceId\)/);
});

test('health failure stays offline and never enables a mock transport', async () => {
  const { bridge } = makeBridge();
  bridge.health = async () => { throw new Error('offline'); };
  const events = [];
  const transport = new RealTransport({ bridge, onEvent: event => events.push(event) });
  await assert.rejects(transport.connect({ poll: false }), /offline/);
  assert.ok(events.some(event => event.event === 'ULTRON_OFFLINE'));
  assert.equal(transport.mode, 'real');
});

test('a interface nunca expõe o PIN e não cria captura própria', async () => {
  const site = new URL('../', import.meta.url);
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const css = await readFile(fileURLToPath(new URL('style.css', site)), 'utf8');
  // campo de PIN é password e só existe quando o núcleo pede
  assert.match(app, /pin\.type\s*=\s*'password'/);
  assert.match(app, /data\.requires_pin/);
  assert.match(app, /transport\.confirm\(/);
  // a parada de emergência vai pelo canal do núcleo
  assert.match(app, /transport\.emergencyStop\(\)/);
  // nenhuma captura de áudio, credencial na tela ou transporte falso no app
  assert.doesNotMatch(app, /voiceListen|voiceSpeak|sessionStorage|MockTransport/);
  assert.doesNotMatch(html, /apiTokenInput|apiUrlInput|corePathInput/);
  assert.doesNotMatch(html, /preview-mock\.js/);   // o mock saiu do app
  // a paleta viva do núcleo continua existindo (tema controla --core)
  assert.match(css, /--core:\s*#ff3446/i);
});

test('trocar de tema muda a cor viva sem recolorir a logo', async () => {
  const site = new URL('../', import.meta.url);
  const css = await readFile(fileURLToPath(new URL('style.css', site)), 'utf8');
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  // a logo aparece na interface e no favicon, uma cópia só no projeto
  assert.match(html, /href="icons\/ULTRON-Logo\.png"/);
  // cada tema redefine --core (a cor viva), sem tocar em imagens
  for (const tema of ['jarvis', 'amber', 'emerald']) {
    assert.match(css, new RegExp(`:root\\[data-theme="${tema}"\\]\\s*\\{[^}]*--core:`), tema);
  }
  assert.doesNotMatch(css, /:root\[data-theme=[^}]*?img/s);
  // o app aplica o tema no documento e guarda a escolha
  assert.match(app, /documentElement\.dataset\.theme/);
  assert.match(app, /localStorage\.setItem\('ultron-theme'/);
  // o núcleo lê a cor viva do tema (não um valor fixo)
  const orb = await readFile(fileURLToPath(new URL('src/orb.js', site)), 'utf8');
  assert.match(orb, /getPropertyValue\('--core'\)/);
});
