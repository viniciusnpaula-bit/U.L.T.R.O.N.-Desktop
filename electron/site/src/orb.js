// Núcleo do ULTRON: holograma em perspectiva, sem WebGL.
// Camadas: casca octaédrica → cristal geodésico → núcleo → anéis → ondas → scanlines.
// Traduz o status real em { rotulo, energia, brilho, humor, nivel, dica }.
// `humor` escolhe a animação e `nivel` é o volume do microfone já normalizado
// pelo limiar calibrado — nada aqui é inventado: se o campo não vier, é zero.
const HUMORES = ['ocioso', 'escutando', 'respondendo', 'trabalhando'];

export function normalizarHumor(valor) {
  return HUMORES.includes(valor) ? valor : 'ocioso';
}

function nivelDoMicrofone(s) {
  const nivel = Number(s?.microphone_level);
  const limiar = Number(s?.microphone_threshold);
  if (!s?.microphone_capturing || !Number.isFinite(nivel) || !Number.isFinite(limiar) || limiar <= 0) return 0;
  return Math.min(1, Math.max(0, nivel / (limiar * 1.6)));
}

export function estadoDoOrbe(s, mem, agora) {
  if (!s || s.core_running !== true) {
    return { rotulo: 'SEM NÚCLEO', dica: 'O núcleo local não respondeu. Abra pelo ULTRON.exe.', energia: 0, brilho: 0.25, humor: 'ocioso', nivel: 0 };
  }
  if (s.microphone_error) {
    return { rotulo: 'MICROFONE', dica: String(s.microphone_error).slice(0, 120), energia: 0, brilho: 0.3, humor: 'ocioso', nivel: 0 };
  }
  if (s.microphone_paused) {
    return { rotulo: 'EM SILÊNCIO', dica: 'Escuta pausada. Clique no microfone para retomar.', energia: 0, brilho: 0.35, humor: 'ocioso', nivel: 0 };
  }
  if (s.speaking) return { rotulo: 'RESPONDENDO', dica: 'O ULTRON está falando.', energia: 0.75, brilho: 1, humor: 'respondendo', nivel: 0 };
  if (s.microphone_state === 'processando') {
    return { rotulo: 'TRABALHANDO', dica: 'Executando o pedido…', energia: 0.45, brilho: 1, humor: 'trabalhando', nivel: 0 };
  }
  const limiar = Number(s.microphone_threshold) || 0;
  if (s.microphone_capturing && limiar > 0 && Number(s.microphone_level) > limiar * 0.8) mem.ateFala = agora + 700;
  const nivel = nivelDoMicrofone(s);
  if (agora < (mem.ateFala || 0)) {
    return { rotulo: 'OUVINDO VOCÊ', dica: 'Fale — estou captando sua voz.', energia: 1, brilho: 1, humor: 'escutando', nivel: Math.max(0.35, nivel) };
  }
  if (s.microphone_state === 'calibrando' || s.microphone_state === 'iniciando') {
    return { rotulo: 'CALIBRANDO', dica: 'Medindo o ruído do ambiente…', energia: 0.25, brilho: 0.7, humor: 'trabalhando', nivel: 0 };
  }
  return { rotulo: 'À ESCUTA', dica: 'Diga “Ei, Ultron” ou escreva abaixo.', energia: 0, brilho: 0.85, humor: 'ocioso', nivel };
}

const CAMERA_PADRAO = Object.freeze({ z: 7.4, foco: (45 * Math.PI) / 180 });

export function normalizarModo(modo) {
  return modo === '2d' ? '2d' : '3d';
}

// Perspectiva simples: o chamador multiplica pelo raio em pixels.
// `z` maior = mais perto da câmera = maior escala.
export function projetar(ponto, camera = CAMERA_PADRAO) {
  const z = Number.isFinite(camera?.z) ? camera.z : CAMERA_PADRAO.z;
  const foco = Number.isFinite(camera?.foco) ? camera.foco : CAMERA_PADRAO.foco;
  const profundidade = Math.max(0.15, z - (Number(ponto?.z) || 0));
  const escala = (1 / Math.tan(foco / 2)) / profundidade;
  return {
    x: (Number(ponto?.x) || 0) * escala,
    y: (Number(ponto?.y) || 0) * escala,
    escala,
    z: Number(ponto?.z) || 0,
  };
}

function icosaedro() {
  const t = (1 + Math.sqrt(5)) / 2;
  const base = [
    [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
    [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
    [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
  ];
  // as arestas são medidas na malha regular: escalar antes muda cada
  // comprimento e a regra de distância 2 não acha nenhuma aresta
  const arestas = [];
  for (let i = 0; i < base.length; i++) {
    for (let j = i + 1; j < base.length; j++) {
      const [ax, ay, az] = base[i], [bx, by, bz] = base[j];
      if (Math.abs(Math.hypot(ax - bx, ay - by, az - bz) - 2) < 0.02) arestas.push([i, j]);
    }
  }
  const vertices = base.map(([x, y, z]) => ({ x: x * 0.76, y: y * 1.2, z: z * 0.84 }));
  return { vertices, arestas };
}

export function geometriaDoCristal() {
  return icosaedro();
}

// Rotação na ordem "XYZ" do three.js (primeiro Z, depois Y, por último X).
// A ordem importa: com X antes de Y os anéis do .tsx caem em planos errados.
function girar(ponto, ax, ay, az) {
  const cx = Math.cos(ax), sx = Math.sin(ax);
  const cy = Math.cos(ay), sy = Math.sin(ay);
  const cz = Math.cos(az), sz = Math.sin(az);
  const x1 = ponto.x * cz - ponto.y * sz;
  const y1 = ponto.x * sz + ponto.y * cz;
  const z1 = ponto.z;
  const x2 = x1 * cy + z1 * sy;
  const z2 = -x1 * sy + z1 * cy;
  return { x: x2, y: y1 * cx - z2 * sx, z: y1 * sx + z2 * cx };
}

// `icosaedro()` vem de `geometriaDoCristal()`, exportado na Tarefa 4.
function octaedro(niveis = 2) {
  const vertices = [
    { x: 1, y: 0, z: 0 }, { x: -1, y: 0, z: 0 },
    { x: 0, y: 1, z: 0 }, { x: 0, y: -1, z: 0 },
    { x: 0, y: 0, z: 1 }, { x: 0, y: 0, z: -1 },
  ];
  let faces = [[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
    [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]];
  for (let n = 0; n < niveis; n++) {
    const cache = new Map();
    const proximas = [];
    const meio = (a, b) => {
      const chave = a < b ? `${a}:${b}` : `${b}:${a}`;
      if (cache.has(chave)) return cache.get(chave);
      const va = vertices[a], vb = vertices[b];
      const norma = Math.hypot((va.x + vb.x) / 2, (va.y + vb.y) / 2, (va.z + vb.z) / 2) || 1;
      vertices.push({
        x: (va.x + vb.x) / 2 / norma,
        y: (va.y + vb.y) / 2 / norma,
        z: (va.z + vb.z) / 2 / norma,
      });
      cache.set(chave, vertices.length - 1);
      return vertices.length - 1;
    };
    for (const [a, b, c] of faces) {
      const ab = meio(a, b), bc = meio(b, c), ca = meio(c, a);
      proximas.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
    }
    faces = proximas;
  }
  const vistas = new Set();
  const arestas = [];
  for (const [a, b, c] of faces) {
    for (const [i, j] of [[a, b], [b, c], [c, a]]) {
      const chave = i < j ? `${i}:${j}` : `${j}:${i}`;
      if (!vistas.has(chave)) { vistas.add(chave); arestas.push([i, j]); }
    }
  }
  return { vertices, arestas };
}

// 20 faces do icosaedro regular, na mesma numeração de `icosaedro()`.
const FACES_ICOSAEDRO = [
  [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
  [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
  [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
  [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
];

// Esfera geodésica: o icosaedro subdividido e renormalizado. As arestas são
// únicas (cada uma compartilhada por duas faces) para o wireframe não duplicar.
function geodesica(niveis = 1) {
  const t = (1 + Math.sqrt(5)) / 2;
  const normalizar = p => {
    const d = Math.hypot(p.x, p.y, p.z) || 1;
    return { x: p.x / d, y: p.y / d, z: p.z / d };
  };
  const base = [
    [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
    [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
    [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
  ].map(([x, y, z]) => normalizar({ x, y, z }));
  const vertices = base.slice();
  let faces = FACES_ICOSAEDRO.map(f => f.slice());
  for (let n = 0; n < niveis; n++) {
    const cache = new Map();
    const meio = (a, b) => {
      const chave = a < b ? `${a}:${b}` : `${b}:${a}`;
      if (cache.has(chave)) return cache.get(chave);
      const va = vertices[a], vb = vertices[b];
      vertices.push(normalizar({
        x: (va.x + vb.x) / 2, y: (va.y + vb.y) / 2, z: (va.z + vb.z) / 2,
      }));
      cache.set(chave, vertices.length - 1);
      return vertices.length - 1;
    };
    const proximas = [];
    for (const [a, b, c] of faces) {
      const ab = meio(a, b), bc = meio(b, c), ca = meio(c, a);
      proximas.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
    }
    faces = proximas;
  }
  const vistas = new Set();
  const arestas = [];
  for (const [a, b, c] of faces) {
    for (const [i, j] of [[a, b], [b, c], [c, a]]) {
      const chave = i < j ? `${i}:${j}` : `${j}:${i}`;
      if (!vistas.has(chave)) { vistas.add(chave); arestas.push([i, j]); }
    }
  }
  return { vertices, arestas };
}

const CAMERA_PADRAO = Object.freeze({ z: 7.4, foco: (45 * Math.PI) / 180 });

export function normalizarModo(modo) {
  return modo === '2d' ? '2d' : '3d';
}

// Perspectiva simples: o chamador multiplica pelo raio em pixels.
// `z` maior = mais perto da câmera = maior escala.
export function projetar(ponto, camera = CAMERA_PADRAO) {
  const z = Number.isFinite(camera?.z) ? camera.z : CAMERA_PADRAO.z;
  const foco = Number.isFinite(camera?.foco) ? camera.foco : CAMERA_PADRAO.foco;
  const profundidade = Math.max(0.15, z - (Number(ponto?.z) || 0));
  const escala = (1 / Math.tan(foco / 2)) / profundidade;
  return {
    x: (Number(ponto?.x) || 0) * escala,
    y: (Number(ponto?.y) || 0) * escala,
    escala,
    z: Number(ponto?.z) || 0,
  };
}

function icosaedro() {
  const t = (1 + Math.sqrt(5)) / 2;
  const base = [
    [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
    [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
    [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
  ];
  // as arestas são medidas na malha regular: escalar antes muda cada
  // comprimento e a regra de distância 2 não acha nenhuma aresta
  const arestas = [];
  for (let i = 0; i < base.length; i++) {
    for (let j = i + 1; j < base.length; j++) {
      const [ax, ay, az] = base[i], [bx, by, bz] = base[j];
      if (Math.abs(Math.hypot(ax - bx, ay - by, az - bz) - 2) < 0.02) arestas.push([i, j]);
    }
  }
  const vertices = base.map(([x, y, z]) => ({ x: x * 0.76, y: y * 1.2, z: z * 0.84 }));
  return { vertices, arestas };
}

export function geometriaDoCristal() {
  return icosaedro();
}

function girar(ponto, ax, ay, az) {
  const cx = Math.cos(ax), sx = Math.sin(ax);
  const cy = Math.cos(ay), sy = Math.sin(ay);
  const cz = Math.cos(az), sz = Math.sin(az);
  const y1 = ponto.y * cx - ponto.z * sx;
  const z1 = ponto.y * sx + ponto.z * cx;
  const x2 = ponto.x * cy + z1 * sy;
  const z2 = -ponto.x * sy + z1 * cy;
  return { x: x2 * cz - y1 * sz, y: x2 * sz + y1 * cz, z: z2 };
}

// `icosaedro()` vem de `geometriaDoCristal()`, exportado na Tarefa 4.
function octaedro(niveis = 2) {
  const vertices = [
    { x: 1, y: 0, z: 0 }, { x: -1, y: 0, z: 0 },
    { x: 0, y: 1, z: 0 }, { x: 0, y: -1, z: 0 },
    { x: 0, y: 0, z: 1 }, { x: 0, y: 0, z: -1 },
  ];
  let faces = [[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
    [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]];
  for (let n = 0; n < niveis; n++) {
    const cache = new Map();
    const proximas = [];
    const meio = (a, b) => {
      const chave = a < b ? `${a}:${b}` : `${b}:${a}`;
      if (cache.has(chave)) return cache.get(chave);
      const va = vertices[a], vb = vertices[b];
      const norma = Math.hypot((va.x + vb.x) / 2, (va.y + vb.y) / 2, (va.z + vb.z) / 2) || 1;
      vertices.push({
        x: (va.x + vb.x) / 2 / norma,
        y: (va.y + vb.y) / 2 / norma,
        z: (va.z + vb.z) / 2 / norma,
      });
      cache.set(chave, vertices.length - 1);
      return vertices.length - 1;
    };
    for (const [a, b, c] of faces) {
      const ab = meio(a, b), bc = meio(b, c), ca = meio(c, a);
      proximas.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
    }
    faces = proximas;
  }
  const vistas = new Set();
  const arestas = [];
  for (const [a, b, c] of faces) {
    for (const [i, j] of [[a, b], [b, c], [c, a]]) {
      const chave = i < j ? `${i}:${j}` : `${j}:${i}`;
      if (!vistas.has(chave)) { vistas.add(chave); arestas.push([i, j]); }
    }
  }
  return { vertices, arestas };
}

function toro(raio, tubo, segmentos = 64) {
  const vertices = [];
  const arestas = [];
  for (let i = 0; i < segmentos; i++) {
    const u = (i / segmentos) * Math.PI * 2;
    for (let j = 0; j < 8; j++) {
      const v = (j / 8) * Math.PI * 2;
      vertices.push({
        x: (raio + tubo * Math.cos(v)) * Math.cos(u),
        y: tubo * Math.sin(v),
        z: (raio + tubo * Math.cos(v)) * Math.sin(u),
      });
      const atual = i * 8 + j;
      arestas.push([atual, ((i + 1) % segmentos) * 8 + j]);
      if (j === 0) arestas.push([atual, i * 8 + 1]);
    }
  }
  return { vertices, arestas };
}

function hexParaHsl(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
  const n = m ? parseInt(m[1], 16) : 0xff3446;
  const r = (n >> 16 & 255) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  let h = 0;
  if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s: d ? d / (1 - Math.abs(2 * l - 1)) : 0 };
}

// Multiplicadores de animação por humor. 1 = o desenho base do holograma.
// São só números de movimento: a energia, o brilho e o nível continuam vindo
// do status real. `pulso` é a respiração; `varredura`, a velocidade da linha.
const PERFIS = {
  ocioso:      { giro: 1.00, anel: 1.0, nucleo: 1.00, bloom: 1.00, onda: 1.00, varredura: 1.0, pulso: 1.0, alfa: 1.00 },
  escutando:   { giro: 1.35, anel: 1.5, nucleo: 1.05, bloom: 1.12, onda: 1.70, varredura: 1.6, pulso: 2.2, alfa: 1.05 },
  respondendo: { giro: 1.80, anel: 2.2, nucleo: 1.18, bloom: 1.35, onda: 2.10, varredura: 1.9, pulso: 2.8, alfa: 1.12 },
  trabalhando: { giro: 2.30, anel: 3.2, nucleo: 0.64, bloom: 0.62, onda: 0.35, varredura: 2.6, pulso: 0.5, alfa: 0.92 },
};

export function criarOrbe(canvas, { modo } = {}) {
  const c = canvas.getContext('2d');
  const reduzir = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const FILAMENTOS = 4;
  const SEGMENTOS = 320;
  const filamentos = Array.from({ length: FILAMENTOS }, (_, f) => ({
    raio: 0.34 + f * 0.052,
    ondulacao: 0.035 + f * 0.011,
    // ordens de ruído diferentes por camada: nunca "pulsa em sincronia"
    k: 3 + f, m: 7 + (f % 3), p: f * 1.73, v: 0.7 + f * 0.23,
  }));
  let raf = 0, ultimo = 0, fase = 0, giro = 0, tempo = 0, energia = 0, brilho = 0.8;
  let alvo = { energia: 0, brilho: 0.8 }, cor = hexParaHsl('#ff3446'), corLida = 0;
  let w = 0, h = 0, dpr = 1;
  // Transições entre humores: cada perfil numérico e o peso de cada humor
  // chegam ao alvo exponencialmente, então nada troca de cara de um quadro
  // para o outro. `nivel` é o volume real do microfone, também amortecido.
  let humorAtual = 'ocioso', nivel = 0;
  const pesos = { ocioso: 1, escutando: 0, respondendo: 0, trabalhando: 0 };
  const suave = { ...PERFIS.ocioso };

  // Malhas construídas uma vez; o quadro só gira e projeta. O cristal é a
  // esfera geodésica do .tsx (42 vértices, 120 arestas), não mais o icosaedro
  // cru: é a densidade do wireframe que faz ler "holograma".
  const cristal = geodesica(1);
  const casca = octaedro(2);
  const aneis = [
    { raio: 1.62, ax: 0.8, ay: 0.2, vel: 0.55, alfa: 0.95, largura: 1.3, volta: 0 },
    { raio: 1.86, ax: -0.5, ay: 0.9, vel: -0.4, alfa: 0.62, largura: 1.0, volta: 0 },
    { raio: 2.06, ax: 1.2, ay: -0.6, vel: 0.28, alfa: 0.40, largura: 0.9, volta: 0 },
  ];
  const ondas = [
    { raio: 1.35, alfa: 0.20 },
    { raio: 1.73, alfa: 0.13 },
    { raio: 2.11, alfa: 0.08 },
  ];
  let modoAtual = normalizarModo(modo);
  let alvoX3d = 0, alvoY3d = 0, px3d = 0, py3d = 0;
  let rodando = false;
  const aoMover3d = evento => {
    if (reduzir || modoAtual !== '3d') return;
    const r = canvas.getBoundingClientRect();
    alvoX3d = (evento.clientX - (r.left + r.width / 2)) / Math.max(1, r.width);
    alvoY3d = (evento.clientY - (r.top + r.height / 2)) / Math.max(1, r.height);
  };
  window.addEventListener('pointermove', aoMover3d, { passive: true });
  window.addEventListener('pointerleave', () => { alvoX3d = 0; alvoY3d = 0; });

  // malhas construídas uma vez; o quadro só gira e projeta
  const cristal = geometriaDoCristal();
  const casca = octaedro(2);
  const aneisGiro = [
    { malha: toro(1.85, 0.012), ax: 0.5, ay: 0.2, az: 1.1, vel: 0.22 },
    { malha: toro(2.18, 0.010), ax: -0.9, ay: 0.6, az: 0.3, vel: -0.16 },
    { malha: toro(2.52, 0.008), ax: 0.2, ay: -1.1, az: 0.7, vel: 0.11 },
  ];
  let modoAtual = normalizarModo(modo);
  let alvoX3d = 0, alvoY3d = 0, px3d = 0, py3d = 0;
  let rodando = false;
  const aoMover3d = evento => {
    if (reduzir || modoAtual !== '3d') return;
    const r = canvas.getBoundingClientRect();
    alvoX3d = (evento.clientX - (r.left + r.width / 2)) / Math.max(1, r.width);
    alvoY3d = (evento.clientY - (r.top + r.height / 2)) / Math.max(1, r.height);
  };
  window.addEventListener('pointermove', aoMover3d, { passive: true });
  window.addEventListener('pointerleave', () => { alvoX3d = 0; alvoY3d = 0; });

  function medir() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    w = canvas.clientWidth || 320; h = canvas.clientHeight || 320;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
  }
  new ResizeObserver(medir).observe(canvas);

  function linha(raio, amplitude, t, corDaCamada, grossura, alfa) {
    c.beginPath();
    for (let i = 0; i <= SEGMENTOS; i++) {
      const a = (i / SEGMENTOS) * Math.PI * 2;
      const r = raio * (1 + amplitude * (
        Math.sin(3 * a + fase * 1.1 + t.p) * 0.6 +
        Math.sin(5 * a - fase * 0.8 + t.p * 2) * 0.3 +
        Math.sin(8 * a + fase * 1.7 + t.v) * 0.18
      ));
      const x = Math.cos(a) * r, y = Math.sin(a) * r;
      i ? c.lineTo(x, y) : c.moveTo(x, y);
    }
    c.closePath();
    c.lineWidth = grossura;
    c.strokeStyle = corDaCamada;
    c.globalAlpha = alfa;
    c.stroke();
    c.globalAlpha = 1;
  }

  // Ramo 2D: o desenho original do orbe, sem mudanças.
  function desenhar2d(R, cor, sat, luz, intensidade) {
    c.globalCompositeOperation = 'lighter';

    // 1) halo atmosférico
    const halo = c.createRadialGradient(0, 0, R * 0.1, 0, 0, R);
    halo.addColorStop(0, `hsla(${cor.h}, ${sat}%, ${luz}%, ${0.30 * intensidade})`);
    halo.addColorStop(0.42, `hsla(${cor.h}, ${sat}%, ${luz - 12}%, ${0.13 * intensidade})`);
    halo.addColorStop(1, `hsla(${cor.h}, ${sat}%, ${luz - 18}%, 0)`);
    c.fillStyle = halo;
    c.beginPath(); c.arc(0, 0, R, 0, Math.PI * 2); c.fill();

    // 2) coroa: filamentos irregulares
    c.save();
    c.rotate(giro);
    for (const f of filamentos) {
      const raio = R * f.raio * (1 + 0.03 * Math.sin(fase * 0.5 + f.p));
      linha(raio, f.ondulacao * (1 + energia * 1.6 + nivel * 1.2),
        f, `hsla(${cor.h}, ${sat}%, ${luz + 12}%, 1)`, 1.1 + energia * 0.5, 0.5 * brilho);
    }
    c.restore();

    // 3) horizonte: um anel nítido que "conserta" a instabilidade
    c.save();
    c.rotate(-giro * 0.6);
    c.beginPath(); c.arc(0, 0, R * 0.28, 0, Math.PI * 2);
    c.lineWidth = 1.6;
    c.strokeStyle = `hsla(${cor.h}, ${sat}%, ${luz + 22}%, ${0.85 * brilho})`;
    c.stroke();
    c.restore();

    // 3b) arco de instrumento: um segmento fino que gira devagar
    c.save();
    c.rotate(giro * 0.35);
    c.beginPath();
    c.arc(0, 0, R * 0.66, -0.52, 0.52);
    c.lineWidth = 1;
    c.strokeStyle = `hsla(${cor.h}, ${sat}%, ${luz + 18}%, ${0.42 * brilho})`;
    c.stroke();
    c.restore();

    // 4) pupila: luz concentrada, respira com a energia
    const pulso = 1 + 0.05 * Math.sin(fase * 1.6) + 0.12 * energia;
    const pupila = c.createRadialGradient(0, 0, 0, 0, 0, R * 0.22 * pulso);
    pupila.addColorStop(0, `hsla(${cor.h}, 30%, 96%, ${0.95 * brilho})`);
    pupila.addColorStop(0.35, `hsla(${cor.h}, ${sat}%, ${luz + 20}%, ${0.7 * brilho})`);
    pupila.addColorStop(1, `hsla(${cor.h}, ${sat}%, ${luz}%, 0)`);
    c.fillStyle = pupila;
    c.beginPath(); c.arc(0, 0, R * 0.24 * pulso, 0, Math.PI * 2); c.fill();

    c.globalCompositeOperation = 'source-over';
  }

  // Holograma em perspectiva com o mesmo enquadramento do .tsx: câmera em
  // z = 7.4, foco 45°, sem escala extra (a projeção já devolve a escala).
  // Camadas: projetor → halo → casca octaédrica → cristal geodésico →
  // núcleo → anéis giroscópicos → ondas → scanlines.
  function desenhar3d(dt, R, cor, sat, luz, intensidade) {
    if (reduzir) {
      px3d = 0; py3d = 0;
    } else {
      const amortece = 1 - Math.exp(-dt * 3);
      px3d += (alvoX3d - px3d) * amortece;
      py3d += (alvoY3d - py3d) * amortece;
    }
    const ax = py3d * 0.65;
    const ay = px3d * 0.65;
    // nenhum holograma é estável: 6% de cintilação, nunca abaixo de zero
    const tremula = 0.94 + 0.06 * Math.sin(fase * 9.7) * Math.sin(fase * 2.3 + 1.1);
    const I = Math.min(1, Math.max(0, intensidade) * tremula * 1.45 * suave.alfa);
    // batida de repouso: um pulso fundo a cada ~7 s, só no ocioso
    const batida = Math.pow(0.5 + 0.5 * Math.sin(fase * 0.85 - 1.2), 8) * pesos.ocioso;
    const R2 = R * 1.32;   // o holograma ocupa o canvas: a onda mais externa
                           // (2,11) chega a ~0,91 do raio, sem cortar as bordas
    const tinta = (t, a = 1) => `hsla(${cor.h}, ${sat}%, ${luz + t}%, ${a})`;

    const projetarPonto = (p, rx, ry, rz) => {
      const girado = girar(girar(p, rx, ry, rz), ax, ay, 0);
      const proj = projetar(girado);
      return { x: proj.x * R2, y: proj.y * R2, z: girado.z };
    };
    // 0 = fundo, 4 = frente: cada balde vira um único traço
    const balde = (z, raio, total) =>
      Math.max(0, Math.min(total - 1, Math.floor(((z / raio) + 1) / 2 * total - 1e-9)));

    // 0) nada de base sólida: o núcleo flutua, como no .tsx
    c.globalCompositeOperation = 'lighter';
    c.globalAlpha = 1;

    // 1) halo atmosférico (cresce quando a voz é captada de verdade)
    const halo = c.createRadialGradient(0, 0, R * 0.02, 0, 0, R * 0.78);
    halo.addColorStop(0, tinta(0, (0.20 + 0.12 * nivel * pesos.escutando) * I));
    halo.addColorStop(0.5, tinta(-6, 0.06 * I));
    halo.addColorStop(1, tinta(-10, 0));
    c.fillStyle = halo;
    c.beginPath(); c.arc(0, 0, R * 0.78, 0, Math.PI * 2); c.fill();

    // 2) malhas: 5 baldes de profundidade, não um traço por aresta
    const desenharMalha = (malha, { raio, rx, ry, rz, alfa, largura, bloom = 0 }) => {
      const pontos = malha.vertices.map(v => projetarPonto(
        { x: v.x * raio, y: v.y * raio, z: v.z * raio }, rx, ry, rz));
      if (bloom > 0) {
        c.strokeStyle = tinta(18);
        c.globalAlpha = bloom * I;
        c.lineWidth = 4;
        c.beginPath();
        for (const [i, j] of malha.arestas) {
          c.moveTo(pontos[i].x, pontos[i].y);
          c.lineTo(pontos[j].x, pontos[j].y);
        }
        c.stroke();
      }
      const baldes = Array.from({ length: 5 }, () => []);
      for (const [i, j] of malha.arestas) {
        baldes[balde((pontos[i].z + pontos[j].z) / 2, raio, 5)].push([i, j]);
      }
      for (let k = 0; k < 5; k++) {
        if (!baldes[k].length) continue;
        const prof = k / 4;
        c.strokeStyle = tinta(8 + 20 * prof);
        c.globalAlpha = Math.min(1, alfa * (0.18 + 1.05 * prof)) * I;
        c.lineWidth = largura * (0.5 + 0.9 * prof);
        c.beginPath();
        for (const [i, j] of baldes[k]) {
          c.moveTo(pontos[i].x, pontos[i].y);
          c.lineTo(pontos[j].x, pontos[j].y);
        }
        c.stroke();
      }
      return pontos;
    };

    const pulso = 1 + 0.03 * Math.sin(fase * 2.8) * suave.pulso + 0.10 * energia
      + 0.05 * batida + 0.04 * nivel * pesos.escutando;
    const raioCristal = 1.02 * pulso;

    // casca externa, contrarrotativa: só um sussurro de volume
    desenharMalha(casca, { raio: 1.48, rx: 0, ry: -tempo * 0.20 * suave.giro, rz: tempo * 0.15 * suave.giro, alfa: 0.16, largura: 0.7 });

    // cristal geodésico + vértices brancos (pontos de dados)
    const nos = desenharMalha(cristal, {
      raio: raioCristal, rx: tempo * 0.30 * suave.giro, ry: tempo * 0.45 * suave.giro, rz: 0,
      alfa: 1, largura: 1, bloom: 0.16,
    });
    const baldesNos = Array.from({ length: 5 }, () => []);
    for (const p of nos) baldesNos[balde(p.z, raioCristal, 5)].push(p);
    for (let k = 0; k < 5; k++) {
      if (!baldesNos[k].length) continue;
      const prof = k / 4;
      const r = 0.9 + 1.2 * prof;
      c.fillStyle = `hsla(${cor.h}, 25%, 98%, 1)`;
      c.globalAlpha = Math.min(1, 0.22 + 0.9 * prof) * I;
      c.beginPath();
      for (const p of baldesNos[k]) {
        c.moveTo(p.x + r, p.y);
        c.arc(p.x, p.y, r, 0, Math.PI * 2);
      }
      c.fill();
    }

    // 3) núcleo incandescente: a singularidade branca do .tsx, quase sempre acesa
    const escalaBase = projetar({ x: 0, y: 0, z: 0 }).escala;
    const raioNucleo = Math.max(2, escalaBase * R2 * 0.60 * suave.nucleo
      * (1 + 0.05 * Math.sin(fase * 1.7) * suave.pulso + 0.16 * energia
        + 0.10 * nivel * pesos.escutando + 0.05 * batida));

    // bloom largo por trás da esfera
    const bloomNucleo = c.createRadialGradient(0, 0, raioNucleo * 0.2, 0, 0, raioNucleo * 2.6);
    bloomNucleo.addColorStop(0, tinta(4, 0.26 * I * suave.bloom));
    bloomNucleo.addColorStop(0.45, tinta(-2, 0.10 * I * suave.bloom));
    bloomNucleo.addColorStop(1, tinta(-8, 0));
    c.fillStyle = bloomNucleo;
    c.beginPath(); c.arc(0, 0, raioNucleo * 2.6, 0, Math.PI * 2); c.fill();

    const nucleo = c.createRadialGradient(0, 0, 0, 0, 0, raioNucleo);
    nucleo.addColorStop(0, `hsla(${cor.h}, 96%, 91%, ${0.92 * Math.min(1, I * 1.3)})`);
    nucleo.addColorStop(0.45, `hsla(${cor.h}, 84%, 82%, ${0.72 * Math.min(1, I * 1.3)})`);
    nucleo.addColorStop(0.74, tinta(24, 0.30 * I));
    nucleo.addColorStop(0.91, tinta(10, 0.10 * I));
    nucleo.addColorStop(1, tinta(0, 0));
    c.fillStyle = nucleo;
    c.beginPath(); c.arc(0, 0, raioNucleo, 0, Math.PI * 2); c.fill();

    // ponto branco: quente no centro, mas sem borda de disco
    const ponto = c.createRadialGradient(0, 0, 0, 0, 0, raioNucleo * 0.36);
    ponto.addColorStop(0, `hsla(${cor.h}, 60%, 100%, ${0.78 * Math.min(1, I * 1.2)})`);
    ponto.addColorStop(0.5, `hsla(${cor.h}, 70%, 96%, ${0.28 * I})`);
    ponto.addColorStop(1, 'rgba(255, 255, 255, 0)');
    c.fillStyle = ponto;
    c.beginPath(); c.arc(0, 0, raioNucleo * 0.36, 0, Math.PI * 2); c.fill();

    // 4) anéis giroscópicos inclinados
    const SEG = 96;
    const tracar = (pontos, total, estilos) => {
      const baldes = Array.from({ length: total }, () => []);
      for (let i = 0; i < SEG; i++) {
        baldes[Math.max(0, Math.min(total - 1, Math.floor(
          ((((pontos[i].z + pontos[i + 1].z) / 2) / estilos.raio) + 1) / 2 * total - 1e-9)))].push(i);
      }
      for (let k = 0; k < total; k++) {
        if (!baldes[k].length) continue;
        const prof = k / (total - 1);
        c.strokeStyle = tinta(10 + 18 * prof);
        c.globalAlpha = Math.min(1, estilos.alfa * (0.30 + 0.95 * prof)) * I;
        c.lineWidth = estilos.largura * (0.6 + 0.9 * prof);
        c.beginPath();
        for (const i of baldes[k]) {
          c.moveTo(pontos[i].x, pontos[i].y);
          c.lineTo(pontos[i + 1].x, pontos[i + 1].y);
        }
        c.stroke();
      }
    };

    for (const anel of aneis) {
      if (!reduzir) anel.volta += anel.vel * dt * suave.anel;
      // deriva lenta do plano: é o que faz ler giroscópio, já que girar um
      // toro em torno do próprio eixo não muda nada na tela
      const rx = anel.ax + Math.sin(tempo * 0.4 + anel.raio) * 0.05;
      const ry = anel.ay + anel.volta * 0.22;
      const pontos = [];
      for (let i = 0; i <= SEG; i++) {
        const a = (i / SEG) * Math.PI * 2;
        pontos.push(projetarPonto(
          { x: Math.cos(a) * anel.raio, y: Math.sin(a) * anel.raio, z: 0 },
          rx, ry, 0));
      }
      tracar(pontos, 4, { raio: anel.raio, alfa: anel.alfa, largura: anel.largura });
    }

    // 5) ondas de ressonância: anéis que ondulam em z e giram devagar.
    //    No humor de escuta, o raio e a amplitude seguem o volume real.
    ondas.forEach((onda, idx) => {
      const reagir = nivel * pesos.escutando;
      const amp = (0.03 + energia * 0.16 + 0.10 * reagir) * suave.onda;
      const pontos = [];
      for (let i = 0; i <= SEG; i++) {
        const theta = (i / SEG) * Math.PI * 2;
        const desvio = Math.sin(theta * 6 + tempo * 3.5 + idx) * amp
          + Math.cos(theta * 4 - tempo * 2.2) * amp * 0.5;
        const r = onda.raio + desvio + 0.10 * reagir;
        const z = Math.sin(theta * 3 + tempo * 2 + idx) * 0.22;
        pontos.push(projetarPonto({ x: Math.cos(theta) * r, y: Math.sin(theta) * r, z },
          0, 0, tempo * 0.12 * (idx % 2 === 0 ? 1 : -1)));
      }
      tracar(pontos, 3, { raio: onda.raio, alfa: onda.alfa * (1 + 0.8 * reagir), largura: 0.7 });
    });

    // 5b) o que distingue cada humor além do ritmo:
    //     escuta → aro que abre com o volume; resposta → ondas que se afastam;
    //     trabalho → aro tracejado girando (leitura de "ocupado", sem %)
    const arco = (raio, de, ate, rx, ry, alfa, largura) => {
      const passos = Math.max(8, Math.round(Math.abs(ate - de) / (Math.PI * 2) * 96));
      c.beginPath();
      for (let i = 0; i <= passos; i++) {
        const a = de + (ate - de) * (i / passos);
        const p = projetarPonto({ x: Math.cos(a) * raio, y: Math.sin(a) * raio, z: 0 }, rx, ry, 0);
        i ? c.lineTo(p.x, p.y) : c.moveTo(p.x, p.y);
      }
      c.globalAlpha = Math.min(1, Math.max(0, alfa) * I);
      c.lineWidth = largura;
      c.stroke();
    };

    if (pesos.escutando > 0.02) {
      c.strokeStyle = tinta(20);
      arco(1.30 + nivel * 0.12, 0, Math.PI * 2, 0.35, 0.10,
        (0.14 + 0.55 * nivel) * pesos.escutando, 1.2);
    }

    if (pesos.respondendo > 0.02) {
      c.strokeStyle = tinta(22);
      for (let i = 0; i < 2; i++) {
        const k = (tempo * 0.55 + i * 0.5) % 1;
        arco(1.06 + k * 1.22, 0, Math.PI * 2, 0.5, 0.18,
          (1 - k) * 0.42 * pesos.respondendo, 1);
      }
    }

    if (pesos.trabalhando > 0.02) {
      c.strokeStyle = tinta(16);
      const passo = (Math.PI * 2) / 16;
      const rxTrab = 1.05 + Math.sin(tempo * 0.6) * 0.08;
      for (let i = 0; i < 16; i++) {
        const a0 = tempo * 1.9 + i * passo;
        arco(1.74, a0, a0 + passo * 0.42, rxTrab, -0.45, 0.5 * pesos.trabalhando, 1.1);
      }
    }

    // 6) scanlines e varredura: confinadas ao volume do núcleo, não à tela
    //    inteira — fora dele viram um filtro de vídeo sobre o fundo
    const raioLinhas = R * 0.54;
    c.save();
    c.beginPath(); c.arc(0, 0, raioLinhas, 0, Math.PI * 2); c.clip();
    c.strokeStyle = tinta(24);
    c.globalAlpha = 0.07 * I;
    c.lineWidth = 1;
    c.beginPath();
    for (let y = -raioLinhas; y <= raioLinhas; y += 4) { c.moveTo(-raioLinhas, y); c.lineTo(raioLinhas, y); }
    c.stroke();

    const faixa = raioLinhas * 0.34;
    const sy = -raioLinhas + ((tempo * 0.16 * suave.varredura) % 1) * 2 * raioLinhas;
    const varredura = c.createLinearGradient(0, sy - faixa, 0, sy + faixa);
    varredura.addColorStop(0, tinta(26, 0));
    varredura.addColorStop(0.5, tinta(26, 0.08 * I * Math.min(1.4, suave.varredura)));
    varredura.addColorStop(1, tinta(26, 0));
    c.globalAlpha = 1;
    c.fillStyle = varredura;
    c.fillRect(-raioLinhas, sy - faixa, 2 * raioLinhas, faixa * 2);
    c.restore();

    c.globalCompositeOperation = 'source-over';
    c.globalAlpha = 1;
  }

  function quadro(t) {
    const dt = Math.min(0.05, (t - ultimo) / 1000 || 0.016);
    ultimo = t;
    if (t - corLida > 800) {
      cor = hexParaHsl(getComputedStyle(document.documentElement).getPropertyValue('--core'));
      corLida = t;
    }
    const ataque = alvo.energia > energia;
    energia += (alvo.energia - energia) * (1 - Math.exp(-dt * (ataque ? 9 : 2.2)));
    brilho += (alvo.brilho - brilho) * (1 - Math.exp(-dt * 3.4));
    const vel = reduzir ? 0.25 : 1;
    fase += dt * (0.6 + 3.4 * energia) * vel;
    giro += dt * (0.05 + 0.55 * energia) * vel;
    tempo += dt * (0.9 + 1.6 * energia) * vel;

    humorAtual = normalizarHumor(alvo.humor);
    const alvoNivel = Math.min(1, Math.max(0, Number(alvo.nivel) || 0));
    nivel += (alvoNivel - nivel) * (1 - Math.exp(-dt * 7));
    const amorteceHumor = 1 - Math.exp(-dt * 3.2);
    for (const chave in suave) suave[chave] += (PERFIS[humorAtual][chave] - suave[chave]) * amorteceHumor;
    for (const nome in pesos) pesos[nome] += ((nome === humorAtual ? 1 : 0) - pesos[nome]) * amorteceHumor;

    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, canvas.width, canvas.height);
    c.scale(dpr, dpr);
    c.translate(w / 2, h / 2);
    const R = Math.min(w, h) * 0.5;
    const sat = 62 + 38 * energia;
    const luz = 44 + 14 * energia;
    const intensidade = (0.55 + 0.45 * energia) * brilho;

    if (modoAtual === '3d') desenhar3d(dt, R, cor, sat, luz, intensidade);
    else desenhar2d(R, cor, sat, luz, intensidade);

    raf = requestAnimationFrame(quadro);
  }

  function definirModo(novo) {
    modoAtual = normalizarModo(novo);
    alvoX3d = 0; alvoY3d = 0; px3d = 0; py3d = 0;
  }

  function aoVisibilidade() {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
    else if (rodando) { ultimo = performance.now(); raf = requestAnimationFrame(quadro); }
  }
  document.addEventListener('visibilitychange', aoVisibilidade);

  return {
    iniciar() { if (rodando) return; rodando = true; medir(); ultimo = performance.now(); raf = requestAnimationFrame(quadro); },
    parar() { rodando = false; cancelAnimationFrame(raf); raf = 0; },
    definir(e) { alvo = e; },
    definirModo,
    medir,
  };
}

// Campo estelar: poeira distante quase parada e poeira próxima com parallax.
// Deriva lenta para baixo, cintilação e nada de órbita — leitura de céu, não de sistema solar.
export function criarCampo(canvas) {
  const c = canvas.getContext('2d');
  const reduzir = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  let w = 0, h = 0, dpr = 1, raf = 0, ultimo = performance.now(), rodando = false;
  let perto = [], longe = [], cor = '#ff3446';
  let alvoX = 0, alvoY = 0, px = 0, py = 0;

  const sorte = (a, b) => a + Math.random() * (b - a);

  function medir() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    const criar = (n, rMin, rMax, aMin, aMax, pMin, pMax) => Array.from({ length: n }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      r: sorte(rMin, rMax), a: sorte(aMin, aMax),
      prof: sorte(pMin, pMax), fase: Math.random() * Math.PI * 2,
      tw: sorte(0.3, 1.2), dir: Math.random() < 0.5 ? -1 : 1,
    }));
    const area = Math.min(1.4, Math.max(0.7, (w * h) / 1100000));
    perto = criar(Math.round(110 * area), 0.8, 1.8, 0.5, 0.9, 0.8, 1);
    longe = criar(Math.round(220 * area), 0.3, 0.9, 0.15, 0.4, 0.2, 0.5);
    cor = getComputedStyle(document.documentElement).getPropertyValue('--core').trim() || '#ff3446';
  }

  function aoMover(evento) {
    if (reduzir) return;
    alvoX = (evento.clientX / Math.max(1, w) - 0.5) * 2;
    alvoY = (evento.clientY / Math.max(1, h) - 0.5) * 2;
  }
  function aoSair() { alvoX = 0; alvoY = 0; }

  function quadro(t) {
    const dt = Math.min(0.05, (t - ultimo) / 1000 || 0.016);
    ultimo = t;
    const amortece = 1 - Math.exp(-dt * 3.4);
    px += (alvoX - px) * amortece;
    py += (alvoY - py) * amortece;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, canvas.width, canvas.height);
    c.scale(dpr, dpr);

    const desenhar = (lista, corDaCamada, deriva, parallax) => {
      c.fillStyle = corDaCamada;
      for (const p of lista) {
        // deriva diagonal: cada estrela tem sua direção, então o campo nunca
        // parece uma imagem colada atrás do núcleo. Com movimento reduzido a
        // deriva continua, só que bem mais lenta (nada de paralaxe nem cintilo).
        const passo = deriva * (0.4 + p.prof) * dt * (reduzir ? 0.5 : 1);
        p.y += passo;
        p.x += passo * 0.45 * p.dir;
        if (p.y > h + 2) { p.y = -2; p.x = Math.random() * w; }
        if (p.x > w + 2) p.x = -2;
        else if (p.x < -2) p.x = w + 2;
        const ox = -px * parallax * p.prof, oy = -py * parallax * p.prof;
        c.globalAlpha = p.a * (reduzir ? 0.8 : 0.55 + 0.45 * Math.sin(t / 1000 * p.tw + p.fase));
        c.beginPath(); c.arc(p.x + ox, p.y + oy, p.r, 0, Math.PI * 2); c.fill();
      }
    };
    desenhar(longe, '#cfe0ff', 2, 8);
    desenhar(perto, cor, 5, 18);
    c.globalAlpha = 1;
    raf = requestAnimationFrame(quadro);
  }

  function aoVisibilidade() {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
    else if (rodando) { ultimo = performance.now(); raf = requestAnimationFrame(quadro); }
  }

  window.addEventListener('pointermove', aoMover, { passive: true });
  window.addEventListener('pointerleave', aoSair);
  window.addEventListener('blur', aoSair);
  window.addEventListener('resize', medir);
  document.addEventListener('visibilitychange', aoVisibilidade);
  return {
    iniciar() { if (rodando) return; rodando = true; medir(); ultimo = performance.now(); raf = requestAnimationFrame(quadro); },
    parar() { rodando = false; cancelAnimationFrame(raf); raf = 0; },
  };
}
