import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const site = new URL('../', import.meta.url);
const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
const css = await readFile(fileURLToPath(new URL('style.css', site)), 'utf8');

test('bate-papo: a aba existe e anuncia voz e texto', () => {
  assert.match(html, /id="chatTab"[^>]*role="tab"/s);
  assert.match(html, /aria-selected="true"[^>]*aria-controls="commsList"/);
  assert.match(html, /aria-label="Bate-papo"/);
  assert.match(html, /id="commsList"[^>]*role="tabpanel"/s);
  assert.match(html, /voz e texto · últimas 15/);
  assert.match(html, /0 mensagens/);
  // os dois lados aparecem: o usuário (voz ou escrito) e o ULTRON
  assert.match(app, /'você · escrito' : 'você · voz'/);
  assert.match(app, /turno\.role !== 'user' && turno\.role !== 'assistant'/);
  // a classe da mensagem não pode colidir com a classe do núcleo animado
  assert.match(app, /'user' : 'ultron'/);
  assert.doesNotMatch(app, /'user' : 'core'/);
  assert.match(css, /\.msg\.ultron p/);
  assert.doesNotMatch(css, /\.msg\.core/);
  // recolhida, a aba continua alcançável pelo botão do topo e por Ctrl+1
  assert.match(html, /id="toggleChat"[^>]*aria-controls="drawerChat"/s);
  assert.match(app, /\$\('toggleChat'\)\?\.addEventListener\('click', \(\) => alternarRail\('chat'\)\)/);
  assert.match(app, /alternador\.setAttribute\('aria-expanded', String\(aberto\)\)/);
  assert.match(app, /event\.ctrlKey && \(event\.key === '1' \|\| event\.key === '!'\)/);
});

test('bate-papo: interface guarda no máximo 15 mensagens', () => {
  assert.match(app, /const LIMITE_TURNOS = 15;/);
  assert.match(app, /state\.turns\.length > LIMITE_TURNOS/);
  assert.match(app, /lista\.children\.length > LIMITE_TURNOS/);
  assert.match(app, /turnos\.slice\(-LIMITE_TURNOS\)/);
  assert.match(app, /'mensagem' : 'mensagens'/);
  assert.doesNotMatch(app, /state\.turns\.length > 120|lista\.children\.length > 120/);
});

test('bate-papo: a aba ativa tem marca visual sem mudar o layout', () => {
  assert.match(css, /\.comms-tab\[aria-selected="true"\]\s*\{[^}]*color: var\(--text\)/s);
  assert.match(css, /\.comms-tab\[aria-selected="true"\]::after\s*\{[^}]*background: var\(--core\)/s);
});

test('bate-papo: limpar a sessão passa pela ponte segura', async () => {
  const preload = await readFile(fileURLToPath(new URL('../preload.js', site)), 'utf8');
  const main = await readFile(fileURLToPath(new URL('../main.js', site)), 'utf8');
  const real = await readFile(fileURLToPath(new URL('src/real.js', site)), 'utf8');
  const api = await readFile(fileURLToPath(new URL('../api.js', site)), 'utf8');
  assert.match(app, /transport\.clearConversation\(\)/);
  assert.match(real, /clearConversation\(\) \{ return this\.bridge\.clearConversation\(\); \}/);
  assert.match(preload, /clearConversation: \(\) => ipcRenderer\.invoke\('api:conversation-clear'\)/);
  assert.match(main, /'api:conversation-clear': \(\) => api\.clearConversation\(\)/);
  assert.match(api, /clearConversation: \(\) => request\('POST', '\/conversation\/clear', \{\}\)/);
});
