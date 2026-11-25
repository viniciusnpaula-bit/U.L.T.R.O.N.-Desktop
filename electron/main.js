const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { app, BrowserWindow, ipcMain, powerMonitor, protocol, screen, session, shell } = require('electron');
const { createApiClient } = require('./api');
const { validarUrlExterna } = require('./links');
const { criarRespostaPalco, abrirPdfPalco } = require('./palco-protocol');

// O palco entrega mídia por um esquema próprio: a interface recebe um id
// opaco, nunca o caminho absoluto do arquivo nem o token da API.
protocol.registerSchemesAsPrivileged([{
  scheme: 'ultron-palco',
  privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, bypassCSP: false },
}]);

const ULTRON_ROOT = path.resolve(process.env.ULTRON_ROOT || path.join(__dirname, '..'));
const ULTRON_DATA_DIR = process.env.ULTRON_DATA_DIR ? path.resolve(process.env.ULTRON_DATA_DIR) : '';
const responderPalco = criarRespostaPalco({ root: ULTRON_ROOT, dataDir: ULTRON_DATA_DIR });

const api = createApiClient({ baseUrl: process.env.ULTRON_API_URL, token: process.env.ULTRON_API_TOKEN });
const SKILL_SLUG_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const TASK_ID_RE = /^[a-f0-9]{12}$/;
// Só estes domínios oficiais podem ser abertos pelo botão "obter chave".
const LINK_HOSTS = Object.freeze([
  'aistudio.google.com', 'console.groq.com', 'build.nvidia.com',
  'platform.openai.com', 'openrouter.ai', 'console.mistral.ai',
  'platform.deepseek.com', 'cloud.cerebras.ai', 'api.together.xyz',
  'console.x.ai', 't.me', 'myaccount.google.com', 'developer.spotify.com',
]);
const quickActions = Object.freeze({
  browser: 'Abra o navegador', spotify: 'Abra o Spotify', media: 'Pause ou retome a música',
  volume: 'Aumente o volume do PC', vol_up: 'Aumente o volume do PC', vol_down: 'Diminua o volume do PC',
  rocket: 'Abra o Rocket League', game: 'Ative o modo jogo', minimize: 'Minimize tudo',
  mic: '__TOGGLE_MIC__', stop: '__EMERGENCY_STOP__',
});
const ISLAND_POSITIONS = Object.freeze(['top-center', 'top-left', 'top-right', 'right', 'left']);
const ISLAND_STYLES = Object.freeze(['island', 'orb']);
const ISLAND_COMPACT_TOP = Object.freeze({ width: 256, height: 40 });
const ISLAND_COMPACT_SIDE = Object.freeze({ width: 46, height: 144 });
const ISLAND_EXPANDED = Object.freeze({ width: 460, height: 256 });
const ORB_COMPACT = Object.freeze({ width: 116, height: 116 });
const ORB_EXPANDED = Object.freeze({ width: 492, height: 320 });
let mainWindow;
let miniWindow;
let lastHudSnapshot = null;
let nextActionRequest = 0;
const pendingActions = new Map();
let quitting = false;
let closingFromIsland = false;
let islandExpanded = false;
let islandStyle = 'island';
let islandPosition = 'top-center';
let orbSavedPos = null;
let orbTeleportSec = 10;
let orbTeleportTimer = null;
let orbTeleportMoveTimer = null;
let orbTeleportSeq = 0;
let orbTeleportOutSeq = 0;
let orbTeleportPhase = 'idle';
let islandHiddenByFullscreen = false;
let zoomsEnabled = false;
let lockPendente = false;

function isSender(event, window) {
  return Boolean(window && !window.isDestroyed() && event.sender === window.webContents &&
    (!event.senderFrame || event.senderFrame === window.webContents.mainFrame));
}

function registerApiHandlers() {
  const methods = {
    'api:health': () => api.health(), 'api:status': () => api.status(), 'api:events': () => api.events(),
    'api:conversation': () => api.conversation(),
    'api:conversation-clear': () => api.clearConversation(),
    'api:command': (_event, text) => api.command(text), 'api:microphone': (_event, paused) => api.microphone(paused),
      'api:confirmation': (_event, requestId, approved, pin) => api.confirmation(requestId, approved, pin),
    'api:emergency-stop': () => api.emergencyStop(), 'api:shutdown': () => api.shutdown(),
  };
  for (const [channel, handler] of Object.entries(methods)) ipcMain.handle(channel, handler);

  ipcMain.handle('unlock:info', event => isSender(event, mainWindow) ? api.unlockInfo() : null);
  ipcMain.handle('unlock:hello', event => isSender(event, mainWindow) ? api.unlockHello() : null);
  ipcMain.handle('unlock:pin', (event, pin) => {
    if (!isSender(event, mainWindow) || typeof pin !== 'string' || pin.length < 1 || pin.length > 64) return null;
    return api.unlockPin(pin);
  });
  ipcMain.handle('unlock:lock', event => isSender(event, mainWindow) ? api.lock() : null);
  ipcMain.handle('api:autostart', (event, enabled) => {
    if (!isSender(event, mainWindow) || typeof enabled !== 'boolean') return null;
    return api.setAutostart(enabled);
  });
  ipcMain.handle('undo:list', event => isSender(event, mainWindow) ? api.undoList() : null);

  ipcMain.handle('api:microphones', event => {
    if (!isSender(event, mainWindow)) throw new TypeError('Janela do ULTRON inválida.');
    return api.microphones();
  });
  ipcMain.handle('api:microphone-device', (event, deviceId) => {
    if (!isSender(event, mainWindow) || (deviceId !== null && typeof deviceId !== 'string')) {
      throw new TypeError('Solicitação de microfone inválida.');
    }
    return api.selectMicrophone(deviceId);
  });

  // zoom desligado de propósito: a interface é desenhada para 100% e o Electron
  // reabre sempre com o último fator de zoom aplicado.
  ipcMain.handle('view:zoom', (event, enabled) => {
    if (!isSender(event, mainWindow)) return false;
    zoomsEnabled = enabled === true;
    if (!zoomsEnabled && mainWindow) {
      mainWindow.webContents.setZoomFactor(1);
      mainWindow.webContents.setZoomLevel(0);
    }
    if (mainWindow) mainWindow.webContents.setVisualZoomLevelLimits(1, 1);
    return zoomsEnabled;
  });

  ipcMain.handle('cofre:status', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.cofreStatus();
  });
  ipcMain.handle('cofre:guardar', (event, nome, valor) => {
    if (!isSender(event, mainWindow) || typeof nome !== 'string' || typeof valor !== 'string') return null;
    return api.cofreGuardar(nome, valor);
  });
  ipcMain.handle('cofre:remover', (event, nome) => {
    if (!isSender(event, mainWindow) || typeof nome !== 'string') return null;
    return api.cofreRemover(nome);
  });
  ipcMain.handle('cofre:testar', (event, nome) => {
    if (!isSender(event, mainWindow) || typeof nome !== 'string') return null;
    return api.cofreTestar(nome);
  });
  ipcMain.handle('bloco1:status', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.bloco1Status();
  });
  ipcMain.handle('bloco1:salvar', (event, config) => {
    if (!isSender(event, mainWindow) || typeof config !== 'object') return null;
    return api.bloco1Salvar(config);
  });
  ipcMain.handle('bloco1:executar', (event, acao, params) => {
    if (!isSender(event, mainWindow) || typeof acao !== 'string') return null;
    return api.bloco1Executar(acao, params);
  });
  ipcMain.handle('bloco2:status', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.bloco2Status();
  });
  ipcMain.handle('bloco2:salvar', (event, config) => {
    if (!isSender(event, mainWindow) || typeof config !== 'object') return null;
    return api.bloco2Salvar(config);
  });
  ipcMain.handle('bloco2:executar', (event, acao, params) => {
    if (!isSender(event, mainWindow) || typeof acao !== 'string') return null;
    return api.bloco2Executar(acao, params);
  });

  // Links de "onde obter a chave": abre no navegador do sistema, nunca dentro do app.
  ipcMain.handle('link:abrir', async (event, url) => {
    if (!isSender(event, mainWindow) || typeof url !== 'string' || url.length > 2048) return false;
    let parsed;
    try { parsed = new URL(url); } catch { return false; }
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.port) return false;
    if (!LINK_HOSTS.includes(parsed.hostname)) return false;
    await shell.openExternal(parsed.href);
    return true;
  });

  // "abrir no navegador" do palco: segunda validação antes de sair do app.
  ipcMain.handle('link:externo', async (event, url) => {
    if (!isSender(event, mainWindow)) return false;
    const destino = await validarUrlExterna(url);
    if (!destino) return false;
    await shell.openExternal(destino);
    return true;
  });

  ipcMain.handle('palco:fechar', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.palcoFechar();
  });

  // O visualizador de PDF embutido do Electron não abre o esquema do palco.
  // Em vez de expor o caminho para a interface, ela manda o id opaco e o
  // processo principal abre o arquivo no visualizador do sistema. Só PDF,
  // só com id válido e só enquanto a entrada do manifesto não expirou.
  ipcMain.handle('palco:abrir', async (event, id) => {
    if (!isSender(event, mainWindow) || typeof id !== 'string') return false;
    return abrirPdfPalco({
      root: ULTRON_ROOT,
      dataDir: ULTRON_DATA_DIR,
      id,
      abrir: arquivo => shell.openPath(arquivo),
    });
  });

  ipcMain.handle('mem:fatos', (event, busca) => {
    if (!isSender(event, mainWindow)) return null;
    const termo = typeof busca === 'string' ? busca.slice(0, 300) : '';
    return api.fatosListar(termo);
  });
  ipcMain.handle('mem:fato-corrigir', (event, id, texto) => {
    if (!isSender(event, mainWindow) || !Number.isSafeInteger(id)) return null;
    return api.fatoCorrigir(id, String(texto || ''));
  });
  ipcMain.handle('mem:fato-apagar', (event, id) => {
    if (!isSender(event, mainWindow) || !Number.isSafeInteger(id)) return null;
    return api.fatoApagar(id);
  });
  ipcMain.handle('mem:lembrete-cancelar', (event, numero, trecho) => {
    if (!isSender(event, mainWindow)) return null;
    if (numero !== null && numero !== undefined && !Number.isSafeInteger(numero)) return null;
    return api.lembreteCancelar(numero ?? null, trecho);
  });
  ipcMain.handle('agenda:listar', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.agendaListar();
  });
  ipcMain.handle('agenda:cancelar', (event, numero, trecho) => {
    if (!isSender(event, mainWindow)) return null;
    if (numero !== null && numero !== undefined && !Number.isSafeInteger(numero)) return null;
    return api.agendaCancelar(numero ?? null, trecho);
  });
  ipcMain.handle('fluxos:listar', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.fluxosListar();
  });
  ipcMain.handle('fluxos:executar', (event, id) => {
    if (!isSender(event, mainWindow)) throw new TypeError('Janela do ULTRON inválida.');
    return api.executarFluxo(id);
  });

  ipcMain.handle('skills:listar', event => {
    if (!isSender(event, mainWindow)) throw new TypeError('Janela do ULTRON inválida.');
    return api.skillsListar();
  });
  ipcMain.handle('skills:aprovar', (event, nome) => {
    if (!isSender(event, mainWindow)) throw new TypeError('Janela do ULTRON inválida.');
    if (typeof nome !== 'string' || !SKILL_SLUG_RE.test(nome)) {
      throw new TypeError('Identificador de skill inválido.');
    }
    return api.skillsAprovar(nome);
  });
  ipcMain.handle('skills:descartar', (event, nome) => {
    if (!isSender(event, mainWindow)) throw new TypeError('Janela do ULTRON inválida.');
    if (typeof nome !== 'string' || !SKILL_SLUG_RE.test(nome)) {
      throw new TypeError('Identificador de skill inválido.');
    }
    return api.skillsDescartar(nome);
  });
  ipcMain.handle('tarefas:listar', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.tarefasListar();
  });
  ipcMain.handle('tarefas:cancelar', (event, id) => {
    if (!isSender(event, mainWindow) || typeof id !== 'string' || !TASK_ID_RE.test(id)) {
      throw new TypeError('Identificador de tarefa inválido.');
    }
    return api.tarefaCancelar(id);
  });

  ipcMain.handle('mem:lembretes', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.lembretesListar();
  });

  ipcMain.handle('voz:info', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.vozInfo();
  });
  ipcMain.handle('voz:salvar', (event, valores) => {
    if (!isSender(event, mainWindow)) return null;
    return api.vozSalvar(valores);
  });
  ipcMain.handle('voz:restaurar', event => isSender(event, mainWindow) && api.vozRestaurar());
  ipcMain.handle('voz:testar', (event, texto) => {
    if (!isSender(event, mainWindow)) return null;
    return api.vozTestar(texto);
  });
  ipcMain.handle('voz:testar-microfone', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.microfoneTestar();
  });
  ipcMain.handle('voz:personalidade', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.personalidadeInfo();
  });
  ipcMain.handle('voz:personalidade-salvar', (event, valores) => {
    if (!isSender(event, mainWindow)) return null;
    return api.personalidadeSalvar(valores);
  });
  ipcMain.handle('voz:personalidade-restaurar', event => isSender(event, mainWindow) && api.personalidadeRestaurar());
  ipcMain.handle('voz:personalidade-previa', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.personalidadePrevia();
  });

  ipcMain.handle('update:info', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.updateInfo();
  });
  ipcMain.handle('update:check', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.updateCheck();
  });
  ipcMain.handle('update:apply', (event, restartAfter) => {
    if (!isSender(event, mainWindow)) return null;
    return api.updateApply(restartAfter === true);
  });
  ipcMain.handle('update:launch', async event => {
    if (!isSender(event, mainWindow)) return false;
    const launched = await api.updateLaunch();
    const ok = Boolean(launched && (launched === true || launched.launched === true));
    if (ok) setTimeout(() => app.quit(), 400);
    return ok;
  });
  ipcMain.handle('update:rollback', event => {
    if (!isSender(event, mainWindow)) return false;
    return api.updateRollback();
  });

  ipcMain.handle('mobile:pairing-status', event => {
    if (!isSender(event, mainWindow)) return null;
    return api.mobilePairingStatus();
  });
  ipcMain.handle('mobile:pairing-rotate', (event, deviceId, killswitchSeparado) => {
    if (!isSender(event, mainWindow)) return null;
    if (deviceId !== undefined && deviceId !== null && typeof deviceId !== 'string') return null;
    return api.mobilePairingRotate(deviceId || null, killswitchSeparado === true);
  });
  ipcMain.handle('mobile:pairing-revoke', (event, deviceId) => {
    if (!isSender(event, mainWindow)) return null;
    if (deviceId !== undefined && deviceId !== null && typeof deviceId !== 'string') return null;
    return api.mobilePairingRevoke(deviceId || null);
  });

  ipcMain.handle('hud:toggle', event => {
    if (!isSender(event, mainWindow)) return false;
    if (miniWindow && !miniWindow.isDestroyed()) { miniWindow.close(); return false; }
    createMiniWindow();
    return true;
  });
  ipcMain.handle('app:quit', event => {
    if (!isSender(event, mainWindow)) return false;
    quitting = true;
    app.quit();
    return true;
  });
  ipcMain.handle('hud:snapshot', event => isSender(event, miniWindow) ? lastHudSnapshot : null);
  ipcMain.handle('hud:publish', (event, snapshot) => {
    if (!isSender(event, mainWindow) || !snapshot || typeof snapshot !== 'object') return false;
    const theme = ['ultron', 'jarvis', 'amber', 'emerald'].includes(snapshot.theme) ? snapshot.theme : 'ultron';
    const islandMode = ['auto', 'hover', 'click', 'activity'].includes(snapshot.islandMode) ? snapshot.islandMode : 'auto';
    const nextStyle = ISLAND_STYLES.includes(snapshot.islandStyle) ? snapshot.islandStyle : 'island';
    const islandPos = ISLAND_POSITIONS.includes(snapshot.islandPos) ? snapshot.islandPos : 'top-center';
    const rawTele = Number(snapshot.orbTeleportSec);
    const nextTele = Number.isFinite(rawTele) ? Math.min(300, Math.max(0, Math.round(rawTele))) : orbTeleportSec;
    const geometriaMudou = islandPos !== islandPosition || nextStyle !== islandStyle;
    const teleMudou = nextTele !== orbTeleportSec || nextStyle !== islandStyle;
    islandStyle = nextStyle;
    islandPosition = islandPos;
    orbTeleportSec = nextTele;
    const clean = (value, max = 500) => typeof value === 'string' ? value.slice(0, max) : '';
    const num = (value, min, max) => {
      const n = Number(value);
      return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : null;
    };
    const fullscreen = snapshot.fullscreen === true;
    const layoutInfo = computeOrbLayout(islandExpanded);
    lastHudSnapshot = Object.freeze({
      core: clean(snapshot.core, 40) || 'Indisponível',
      api: clean(snapshot.api, 40) || 'Indisponível',
      microphone: clean(snapshot.microphone, 60) || 'Indisponível',
      response: clean(snapshot.response, 500) || 'Indisponível',
      wake: clean(snapshot.wake, 24) || 'Ultron',
      theme,
      islandStyle,
      islandMode,
      islandPos,
      orbSide: layoutInfo.side,
      orbOffsetY: layoutInfo.orbOffsetY,
      orbTeleportSec,
      orbTeleportSeq,
      orbTeleportOutSeq,
      orbTeleportPhase,
      paused: snapshot.paused === true,
      capturing: snapshot.capturing === true,
      speaking: snapshot.speaking === true,
      processing: snapshot.processing === true,
      micLevel: num(snapshot.micLevel, 0, 100) ?? 0,
      cpu: num(snapshot.cpu, 0, 100),
      ram: num(snapshot.ram, 0, 100),
      palcoTipo: clean(snapshot.palcoTipo, 30),
      palcoTitulo: clean(snapshot.palcoTitulo, 120),
      palcoResumo: clean(snapshot.palcoResumo, 320),
      fullscreen,
    });
    if (miniWindow && !miniWindow.isDestroyed()) {
      if (geometriaMudou) miniWindow.setBounds(islandBounds(islandExpanded, islandPosition), false);
      miniWindow.webContents.send('hud:snapshot', lastHudSnapshot);
      if (fullscreen && miniWindow.isVisible()) {
        islandHiddenByFullscreen = true;
        miniWindow.hide();
      } else if (!fullscreen && islandHiddenByFullscreen) {
        islandHiddenByFullscreen = false;
        miniWindow.showInactive();
      }
      if (teleMudou) syncOrbTeleportTimer();
    } else if (teleMudou) {
      stopOrbTeleportTimer();
    }
    return true;
  });
  ipcMain.handle('hud:expand', (event, expanded) => {
    if (!isSender(event, miniWindow) || typeof expanded !== 'boolean') return null;
    return resizeMiniWindow(expanded);
  });
  ipcMain.handle('hud:move', (event, payload) => {
    if (!isSender(event, miniWindow) || !payload || typeof payload !== 'object') return null;
    const dx = Number(payload.dx);
    const dy = Number(payload.dy);
    if (!Number.isFinite(dx) || !Number.isFinite(dy)) return null;
    return moveOrbBy(Math.round(dx), Math.round(dy), payload.commit === true);
  });
  ipcMain.handle('hud:return', event => {
    if (!isSender(event, miniWindow)) return false;
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
    miniWindow.close();
    return true;
  });
  ipcMain.handle('hud:quit', event => {
    if (!isSender(event, miniWindow)) return false;
    quitting = true;
    if (miniWindow && !miniWindow.isDestroyed()) miniWindow.close();
    app.quit();
    return true;
  });
  ipcMain.handle('hud:action', async (event, actionId) => {
    if (!isSender(event, miniWindow) || !Object.hasOwn(quickActions, actionId) || !mainWindow || mainWindow.isDestroyed()) return false;
    const requestId = ++nextActionRequest;
    return new Promise(resolve => {
      const timeout = setTimeout(() => { pendingActions.delete(requestId); resolve(false); }, 15000);
      pendingActions.set(requestId, accepted => { clearTimeout(timeout); pendingActions.delete(requestId); resolve(accepted === true); });
      mainWindow.webContents.send('hud:run-action', { requestId, actionId });
    });
  });
  ipcMain.handle('hud:command', async (event, text) => {
    if (!isSender(event, miniWindow) || typeof text !== 'string' || !mainWindow || mainWindow.isDestroyed()) return false;
    const limpo = text.trim().slice(0, 500);
    if (!limpo) return false;
    const requestId = ++nextActionRequest;
    return new Promise(resolve => {
      const timeout = setTimeout(() => { pendingActions.delete(requestId); resolve(false); }, 15000);
      pendingActions.set(requestId, accepted => { clearTimeout(timeout); pendingActions.delete(requestId); resolve(accepted === true); });
      mainWindow.webContents.send('hud:run-command', { requestId, text: limpo });
    });
  });
  ipcMain.on('hud:action-result', (event, requestId, accepted) => {
    if (!isSender(event, mainWindow) || !Number.isSafeInteger(requestId)) return;
    pendingActions.get(requestId)?.(accepted);
  });
}

// O bloqueio do Windows vale como bloqueio do ULTRON. Se o POST /lock falhar
// (ex.: durante o suspend), a flag fica ligada e o resume tenta de novo.
async function tentarBloquear(tentativas) {
  for (let indice = 0; indice < tentativas && lockPendente; indice += 1) {
    try {
      await api.lock();
      lockPendente = false;
      return;
    } catch {
      if (indice + 1 < tentativas) await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
}

function bloquearSessao() {
  lockPendente = true;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('session:locked');
  return tentarBloquear(1);
}

function registrarEnergia() {
  powerMonitor.on('lock-screen', bloquearSessao);
  powerMonitor.on('suspend', bloquearSessao);
  powerMonitor.on('resume', () => { if (lockPendente) tentarBloquear(3); });
  powerMonitor.on('unlock-screen', () => { if (lockPendente) tentarBloquear(3); });
}

function restringirCamera() {
  const permitido = (webContents, permission, details) => {
    const tipos = details?.mediaTypes || [];
    return permission === 'media' && webContents === mainWindow?.webContents &&
      tipos.includes('video') && !tipos.includes('audio');
  };
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    callback(permitido(webContents, permission, details));
  });
  session.defaultSession.setPermissionCheckHandler((webContents, permission) =>
    permission === 'media' && webContents === mainWindow?.webContents);
}

function secureLocalWindow(window, file) {
  window.webContents.on('will-navigate', (event, url) => {
    if (url !== pathToFileURL(file).href) event.preventDefault();
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
}

function orbPosFile() {
  try { return path.join(app.getPath('userData'), 'ultron-orb-pos.json'); }
  catch { return ''; }
}

function getOrbPos() {
  const area = screen.getPrimaryDisplay().workArea;
  if (!orbSavedPos) {
    try {
      const file = orbPosFile();
      if (file && fs.existsSync(file)) {
        const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (Number.isFinite(parsed?.x) && Number.isFinite(parsed?.y)) {
          orbSavedPos = { x: Math.round(parsed.x), y: Math.round(parsed.y) };
        }
      }
    } catch {}
  }
  if (!orbSavedPos) {
    orbSavedPos = {
      x: area.x + area.width - ORB_COMPACT.width - 24,
      y: Math.round(area.y + area.height * 0.42),
    };
  }
  orbSavedPos = {
    x: Math.max(area.x, Math.min(area.x + area.width - ORB_COMPACT.width, orbSavedPos.x)),
    y: Math.max(area.y, Math.min(area.y + area.height - ORB_COMPACT.height, orbSavedPos.y)),
  };
  return orbSavedPos;
}

function saveOrbPos() {
  try {
    const file = orbPosFile();
    if (file && orbSavedPos) fs.writeFileSync(file, JSON.stringify(orbSavedPos), 'utf8');
  } catch {}
}

function computeOrbLayout(expanded) {
  const area = screen.getPrimaryDisplay().workArea;
  const pos = getOrbPos();
  const centerX = pos.x + ORB_COMPACT.width / 2;
  const side = centerX > area.x + area.width / 2 ? 'left' : 'right';
  if (!expanded) {
    return {
      rect: { x: pos.x, y: pos.y, width: ORB_COMPACT.width, height: ORB_COMPACT.height },
      side,
      orbOffsetY: 0,
    };
  }
  const width = Math.min(ORB_EXPANDED.width, area.width - 16);
  const height = Math.min(ORB_EXPANDED.height, area.height - 16);
  const rawX = side === 'left' ? pos.x + ORB_COMPACT.width - width : pos.x;
  const x = Math.max(area.x + 8, Math.min(area.x + area.width - width - 8, rawX));
  const rawY = pos.y - 24;
  const y = Math.max(area.y + 8, Math.min(area.y + area.height - height - 8, rawY));
  const orbOffsetY = Math.max(0, Math.min(height - ORB_COMPACT.height, pos.y - y));
  return { rect: { x, y, width, height }, side, orbOffsetY };
}

function stopOrbTeleportTimer() {
  if (orbTeleportTimer) {
    clearInterval(orbTeleportTimer);
    orbTeleportTimer = null;
  }
  if (orbTeleportMoveTimer) {
    clearTimeout(orbTeleportMoveTimer);
    orbTeleportMoveTimer = null;
  }
  orbTeleportPhase = 'idle';
}

function podeTeleportarOrbe() {
  return Boolean(
    miniWindow &&
    !miniWindow.isDestroyed() &&
    islandStyle === 'orb' &&
    orbTeleportSec > 0 &&
    !islandExpanded &&
    !lastHudSnapshot?.fullscreen
  );
}

function executarMovimentoTeleporte() {
  orbTeleportMoveTimer = null;
  if (!podeTeleportarOrbe()) {
    orbTeleportPhase = 'idle';
    if (miniWindow && !miniWindow.isDestroyed() && lastHudSnapshot) {
      lastHudSnapshot = Object.freeze({ ...lastHudSnapshot, orbTeleportPhase: 'idle' });
      miniWindow.webContents.send('hud:snapshot', lastHudSnapshot);
    }
    return;
  }
  const area = screen.getPrimaryDisplay().workArea;
  const margin = 24;
  const minX = area.x + Math.min(margin, Math.max(0, Math.floor((area.width - ORB_COMPACT.width) / 4)));
  const maxX = Math.max(minX, area.x + area.width - ORB_COMPACT.width - margin);
  const minY = area.y + Math.min(margin, Math.max(0, Math.floor((area.height - ORB_COMPACT.height) / 4)));
  const maxY = Math.max(minY, area.y + area.height - ORB_COMPACT.height - margin);
  const prev = getOrbPos();
  let nx = prev.x;
  let ny = prev.y;
  for (let i = 0; i < 6; i++) {
    nx = Math.round(minX + Math.random() * (maxX - minX));
    ny = Math.round(minY + Math.random() * (maxY - minY));
    if (Math.hypot(nx - prev.x, ny - prev.y) >= 160) break;
  }
  orbSavedPos = { x: nx, y: ny };
  const layout = computeOrbLayout(false);
  miniWindow.setBounds(layout.rect, false);
  orbTeleportSeq += 1;
  orbTeleportPhase = 'in';
  if (lastHudSnapshot) {
    lastHudSnapshot = Object.freeze({
      ...lastHudSnapshot,
      orbSide: layout.side,
      orbOffsetY: layout.orbOffsetY,
      orbTeleportSeq,
      orbTeleportPhase: 'in',
    });
    miniWindow.webContents.send('hud:snapshot', lastHudSnapshot);
  }
}

function teleportarOrbe() {
  if (!podeTeleportarOrbe()) {
    if (!miniWindow || miniWindow.isDestroyed()) stopOrbTeleportTimer();
    return;
  }
  if (orbTeleportMoveTimer) return;
  orbTeleportOutSeq += 1;
  orbTeleportPhase = 'out';
  if (lastHudSnapshot) {
    lastHudSnapshot = Object.freeze({
      ...lastHudSnapshot,
      orbTeleportOutSeq,
      orbTeleportPhase: 'out',
    });
    miniWindow.webContents.send('hud:snapshot', lastHudSnapshot);
  }
  orbTeleportMoveTimer = setTimeout(executarMovimentoTeleporte, 185);
}

function syncOrbTeleportTimer() {
  stopOrbTeleportTimer();
  if (!miniWindow || miniWindow.isDestroyed()) return;
  if (islandStyle !== 'orb' || orbTeleportSec <= 0 || islandExpanded || lastHudSnapshot?.fullscreen) return;
  orbTeleportTimer = setInterval(teleportarOrbe, orbTeleportSec * 1000);
}

function moveOrbBy(dx, dy, commit) {
  const pos = getOrbPos();
  const area = screen.getPrimaryDisplay().workArea;
  orbSavedPos = {
    x: Math.max(area.x, Math.min(area.x + area.width - ORB_COMPACT.width, pos.x + dx)),
    y: Math.max(area.y, Math.min(area.y + area.height - ORB_COMPACT.height, pos.y + dy)),
  };
  if (commit) {
    saveOrbPos();
    syncOrbTeleportTimer();
  }
  const layout = computeOrbLayout(islandExpanded);
  if (miniWindow && !miniWindow.isDestroyed() && islandStyle === 'orb') {
    miniWindow.setBounds(layout.rect, false);
  }
  return { side: layout.side, orbOffsetY: layout.orbOffsetY };
}

function islandBounds(expanded, pos = islandPosition) {
  if (islandStyle === 'orb') {
    return computeOrbLayout(expanded).rect;
  }
  const area = screen.getPrimaryDisplay().bounds;
  const side = pos === 'right' || pos === 'left';
  const spec = expanded ? ISLAND_EXPANDED : (side ? ISLAND_COMPACT_SIDE : ISLAND_COMPACT_TOP);
  const width = Math.min(spec.width, area.width - 16);
  const height = Math.min(spec.height, area.height - 16);
  if (pos === 'right') {
    return {
      x: area.x + area.width - width,
      y: Math.round(area.y + (area.height - height) / 2),
      width,
      height,
    };
  }
  if (pos === 'left') {
    return {
      x: area.x,
      y: Math.round(area.y + (area.height - height) / 2),
      width,
      height,
    };
  }
  if (pos === 'top-left') {
    return { x: area.x + 18, y: area.y, width, height };
  }
  if (pos === 'top-right') {
    return { x: area.x + area.width - width - 18, y: area.y, width, height };
  }
  return {
    x: Math.round(area.x + (area.width - width) / 2),
    y: area.y,
    width,
    height,
  };
}

function resizeMiniWindow(expanded) {
  islandExpanded = Boolean(expanded);
  const layout = islandStyle === 'orb' ? computeOrbLayout(islandExpanded) : { side: 'left', orbOffsetY: 0 };
  if (!miniWindow || miniWindow.isDestroyed()) return { side: layout.side, orbOffsetY: layout.orbOffsetY };
  miniWindow.setBounds(islandBounds(islandExpanded, islandPosition), false);
  syncOrbTeleportTimer();
  return { side: layout.side, orbOffsetY: layout.orbOffsetY };
}

function createMiniWindow() {
  if (miniWindow && !miniWindow.isDestroyed()) {
    if (!lastHudSnapshot?.fullscreen) miniWindow.showInactive();
    return miniWindow;
  }
  const file = path.join(__dirname, 'site', 'mini-hud.html');
  islandExpanded = false;
  islandHiddenByFullscreen = false;
  const rect = islandBounds(false);
  miniWindow = new BrowserWindow({
    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
    frame: false, transparent: true, hasShadow: false, resizable: false,
    alwaysOnTop: true, skipTaskbar: true, show: false,
    backgroundColor: '#00000000', autoHideMenuBar: true,
    icon: path.join(__dirname, 'assets', 'ULTRON.ico'),
    webPreferences: { preload: path.join(__dirname, 'mini-preload.js'), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  miniWindow.setAlwaysOnTop(true, 'screen-saver');
  secureLocalWindow(miniWindow, file);
  miniWindow.on('closed', () => {
    stopOrbTeleportTimer();
    miniWindow = null;
    islandExpanded = false;
    islandHiddenByFullscreen = false;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('hud:visibility', false);
      if (!quitting && !mainWindow.isVisible()) closingFromIsland = true;
      if (!quitting && !mainWindow.isVisible()) mainWindow.close();
    }
  });
  miniWindow.loadFile(file);
  miniWindow.webContents.once('did-finish-load', () => {
    if (!miniWindow || miniWindow.isDestroyed()) return;
    if (lastHudSnapshot) miniWindow.webContents.send('hud:snapshot', lastHudSnapshot);
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('hud:visibility', true);
    if (lastHudSnapshot?.fullscreen) {
      islandHiddenByFullscreen = true;
    } else {
      miniWindow.showInactive();
    }
    syncOrbTeleportTimer();
  });
  return miniWindow;
}

// No build empacotado a interface vem de file://, então o embed do YouTube sai
// sem Referer e com origem nula; o player recusa com o erro 153. Reaplica as
// headers que o YouTube espera apenas nas requisições do embed.
function fixYoutubeEmbedHeaders() {
  session.defaultSession.webRequest.onBeforeSendHeaders(
    { urls: ['https://*.youtube.com/embed/*', 'https://*.youtube-nocookie.com/embed/*'] },
    (details, callback) => {
      const requestHeaders = { ...details.requestHeaders };
      if (!details.referrer || details.referrer.startsWith('file://')) {
        const origem = new URL(details.url).origin;
        requestHeaders.Referer = `${origem}/`;
        requestHeaders.Origin = origem;
      }
      callback({ requestHeaders });
    },
  );
}

function createWindow() {
  const indexFile = path.join(__dirname, 'site', 'index.html');
  mainWindow = new BrowserWindow({
    width: 1440, height: 900, minWidth: 980, minHeight: 640, backgroundColor: '#05070d', autoHideMenuBar: true,
    icon: path.join(__dirname, 'assets', 'ULTRON.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'), contextIsolation: true,
      sandbox: true, nodeIntegration: false, zoomFactor: 1,
    },
  });
  secureLocalWindow(mainWindow, indexFile);
  mainWindow.on('minimize', event => {
    if (!quitting) {
      event.preventDefault();
      mainWindow.hide();
      createMiniWindow();
    }
  });
  mainWindow.on('close', event => {
    if (!quitting && !closingFromIsland) {
      event.preventDefault();
      mainWindow.hide();
      createMiniWindow();
    }
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.loadFile(indexFile);
}

const gotSingleInstanceLock = app.requestSingleInstanceLock();

if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    app.setAppUserModelId('com.ultron.desktop');
    protocol.handle('ultron-palco', async request => {
      try {
        return await responderPalco(request);
      } catch {
        return new Response(null, { status: 500 });
      }
    });
    registerApiHandlers();
    fixYoutubeEmbedHeaders();
    createWindow();
    registrarEnergia();
    restringirCamera();
    app.on('before-quit', () => { quitting = true; });
    app.on('activate', () => {
      if (mainWindow && !mainWindow.isDestroyed()) { mainWindow.show(); mainWindow.focus(); }
      else createWindow();
    });
  });
}

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
