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
    palcoFechar: async () => (calls.push(['palcoFechar']), { ok: true }),
    palcoAbrir: async id => (calls.push(['palcoAbrir', id]), true),
    shutdown: async () => ({ shutdown_requested: true }),
    unlockInfo: async () => ({ session: { desbloqueada: false }, hello: { disponivel: false } }),
    unlockHello: async () => (calls.push(['unlockHello']), { unlocked: false, error: 'hello_unavailable' }),
    unlockPin: async pin => (calls.push(['unlockPin', pin]), { unlocked: true, method: 'pin' }),
    lock: async () => (calls.push(['lock']), { locked: true }),
    undoList: async () => (calls.push(['undoList']), { itens: [], limite: 10 }),
    onSessionLocked: callback => (calls.push(['onSessionLocked']), () => {}),
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
  assert.equal((await transport.unlockInfo()).session.desbloqueada, false);
  await transport.unlockHello();
  await transport.unlockPin('2468');
  await transport.lock();
  assert.deepEqual(await transport.undoList(), { itens: [], limite: 10 });
  transport.onSessionLocked(() => {});
  await transport.poll();
  assert.deepEqual(calls, [['command', 'Olá'], ['microphone', true], ['selectMicrophone', 'input-1'],
    ['confirmation', 'req-1', true, '1234'], ['unlockHello'], ['unlockPin', '2468'], ['lock'], ['undoList'], ['onSessionLocked']]);
  assert.ok(events.some(event => event.event === 'NOTIFICATION' && event.data.message === 'Pronto'));
  assert.ok(events.some(event => event.event === 'SYSTEM_STATUS'));
  transport.disconnect();
});

test('bate-papo: limpar a sessão usa a ponte segura', async () => {
  const { bridge, calls } = makeBridge();
  bridge.clearConversation = async () => (calls.push(['clearConversation']), { cleared: 2 });
  const transport = new RealTransport({ bridge, onEvent: () => {} });
  await transport.connect({ poll: false });
  assert.deepEqual(await transport.clearConversation(), { cleared: 2 });
  assert.deepEqual(calls, [['clearConversation']]);
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

test('palco: transporte mapeia mostrar/fechar e usa a ponte segura', async () => {
  const { bridge, calls } = makeBridge();
  bridge.events = async () => ({ events: [
    { type: 'palco_show', palco: { id: 'a'.repeat(32), tipo: 'video', fonte: 'ultron-palco://media/x' } },
    { type: 'palco_hide' },
  ] });
  const events = [];
  const transport = new RealTransport({ bridge, onEvent: event => events.push(event) });
  await transport.connect({ poll: false });
  assert.deepEqual(events.filter(event => event.event.startsWith('PALCO')), [
    { event: 'PALCO_SHOW', data: { id: 'a'.repeat(32), tipo: 'video', fonte: 'ultron-palco://media/x' } },
    { event: 'PALCO_HIDE', data: {} },
  ]);
  await transport.palcoFechar();
  await transport.palcoAbrir('a'.repeat(32));
  assert.deepEqual(calls, [['palcoFechar'], ['palcoAbrir', 'a'.repeat(32)]]);
  transport.disconnect();
});

test('palco: interface usa textContent, CSP própria e protocolo privilegiado', async () => {
  const site = new URL('../', import.meta.url);
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const css = await readFile(fileURLToPath(new URL('style.css', site)), 'utf8');
  const main = await readFile(fileURLToPath(new URL('../main.js', site)), 'utf8');
  const preload = await readFile(fileURLToPath(new URL('../preload.js', site)), 'utf8');
  const protocol = await readFile(fileURLToPath(new URL('../palco-protocol.js', site)), 'utf8');
  assert.match(html, /id="palco"/);
  assert.match(html, /img-src[^"]*ultron-palco:/);
  assert.match(html, /media-src[^"]*ultron-palco:/);
  assert.match(html, /frame-src[^"]*ultron-palco:/);
  assert.match(app, /pre\.textContent = String\(dados\.conteudo/);
  assert.match(app, /ultron-palco:\/\/media\//);
  assert.doesNotMatch(app, /palcoBody[^\n]*innerHTML/);
  assert.match(css, /\.palco\[hidden\]/);
  // a saída do palco é um fade curto e cancelável, como a da gaveta
  assert.match(css, /\.palco\.saindo/);
  assert.match(app, /classList\.add\('saindo'\)/);
  assert.match(main, /registerSchemesAsPrivileged/);
  assert.match(main, /protocol\.handle\('ultron-palco'/);
  assert.match(preload, /palcoFechar: \(\) => ipcRenderer\.invoke\('palco:fechar'\)/);
  assert.match(preload, /abrirExterno: url => ipcRenderer\.invoke\('link:externo', url\)/);
  // PDF não usa iframe (o visualizador embutido não abre o esquema do palco):
  // mostra um cartão e abre pelo id opaco no visualizador do sistema.
  const pdfBranch = app.slice(app.indexOf("tipo === 'pdf'"), app.indexOf("tipo === 'site'"));
  assert.ok(pdfBranch.length > 0);
  assert.match(pdfBranch, /palco-doc/);
  assert.doesNotMatch(pdfBranch, /iframe/);
  assert.match(app, /transport\.palcoAbrir\(id\)/);
  assert.match(main, /ipcMain\.handle\('palco:abrir'/);
  assert.match(main, /abrirPdfPalco/);
  assert.match(main, /shell\.openPath\(arquivo\)/);
  assert.match(protocol, /entrada\.mime !== 'application\/pdf'/);
  assert.match(preload, /palcoAbrir: id => ipcRenderer\.invoke\('palco:abrir', id\)/);
  // YouTube erro 153: o iframe de vídeo não pode usar referrerpolicy=no-referrer
  const videoBranch = app.slice(app.indexOf("tipo === 'video'"), app.indexOf("tipo === 'imagem'"));
  assert.ok(videoBranch.length > 0);
  assert.doesNotMatch(videoBranch, /referrerpolicy:\s*'no-referrer'/);
  assert.match(videoBranch, /referrerpolicy:\s*'strict-origin-when-cross-origin'/);
});

test('youtube: embed vindo de file:// recebe Referer e Origin', async () => {
  const main = await readFile(fileURLToPath(new URL('../../main.js', import.meta.url)), 'utf8');
  const inicio = main.indexOf('function fixYoutubeEmbedHeaders()');
  const fim = main.indexOf('function createWindow()');
  assert.ok(inicio > -1 && fim > inicio, 'fixYoutubeEmbedHeaders deve existir antes de createWindow');

  let filtro;
  let handler;
  const fakeSession = {
    defaultSession: {
      webRequest: {
        onBeforeSendHeaders: (f, fn) => { filtro = f; handler = fn; },
      },
    },
  };
  new Function('session', `${main.slice(inicio, fim)}\nfixYoutubeEmbedHeaders();`)(fakeSession);

  assert.deepEqual(filtro.urls, [
    'https://*.youtube.com/embed/*',
    'https://*.youtube-nocookie.com/embed/*',
  ]);

  const enviados = fn => {
    let resultado;
    fn(details => { resultado = details; });
    return resultado;
  };

  const deFile = enviados(cb => handler({
    url: 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1',
    referrer: '',
    requestHeaders: { Accept: '*/*' },
  }, cb));
  assert.equal(deFile.requestHeaders.Referer, 'https://www.youtube-nocookie.com/');
  assert.equal(deFile.requestHeaders.Origin, 'https://www.youtube-nocookie.com');
  assert.equal(deFile.requestHeaders.Accept, '*/*');

  const deHttps = enviados(cb => handler({
    url: 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ',
    referrer: 'https://exemplo.com/',
    requestHeaders: {},
  }, cb));
  assert.equal(deHttps.requestHeaders.Origin, undefined);
  assert.equal(deHttps.requestHeaders.Referer, undefined);
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

test('voz e jeito: um painel só, com abas, cartões e persistência', async () => {
  const site = new URL('../', import.meta.url);
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  const css = await readFile(fileURLToPath(new URL('style.css', site)), 'utf8');

  // o bloco antigo de personalidade não ficou duplicado
  assert.equal((html.match(/id="profileSwatches"/g) || []).length, 1);
  assert.equal((html.match(/id="voiceSelect"/g) || []).length, 1);
  assert.match(html, /id="voiceStyleBlock"/);

  // quatro abas reais, cada uma com o seu painel
  for (const [aba, painel] of [
    ['tabVoice', 'paneVoice'], ['tabStyle', 'paneStyle'],
    ['tabMic', 'paneMic'], ['tabAbout', 'paneAbout'],
  ]) {
    assert.match(html, new RegExp(`id="${aba}"[^>]*aria-controls="${painel}"`));
    assert.match(html, new RegExp(`id="${painel}"[^>]*aria-labelledby="${aba}"`));
  }

  // “sobre você” e saudação fazem parte do mesmo painel
  assert.match(html, /id="userName"/);
  assert.match(html, /id="greetingToggle"[^>]*role="switch"/);
  assert.match(app, /function renderVoiceCards/);
  assert.match(app, /function escolherVoz/);
  assert.match(app, /function renderStyleCards/);
  assert.match(app, /function escolherJeito/);
  assert.match(app, /function alternarSaudacao/);
  assert.match(app, /personalidadeSalvar\(dados\)/);
  assert.match(app, /dados\.usuario = dadosDoUsuario\(\)/);
  assert.match(app, /dados\.saudacao = saudacaoLigada/);
  // alternar a saudação não pode repintar/apagar os campos ainda não aplicados
  assert.match(app, /personalidadeSalvar\(\{ saudacao: saudacaoLigada \}\)/);
  assert.match(app, /if \(usuario && salvo\.usuario\) preencherUsuario/);

  // o estilo novo existe e marca a escolha sem recolorir o resto
  assert.match(css, /\.seg-tabs\s*\{/);
  assert.match(css, /\.seg-tab\[aria-selected="true"\]/);
  assert.match(css, /\.choice-card\[aria-checked="true"\]/);
  assert.match(css, /\.field-col\s*\{/);
});

test('sessão local: IPC, powerMonitor e câmera ficam restritos à janela principal', async () => {
  const site = new URL('../', import.meta.url);
  const main = await readFile(fileURLToPath(new URL('../main.js', site)), 'utf8');
  const preload = await readFile(fileURLToPath(new URL('../preload.js', site)), 'utf8');
  const real = await readFile(fileURLToPath(new URL('src/real.js', site)), 'utf8');
  for (const canal of ['unlock:info', 'unlock:hello', 'unlock:pin', 'unlock:lock']) {
    assert.match(main, new RegExp(`ipcMain\\.handle\\('${canal}'`), canal);
  }
  assert.match(main, /powerMonitor\.on\('lock-screen'/);
  assert.match(main, /powerMonitor\.on\('suspend'/);
  assert.match(main, /lockPendente/);
  assert.match(main, /session:locked/);
  assert.match(main, /setPermissionRequestHandler/);
  assert.match(main, /setPermissionCheckHandler/);
  assert.match(main, /tipos\.includes\('video'\)\s*&&\s*!tipos\.includes\('audio'\)/);
  assert.match(preload, /unlockInfo: \(\) => ipcRenderer\.invoke\('unlock:info'\)/);
  assert.match(preload, /onSessionLocked: callback/);
  assert.doesNotMatch(real, /getUserMedia/);
});

test('diário: IPC e transporte leem a rota /undo pela ponte segura', async () => {
  const site = new URL('../', import.meta.url);
  const main = await readFile(fileURLToPath(new URL('../main.js', site)), 'utf8');
  const preload = await readFile(fileURLToPath(new URL('../preload.js', site)), 'utf8');
  assert.match(main, /ipcMain\.handle\('undo:list', event => isSender\(event, mainWindow\) \? api\.undoList\(\) : null\)/);
  assert.match(preload, /undoList: \(\) => ipcRenderer\.invoke\('undo:list'\)/);
});

test('prévia: todo id da tela real existe na prévia', async () => {
  const site = new URL('../', import.meta.url);
  const real = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const preview = await readFile(fileURLToPath(new URL('preview.html', site)), 'utf8');
  const ids = html => new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));
  const faltando = [...ids(real)].filter(id => !ids(preview).has(id)).sort();
  assert.deepEqual(faltando, []);
  assert.match(preview, /preview-mock\.js/);
  assert.doesNotMatch(real, /preview-mock\.js/);
});
