const path = require('node:path');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const { Readable } = require('node:stream');

const PALCO_ID = /^[a-f0-9]{32}$/;
const PALCO_MIME = Object.freeze({
  '.mp4': 'video/mp4', '.webm': 'video/webm', '.mkv': 'video/x-matroska',
  '.mov': 'video/quicktime', '.m4v': 'video/x-m4v', '.ogv': 'video/ogg',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
  '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
  '.pdf': 'application/pdf',
});

function faixaInvalida(tamanho) {
  return new Response(null, {
    status: 416,
    headers: { 'Content-Range': `bytes */${tamanho}`, 'Cache-Control': 'no-store' },
  });
}

function manifestoPalco(root) {
  if (typeof root !== 'string' || !path.isAbsolute(root)) {
    throw new TypeError('A raiz do ULTRON precisa ser um caminho absoluto.');
  }
  return path.join(root, 'dados', 'palco', 'manifest.json');
}

// Lê o manifesto e devolve só o necessário para servir ou abrir a mídia. O id
// é opaco: o caminho nunca chega à interface. A mesma leitura alimenta o
// protocolo de mídia e o botão "abrir PDF", para as duas checagens não
// divergirem com o tempo.
async function lerEntradaPalco(root, id, { agora = () => Date.now() } = {}) {
  const manifesto = manifestoPalco(root);
  if (typeof id !== 'string' || !PALCO_ID.test(id)) return null;
  let dados;
  try {
    dados = JSON.parse(await fsp.readFile(manifesto, 'utf8'));
  } catch {
    return null;
  }
  if (!dados || typeof dados !== 'object' || Array.isArray(dados)) return null;
  const entrada = dados[id];
  if (!entrada || typeof entrada !== 'object' || Array.isArray(entrada)) return null;
  if (typeof entrada.caminho !== 'string' || !entrada.caminho) return null;
  const expira = Number(entrada.expira);
  if (!Number.isFinite(expira) || expira <= agora() / 1000) return null;

  const arquivo = path.resolve(entrada.caminho);
  const mime = PALCO_MIME[path.extname(arquivo).toLowerCase()];
  if (!mime) return null;
  try {
    const info = await fsp.stat(arquivo);
    if (!info.isFile()) return null;
    return { arquivo, mime, tamanho: info.size };
  } catch {
    return null;
  }
}

// Abre um PDF do palco no visualizador do sistema. A interface manda só o id;
// o caminho é resolvido aqui, no processo principal, e nunca volta para o
// renderer. Qualquer outro tipo de mídia é recusado.
async function abrirPdfPalco({ root, id, abrir, agora = () => Date.now() } = {}) {
  if (typeof abrir !== 'function') return false;
  const entrada = await lerEntradaPalco(root, id, { agora });
  if (!entrada || entrada.mime !== 'application/pdf') return false;
  return (await abrir(entrada.arquivo)) === '';
}

function criarRespostaPalco({ root, agora = () => Date.now() } = {}) {
  manifestoPalco(root);

  return async function responder(request) {
    let url;
    try { url = new URL(request.url); } catch { return new Response(null, { status: 400 }); }
    if (url.hostname !== 'media') return new Response(null, { status: 404 });
    const id = url.pathname.replace(/^\/+/, '');
    if (!id || id.includes('/')) return new Response(null, { status: 404 });

    const entrada = await lerEntradaPalco(root, id, { agora });
    if (!entrada) return new Response(null, { status: 404 });
    const { arquivo, mime, tamanho } = entrada;
    const cabecalhos = {
      'Content-Type': mime,
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'no-store',
      'Content-Disposition': 'inline',
      'X-Content-Type-Options': 'nosniff',
    };

    let inicio = 0;
    let fim = tamanho - 1;
    let status = 200;
    const faixa = request.headers.get('range');
    if (faixa) {
      const achado = /^bytes=(\d*)-(\d*)$/.exec(faixa.trim());
      if (!achado || (!achado[1] && !achado[2])) return faixaInvalida(tamanho);
      if (achado[1]) {
        inicio = Number(achado[1]);
        fim = achado[2] ? Number(achado[2]) : tamanho - 1;
      } else {
        const sufixo = Number(achado[2]);
        inicio = Math.max(0, tamanho - sufixo);
        fim = tamanho - 1;
      }
      if (!Number.isSafeInteger(inicio) || !Number.isSafeInteger(fim) ||
          inicio < 0 || inicio > fim || inicio >= tamanho) {
        return faixaInvalida(tamanho);
      }
      fim = Math.min(fim, tamanho - 1);
      status = 206;
      cabecalhos['Content-Range'] = `bytes ${inicio}-${fim}/${tamanho}`;
    }

    const comprimento = tamanho === 0 ? 0 : fim - inicio + 1;
    cabecalhos['Content-Length'] = String(comprimento);
    if (request.method === 'HEAD' || comprimento === 0) {
      return new Response(null, { status, headers: cabecalhos });
    }
    const fluxo = Readable.toWeb(fs.createReadStream(arquivo, { start: inicio, end: fim }));
    return new Response(fluxo, { status, headers: cabecalhos });
  };
}

module.exports = { criarRespostaPalco, lerEntradaPalco, abrirPdfPalco, PALCO_MIME };
