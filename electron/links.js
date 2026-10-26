const net = require('node:net');
const dns = require('node:dns/promises');

// O palco já valida no Python; esta é a segunda barreira, do lado do Electron.
// Ela existe para que um renderer comprometido não consiga abrir um endereço
// local nem entregar ao navegador do sistema uma URL com credenciais.
const SUFIXOS_LOCAIS = Object.freeze(['.local', '.localdomain', '.internal', '.lan', '.home', '.localhost']);

function ipv4Publico(endereco) {
  const partes = endereco.split('.').map(Number);
  if (partes.length !== 4 || partes.some(n => !Number.isInteger(n) || n < 0 || n > 255)) return false;
  const [a, b, c] = partes;
  if (a === 0 || a === 10 || a === 127) return false;
  if (a === 169 && b === 254) return false;
  if (a === 172 && b >= 16 && b <= 31) return false;
  if (a === 192 && b === 168) return false;
  if (a === 100 && b >= 64 && b <= 127) return false;        // CGNAT
  if (a === 198 && (b === 18 || b === 19)) return false;     // benchmarking
  if (a === 192 && b === 0 && c === 0) return false;
  if (a === 198 && b === 51 && c === 100) return false;
  if (a === 203 && b === 0 && c === 113) return false;
  if (a >= 224) return false;                                // multicast + reservado
  return true;
}

function ipv6Publico(endereco) {
  const valor = endereco.toLowerCase().split('%')[0];
  if (valor === '::' || valor === '::1') return false;
  if (/^f[cd]/.test(valor)) return false;                    // fc00::/7
  if (/^fe[89ab]/.test(valor)) return false;                 // fe80::/10
  if (/^ff/.test(valor)) return false;                       // multicast
  const mapeado = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(valor);
  if (mapeado) return ipv4Publico(mapeado[1]);
  return true;
}

function ipPublico(endereco) {
  const familia = net.isIP(endereco);
  if (familia === 4) return ipv4Publico(endereco);
  if (familia === 6) return ipv6Publico(endereco);
  return false;
}

async function validarUrlExterna(valor, { lookup = dns.lookup } = {}) {
  if (typeof valor !== 'string') return null;
  const bruto = valor.trim();
  if (!bruto || bruto.length > 2048) return null;

  let url;
  try { url = new URL(bruto); } catch { return null; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (url.username || url.password) return null;

  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
  if (!host) return null;
  if (host === 'localhost' || SUFIXOS_LOCAIS.some(sufixo => host.endsWith(sufixo))) return null;

  if (net.isIP(host)) {
    return ipPublico(host) ? url.href : null;
  }
  if (!/^[a-z0-9.-]+$/.test(host)) return null;

  let enderecos;
  try { enderecos = await lookup(host, { all: true, verbatim: true }); } catch { return null; }
  if (!Array.isArray(enderecos) || enderecos.length === 0) return null;
  if (enderecos.some(item => !item || !ipPublico(String(item.address || '')))) return null;
  return url.href;
}

module.exports = { validarUrlExterna, ipPublico };
