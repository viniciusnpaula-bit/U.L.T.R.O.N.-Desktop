const test = require('node:test');
const assert = require('node:assert/strict');
const { readFile } = require('node:fs/promises');
const path = require('node:path');
const { createApiClient } = require('../api');

const TOKEN = 't'.repeat(48);

test('named API actions call only the current ULTRON routes with the run token', async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return Response.json({ ok: true });
  };
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN, fetchImpl,
  });

  await api.health();
  await api.status();
  await api.events();
  await api.conversation();
  await api.clearConversation();
  await api.command('olá');
  await api.microphone(true);
  await api.confirmation('request-1', true, '1234');
  await api.emergencyStop();
  await api.palcoFechar();
  await api.unlockInfo();
  await api.unlockHello();
  await api.unlockPin('2468');
  await api.lock();
  await api.undoList();
  await api.shutdown();

  assert.deepEqual(calls.map(({ url, init }) => [url, init.method, init.body || null]), [
    ['http://127.0.0.1:43873/api/v1/health', 'GET', null],
    ['http://127.0.0.1:43873/api/v1/status', 'GET', null],
    ['http://127.0.0.1:43873/api/v1/events', 'GET', null],
    ['http://127.0.0.1:43873/api/v1/conversation', 'GET', null],
    ['http://127.0.0.1:43873/api/v1/conversation/clear', 'POST', '{}'],
    ['http://127.0.0.1:43873/api/v1/commands', 'POST', '{"text":"olá"}'],
    ['http://127.0.0.1:43873/api/v1/microphone', 'POST', '{"paused":true}'],
    ['http://127.0.0.1:43873/api/v1/confirmations', 'POST',
      '{"request_id":"request-1","approved":true,"pin":"1234"}'],
    ['http://127.0.0.1:43873/api/v1/emergency-stop', 'POST', '{}'],
    ['http://127.0.0.1:43873/api/v1/palco/fechar', 'POST', '{}'],
    ['http://127.0.0.1:43873/api/v1/unlock', 'GET', null],
    ['http://127.0.0.1:43873/api/v1/unlock', 'POST', '{"method":"hello"}'],
    ['http://127.0.0.1:43873/api/v1/unlock', 'POST', '{"method":"pin","pin":"2468"}'],
    ['http://127.0.0.1:43873/api/v1/lock', 'POST', '{}'],
    ['http://127.0.0.1:43873/api/v1/undo', 'GET', null],
    ['http://127.0.0.1:43873/api/v1/shutdown', 'POST', '{}'],
  ]);
  for (const { init } of calls) {
    assert.equal(init.headers['X-ULTRON-Token'], TOKEN);
    assert.ok(init.signal instanceof AbortSignal);
  }
  assert.equal('request' in api, false);
});

test('API client rejects non-loopback configuration and malformed inputs', async () => {
  assert.throws(() => createApiClient({ baseUrl: 'http://0.0.0.0:8000', token: TOKEN }));
  assert.throws(() => createApiClient({ baseUrl: 'http://127.0.0.1:8000', token: 'short' }));
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async () => Response.json({ ok: true }),
  });
  assert.throws(() => api.command('x'.repeat(4001)));
  assert.throws(() => api.microphone('yes'));
  assert.throws(() => api.confirmation('', true));
});

test('API transport errors never expose the run token', async () => {
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async () => { throw new Error(`connection failed: ${TOKEN}`); },
  });
  await assert.rejects(api.status(), error => !error.message.includes(TOKEN));
});

test('unlock usa o prazo longo do prompt e valida o PIN antes de enviar', async () => {
  const source = await readFile(path.join(__dirname, '..', 'api.js'), 'utf8');
  assert.match(source, /UNLOCK_TIMEOUT_MS\s*=\s*70000/);
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async () => Response.json({ ok: true }),
  });
  assert.throws(() => api.unlockPin(''));
  assert.throws(() => api.unlockPin('x'.repeat(65)));
  assert.throws(() => api.unlockPin(1234));
});

test('skills API routes use expected endpoints, token and schema validation', async () => {
  const calls = [];
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      if (url.endsWith('/skills')) {
        return Response.json({
          skills: [{ slug: 'modo-foco', nome: 'Modo foco', descricao: 'Foca no trabalho', quando: 'pedir foco', estado: 'ativo' }],
          pendentes: [{ slug: 'abrir-git', nome: 'Abrir Git', quando: 'abrir git', corpo: '1. Abrir bash' }],
        });
      }
      if (url.endsWith('/skills/approve')) {
        return Response.json({ ok: true, slug: 'abrir-git' });
      }
      return Response.json({ ok: true });
    },
  });

  const lista = await api.skillsListar();
  assert.equal(lista.skills[0].slug, 'modo-foco');
  assert.equal(lista.pendentes[0].slug, 'abrir-git');
  const aprovada = await api.skillsAprovar('abrir-git');
  assert.deepEqual(aprovada, { ok: true, slug: 'abrir-git' });
  const descartada = await api.skillsDescartar('abrir-git');
  assert.deepEqual(descartada, { ok: true });

  assert.deepEqual(calls.map(({ url, init }) => [url, init.method, init.body || null]), [
    ['http://127.0.0.1:43873/api/v1/skills', 'GET', null],
    ['http://127.0.0.1:43873/api/v1/skills/approve', 'POST', '{"nome":"abrir-git"}'],
    ['http://127.0.0.1:43873/api/v1/skills/discard', 'POST', '{"nome":"abrir-git"}'],
  ]);
  for (const { init } of calls) {
    assert.equal(init.headers['X-ULTRON-Token'], TOKEN);
    assert.ok(init.signal instanceof AbortSignal);
  }
});

test('skills API client rejects invalid slugs before calling fetch', async () => {
  let called = false;
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async () => { called = true; return Response.json({ ok: true }); },
  });

  for (const bad of ['', null, undefined, 123, '../evil', '-abc', 'AbrirGit', 'a b', 'x'.repeat(41)]) {
    await assert.rejects(() => Promise.resolve().then(() => api.skillsAprovar(bad)), /Identificador de skill inválido/);
    await assert.rejects(() => Promise.resolve().then(() => api.skillsDescartar(bad)), /Identificador de skill inválido/);
  }
  assert.equal(called, false);
});

test('skills API client rejects malformed responses, non-ok 409 conflicts, and redacts token', async () => {
  const respostasInvalidas = [
    () => Response.json(null),
    () => Response.json([]),
    () => Response.json({}),
    () => Response.json({ skills: 'nope', pendentes: [] }),
    () => Response.json({ skills: [{ slug: '../bad', nome: 'X', estado: 'ativo' }], pendentes: [] }),
    () => Response.json({ skills: [{ slug: 'ok', nome: 'X', estado: 'inventado' }], pendentes: [] }),
    () => Response.json({ skills: [], pendentes: [{ slug: 'x', nome: '' }] }),
  ];

  for (const responder of respostasInvalidas) {
    const api = createApiClient({
      baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
      fetchImpl: async () => responder(),
    });
    await assert.rejects(api.skillsListar(), /Resposta inválida da API local/);
  }

  const badApprove = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async () => Response.json({ ok: false }),
  });
  await assert.rejects(badApprove.skillsAprovar('abrir-git'), /Resposta inválida da API local/);
  await assert.rejects(badApprove.skillsDescartar('abrir-git'), /Resposta inválida da API local/);

  const conflict = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async () => new Response(JSON.stringify({ error: 'conflict', detail: 'skill pendente não encontrada: falta-x' }), { status: 409 }),
  });
  await assert.rejects(conflict.skillsAprovar('falta-x'), error =>
    error.message.startsWith('A API local recusou a solicitação (409).') && !error.message.includes(TOKEN));

  const leakyConflict = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async () => new Response(JSON.stringify({ error: 'conflict', detail: `token=${TOKEN}` }), { status: 409 }),
  });
  await assert.rejects(leakyConflict.skillsAprovar('falta-x'), error =>
    error.message === 'A API local recusou a solicitação (409).' && !error.message.includes(TOKEN));
});

test('fatosListar envia busca codificada quando presente e sem filtro quando ausente', async () => {
  const calls = [];
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return Response.json({ fatos: [], limite: 50 });
    },
  });

  await api.fatosListar();
  await api.fatosListar('');
  await api.fatosListar('   ');
  await api.fatosListar('café');
  await api.fatosListar('anotações & lembretes');

  assert.deepEqual(calls.map(c => c.url), [
    'http://127.0.0.1:43873/api/v1/fatos',
    'http://127.0.0.1:43873/api/v1/fatos',
    'http://127.0.0.1:43873/api/v1/fatos',
    'http://127.0.0.1:43873/api/v1/fatos?busca=caf%C3%A9',
    'http://127.0.0.1:43873/api/v1/fatos?busca=anota%C3%A7%C3%B5es%20%26%20lembretes',
  ]);

  assert.throws(() => api.fatosListar(123), /Termo de busca inválido/);
  assert.throws(() => api.fatosListar({}), /Termo de busca inválido/);
  assert.throws(() => api.fatosListar('a'.repeat(301)), /Termo de busca muito longo/);
});

test('rotas de pareamento mobile usam GET/POST locais esperados', async () => {
  const calls = [];
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:43873', token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, method: init.method, body: init.body || null });
      return Response.json({ ok: true, configured: true });
    },
  });

  await api.mobilePairingStatus();
  await api.mobilePairingRotate('galaxy-a34', false);
  await api.mobilePairingRevoke();

  assert.deepEqual(calls, [
    { url: 'http://127.0.0.1:43873/api/v1/mobile/pairing', method: 'GET', body: null },
    { url: 'http://127.0.0.1:43873/api/v1/mobile/pairing/rotate', method: 'POST', body: '{"killswitch_separado":false,"device_id":"galaxy-a34"}' },
    { url: 'http://127.0.0.1:43873/api/v1/mobile/pairing/revoke', method: 'POST', body: '{}' },
  ]);
});
