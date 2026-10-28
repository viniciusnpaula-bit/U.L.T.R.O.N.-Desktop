// Núcleo do ULTRON: um sol de vento, não mais anéis girando.
// Camadas: halo pulsante → filamentos de plasma → anel de horizonte → pupila.
// Tudo em "lighter" para somar luz, e o estado real do núcleo muda a energia.
// Traduz o status do núcleo em { rotulo, energia, brilho, dica }. `mem` guarda o instante da última fala sua.
export function estadoDoOrbe(s, mem, agora) {
  if (!s || s.core_running !== true) {
    return { rotulo: 'SEM NÚCLEO', dica: 'O núcleo local não respondeu. Abra pelo ULTRON.exe.', energia: 0, brilho: 0.25 };
  }
  if (s.microphone_error) {
    return { rotulo: 'MICROFONE', dica: String(s.microphone_error).slice(0, 120), energia: 0, brilho: 0.3 };
  }
  if (s.microphone_paused) {
    return { rotulo: 'EM SILÊNCIO', dica: 'Escuta pausada. Clique no microfone para retomar.', energia: 0, brilho: 0.35 };
  }
  if (s.speaking) return { rotulo: 'RESPONDENDO', dica: 'O ULTRON está falando.', energia: 0.75, brilho: 1 };
  if (s.microphone_state === 'processando') {
    return { rotulo: 'PENSANDO', dica: 'Processando o comando…', energia: 0.45, brilho: 1 };
  }
  const limiar = Number(s.microphone_threshold) || 0;
  if (s.microphone_capturing && limiar > 0 && Number(s.microphone_level) > limiar * 0.8) mem.ateFala = agora + 700;
  if (agora < (mem.ateFala || 0)) return { rotulo: 'OUVINDO VOCÊ', dica: 'Fale — estou captando sua voz.', energia: 1, brilho: 1 };
  if (s.microphone_state === 'calibrando' || s.microphone_state === 'iniciando') {
    return { rotulo: 'CALIBRANDO', dica: 'Medindo o ruído do ambiente…', energia: 0.25, brilho: 0.7 };
  }
  return { rotulo: 'À ESCUTA', dica: 'Diga “Ei, Ultron” ou escreva abaixo.', energia: 0, brilho: 0.85 };
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
  let raf = 0, ultimo = 0, fase = 0, giro = 0, energia = 0, brilho = 0.8;
  let alvo = { energia: 0, brilho: 0.8 }, cor = hexParaHsl('#ff3446'), corLida = 0;
  let w = 0, h = 0, dpr = 1;

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
      linha(raio, f.ondulacao * (1 + energia * 1.6),
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

  // Projeção em perspectiva: glow → núcleo → malhas (casca, cristal, anéis) → anéis de onda.
  function desenhar3d(dt, R, cor, sat, luz, intensidade) {
    if (reduzir) {
      px3d = 0; py3d = 0;
    } else {
      const amortece = 1 - Math.exp(-dt * 3);
      px3d += (alvoX3d - px3d) * amortece;
      py3d += (alvoY3d - py3d) * amortece;
    }
    const ax = 0.35 + py3d * 0.6;
    const ay = (reduzir ? 0 : giro) + px3d * 0.9;

    c.globalCompositeOperation = 'lighter';

    // 1) glow
    const halo = c.createRadialGradient(0, 0, R * 0.05, 0, 0, R * 0.72);
    halo.addColorStop(0, `hsla(${cor.h}, ${sat}%, ${luz}%, ${0.30 * intensidade})`);
    halo.addColorStop(1, `hsla(${cor.h}, ${sat}%, ${luz - 12}%, 0)`);
    c.fillStyle = halo;
    c.beginPath(); c.arc(0, 0, R * 0.72, 0, Math.PI * 2); c.fill();

    // 2) esfera interna: respira com a energia
    const raioNucleo = Math.max(1, R * (0.22 + 0.05 * Math.sin(fase * 1.3) + 0.1 * energia));
    const nucleo = c.createRadialGradient(0, 0, 0, 0, 0, raioNucleo);
    nucleo.addColorStop(0, `hsla(${cor.h}, 30%, 96%, ${0.95 * intensidade})`);
    nucleo.addColorStop(0.4, `hsla(${cor.h}, ${sat}%, ${luz + 20}%, ${0.7 * intensidade})`);
    nucleo.addColorStop(1, `hsla(${cor.h}, ${sat}%, ${luz}%, 0)`);
    c.fillStyle = nucleo;
    c.beginPath(); c.arc(0, 0, raioNucleo, 0, Math.PI * 2); c.fill();

    // 3) malhas: escala projetada ~0.7×..1.4× a nominal vira 0..1
    const escalaBase = projetar({ x: 0, y: 0, z: 0 }).escala;
    const normalizar = e => Math.min(1, Math.max(0, (e / escalaBase - 0.7) / 0.7));
    const malhas = [
      { malha: casca, escala: 0.30, alfa: 0.20, anel: null },
      { malha: cristal, escala: 0.23, alfa: 0.75, anel: null },
      ...aneisGiro.map(a => ({ malha: a.malha, escala: 0.34, alfa: 1, anel: a })),
    ];
    for (const { malha, escala, alfa, anel } of malhas) {
      // com movimento reduzido os anéis ficam com ângulos fixos
      if (anel && !reduzir) anel.volta = (anel.volta || 0) + anel.vel * dt;
      const ox = ax + (anel ? anel.ax : 0);
      const oy = ay + (anel ? anel.ay : 0);
      const oz = (anel ? anel.az + (anel.volta || 0) : 0);
      const pontos = malha.vertices.map(v => {
        const p = projetar(girar(v, ox, oy, oz));
        return { x: p.x * escala * R, y: p.y * escala * R, z: p.z, escala: p.escala };
      });
      const arestas = malha.arestas
        .map(([i, j]) => ({ i, j, z: (pontos[i].z + pontos[j].z) / 2 }))
        .sort((a, b) => a.z - b.z);            // fundo primeiro
      const escalaMedia = pontos.reduce((soma, p) => soma + p.escala, 0) / pontos.length;
      const n = normalizar(escalaMedia);
      c.strokeStyle = `hsla(${cor.h}, ${sat}%, ${luz + 18}%, 1)`;
      c.globalAlpha = alfa * (0.12 + 0.58 * n);
      c.lineWidth = 0.5 + 1.1 * n;
      for (const { i, j } of arestas) {
        c.beginPath();
        c.moveTo(pontos[i].x, pontos[i].y);
        c.lineTo(pontos[j].x, pontos[j].y);
        c.stroke();
      }
    }

    // 4) anéis de onda no plano z = 0
    for (let i = 0; i < 3; i++) {
      const raio = R * (0.52 + i * 0.13) * (1 + 0.03 * Math.sin(fase + i));
      c.globalAlpha = 0.16 * intensidade;
      c.strokeStyle = `hsla(${cor.h}, ${sat}%, ${luz}%, 1)`;
      c.lineWidth = 1;
      c.save();
      c.scale(1, 0.42);
      c.beginPath(); c.arc(0, 0, raio, 0, Math.PI * 2); c.stroke();
      c.restore();
    }

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
      tw: sorte(0.3, 1.2),
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
        if (!reduzir) {
          p.y += deriva * (0.4 + p.prof) * dt;
          if (p.y > h + 2) { p.y = -2; p.x = Math.random() * w; }
        }
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
