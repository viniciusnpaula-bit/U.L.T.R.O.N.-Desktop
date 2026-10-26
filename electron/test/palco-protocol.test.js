const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { criarRespostaPalco, lerEntradaPalco, abrirPdfPalco } = require('../palco-protocol');

const ID = 'a'.repeat(32);

function pedir(url, { method = 'GET', range } = {}) {
  const headers = new Headers();
  if (range) headers.set('range', range);
  return { url, method, headers };
}

async function montar(entrada = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ultron-palco-'));
  const dir = path.join(root, 'dados', 'palco');
  await fs.mkdir(dir, { recursive: true });
  const arquivo = path.join(root, 'clip.mp4');
  await fs.writeFile(arquivo, Buffer.from('0123456789'));
  const registro = {
    caminho: arquivo,
    tipo: 'video',
    criado: Date.now() / 1000,
    expira: Date.now() / 1000 + 60,
    ...entrada,
  };
  await fs.writeFile(path.join(dir, 'manifest.json'), JSON.stringify({ [ID]: registro }));
  return { root, dir, arquivo };
}

test('serve o arquivo local pelo id opaco com MIME e sem caminho no corpo', async () => {
  const { root } = await montar();
  try {
    const responder = criarRespostaPalco({ root });
    const resposta = await responder(pedir(`ultron-palco://media/${ID}`));
    assert.equal(resposta.status, 200);
    assert.equal(resposta.headers.get('content-type'), 'video/mp4');
    assert.equal(resposta.headers.get('accept-ranges'), 'bytes');
    assert.equal(resposta.headers.get('x-content-type-options'), 'nosniff');
    assert.equal(await resposta.text(), '0123456789');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('lê a entrada pelo id opaco sem expor o manifesto ao chamador', async () => {
  const { root, arquivo } = await montar();
  try {
    const entrada = await lerEntradaPalco(root, ID);
    assert.deepEqual(entrada, { arquivo, mime: 'video/mp4', tamanho: 10 });
    assert.equal(await lerEntradaPalco(root, 'b'.repeat(32)), null);
    assert.equal(await lerEntradaPalco(root, '../../manifest.json'), null);
    assert.equal(await lerEntradaPalco(root, ID, { agora: () => Date.now() + 120000 }), null);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
  await assert.rejects(lerEntradaPalco('relativo', ID), /absoluto/);
});

test('abre só PDF do palco e informa o resultado do visualizador', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ultron-palco-pdf-'));
  const dir = path.join(root, 'dados', 'palco');
  await fs.mkdir(dir, { recursive: true });
  const pdf = path.join(root, 'doc.pdf');
  await fs.writeFile(pdf, '%PDF-1.4');
  const expira = Date.now() / 1000 + 60;
  await fs.writeFile(path.join(dir, 'manifest.json'), JSON.stringify({ [ID]: { caminho: pdf, expira } }));
  try {
    const abertos = [];
    const abrir = async arquivo => (abertos.push(arquivo), '');
    assert.equal(await abrirPdfPalco({ root, id: ID, abrir }), true);
    assert.deepEqual(abertos, [pdf]);
    assert.equal(await abrirPdfPalco({ root, id: ID, abrir: async () => 'sem aplicativo' }), false);
    assert.equal(await abrirPdfPalco({ root, id: 'b'.repeat(32), abrir }), false);
    assert.equal(await abrirPdfPalco({ root, id: ID, abrir: async () => '', agora: () => Date.now() + 120000 }), false);
    assert.equal(await abrirPdfPalco({ root, id: ID }), false);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }

  const video = await montar();
  try {
    const abertos = [];
    const abrir = async arquivo => (abertos.push(arquivo), '');
    assert.equal(await abrirPdfPalco({ root: video.root, id: ID, abrir }), false);
    assert.deepEqual(abertos, []);
  } finally {
    await fs.rm(video.root, { recursive: true, force: true });
  }
});

test('respeita Range, sufixo e HEAD', async () => {
  const { root } = await montar();
  try {
    const responder = criarRespostaPalco({ root });
    const faixa = await responder(pedir(`ultron-palco://media/${ID}`, { range: 'bytes=2-5' }));
    assert.equal(faixa.status, 206);
    assert.equal(faixa.headers.get('content-range'), 'bytes 2-5/10');
    assert.equal(await faixa.text(), '2345');

    const sufixo = await responder(pedir(`ultron-palco://media/${ID}`, { range: 'bytes=-3' }));
    assert.equal(sufixo.status, 206);
    assert.equal(await sufixo.text(), '789');

    const cabeca = await responder(pedir(`ultron-palco://media/${ID}`, { method: 'HEAD' }));
    assert.equal(cabeca.status, 200);
    assert.equal(cabeca.headers.get('content-length'), '10');
    assert.equal(await cabeca.text(), '');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('recusa faixa impossível, id inválido, host errado e manifesto ausente', async () => {
  const { root } = await montar();
  try {
    const responder = criarRespostaPalco({ root });
    assert.equal((await responder(pedir(`ultron-palco://media/${ID}`, { range: 'bytes=20-30' }))).status, 416);
    assert.equal((await responder(pedir(`ultron-palco://media/${ID}`, { range: 'bytes=abc' }))).status, 416);
    assert.equal((await responder(pedir('ultron-palco://media/../../manifest.json'))).status, 404);
    assert.equal((await responder(pedir('ultron-palco://media/1234'))).status, 404);
    assert.equal((await responder(pedir('ultron-palco://outro/abc'))).status, 404);

    const semManifesto = await fs.mkdtemp(path.join(os.tmpdir(), 'ultron-palco-vazio-'));
    try {
      const vazio = criarRespostaPalco({ root: semManifesto });
      assert.equal((await vazio(pedir(`ultron-palco://media/${ID}`))).status, 404);
    } finally {
      await fs.rm(semManifesto, { recursive: true, force: true });
    }
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('recusa entrada expirada e extensão que não é mídia', async () => {
  const { root } = await montar({ expira: Date.now() / 1000 - 1 });
  try {
    const responder = criarRespostaPalco({ root });
    assert.equal((await responder(pedir(`ultron-palco://media/${ID}`))).status, 404);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }

  const outro = await montar();
  try {
    const texto = path.join(outro.root, 'nota.txt');
    await fs.writeFile(texto, 'segredo');
    await fs.writeFile(path.join(outro.dir, 'manifest.json'), JSON.stringify({
      [ID]: { caminho: texto, expira: Date.now() / 1000 + 60 },
    }));
    const responder = criarRespostaPalco({ root: outro.root });
    assert.equal((await responder(pedir(`ultron-palco://media/${ID}`))).status, 404);
  } finally {
    await fs.rm(outro.root, { recursive: true, force: true });
  }
});

test('só aceita raiz absoluta', () => {
  assert.throws(() => criarRespostaPalco({ root: 'relativo' }), /absoluto/);
});
