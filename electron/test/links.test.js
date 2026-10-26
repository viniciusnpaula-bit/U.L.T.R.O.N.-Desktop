const test = require('node:test');
const assert = require('node:assert/strict');
const { validarUrlExterna, ipPublico } = require('../links');

const publico = async () => [{ address: '93.184.216.34', family: 4 }];

test('aceita http/https público e normaliza a URL', async () => {
  assert.equal(await validarUrlExterna('https://example.com/arte', { lookup: publico }),
    'https://example.com/arte');
  assert.equal(await validarUrlExterna('http://example.com', { lookup: publico }),
    'http://example.com/');
  assert.equal(await validarUrlExterna('  https://example.com/a?b=1  ', { lookup: publico }),
    'https://example.com/a?b=1');
});

test('recusa esquema, credenciais e endereços locais', async () => {
  for (const url of [
    'file:///C:/Windows/win.ini',
    'javascript:alert(1)',
    'https://user:senha@example.com/x',
    'http://localhost/x',
    'http://localhost.localdomain/x',
    'http://example.local/x',
    'http://127.0.0.1/x',
    'http://[::1]/x',
    'http://10.1.2.3/x',
    'http://172.16.0.1/x',
    'http://192.168.1.10/x',
    'http://169.254.1.1/x',
    'http://100.64.0.1/x',
    'http://224.0.0.1/x',
    '',
    null,
  ]) {
    assert.equal(await validarUrlExterna(url, { lookup: publico }), null, String(url));
  }
});

test('recusa domínio que resolve para rede privada, falha ou lista vazia', async () => {
  assert.equal(await validarUrlExterna('https://example.com', {
    lookup: async () => [{ address: '10.0.0.5', family: 4 }],
  }), null);
  assert.equal(await validarUrlExterna('https://example.com', {
    lookup: async () => [
      { address: '93.184.216.34', family: 4 },
      { address: '192.168.0.5', family: 4 },
    ],
  }), null);
  assert.equal(await validarUrlExterna('https://example.com', {
    lookup: async () => { throw new Error('dns'); },
  }), null);
  assert.equal(await validarUrlExterna('https://example.com', { lookup: async () => [] }), null);
  assert.equal(await validarUrlExterna(`https://${'a'.repeat(2049)}.com`, { lookup: publico }), null);
});

test('classifica IPv4 e IPv6 públicos sem confiar no formato', () => {
  for (const endereco of ['8.8.8.8', '1.1.1.1', '172.32.0.1', '2001:4860:4860::8888']) {
    assert.equal(ipPublico(endereco), true, endereco);
  }
  for (const endereco of [
    '0.0.0.0', '10.0.0.1', '127.0.0.1', '169.254.1.1', '172.16.0.1',
    '192.168.0.1', '100.64.0.1', '224.0.0.1', '::', '::1', 'fc00::1',
    'fe80::1', 'ff02::1', 'exemplo', '999.1.1.1',
  ]) {
    assert.equal(ipPublico(endereco), false, endereco);
  }
});
