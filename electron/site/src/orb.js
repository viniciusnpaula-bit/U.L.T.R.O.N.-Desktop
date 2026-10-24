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

function hexParaHsl(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
  const n = m ? parseInt(m[1], 16) : 0xff3446;
  const r = (n >> 16 & 255) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  let h = 0;
  if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s: d ? d / (1 - Math.abs(2 * l - 1)) : 0 };
}

export function criarOrbe(canvas) {
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

  function quadro(t) {
    const dt = Math.min(0.05, (t - ultimo) / 1000 || 0.016);
    ultimo = t;
    if (t - corLida > 800) {          // a cor acompanha --core do tema
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
    raf = requestAnimationFrame(quadro);
  }

  return {
    iniciar() { if (!raf) { medir(); ultimo = performance.now(); raf = requestAnimationFrame(quadro); } },
    parar() { cancelAnimationFrame(raf); raf = 0; },
    definir(e) { alvo = e; },
    medir,
  };
}

// Campo de partículas: poeira vermelha em órbita do núcleo.
// Três profundidades orbitais + uma camada ambiente bem discreta. A energia do
// estado real (respondendo/pensando) acelera a deriva e aumenta o brilho.
export function criarCampo(canvas) {
  const c = canvas.getContext('2d');
  const reduzir = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const CAMADAS = [
    { fracao: 0.52, dist: [0.30, 0.78], tam: [0.50, 0.95], alfa: [0.12, 0.28], giro: [0.004, 0.012], deriva: [0.002, 0.006] },
    { fracao: 0.30, dist: [0.52, 1.02], tam: [0.60, 1.25], alfa: [0.18, 0.42], giro: [0.006, 0.018], deriva: [0.004, 0.012] },
    { fracao: 0.18, dist: [0.72, 1.28], tam: [1.00, 2.10], alfa: [0.30, 0.68], giro: [0.010, 0.030], deriva: [0.006, 0.020] },
  ];
  const sorte = (a, b) => a + Math.random() * (b - a);
  let w = 0, h = 0, dpr = 1, raf = 0, ultimo = performance.now();
  let orbitais = [], ambiente = [], centro = { x: 0, y: 0 }, raio = 300;
  let cor = '#ff2f42', lido = 0, energia = 0;

  function medir() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);

    const total = Math.round(Math.min(190, Math.max(90, (w * h) / 10500)));
    orbitais = [];
    for (const camada of CAMADAS) {
      const n = Math.round(total * camada.fracao);
      for (let i = 0; i < n; i++) {
        orbitais.push({
          ang: Math.random() * Math.PI * 2,
          dist: sorte(camada.dist[0], camada.dist[1]),
          r: sorte(camada.tam[0], camada.tam[1]),
          a: sorte(camada.alfa[0], camada.alfa[1]),
          giro: sorte(camada.giro[0], camada.giro[1]) * (Math.random() < 0.5 ? -1 : 1),
          deriva: sorte(camada.deriva[0], camada.deriva[1]),
          fase: Math.random() * Math.PI * 2,
          tw: sorte(0.35, 1.30),
        });
      }
    }
    ambiente = Array.from({ length: Math.round(Math.min(46, w / 26)) }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      r: sorte(0.3, 0.9), a: sorte(0.05, 0.14),
      v: sorte(0.4, 1.4), fase: Math.random() * Math.PI * 2, tw: sorte(0.2, 0.8),
    }));
    medirCentro(true);
  }

  function medirCentro(forcar) {
    const agora = performance.now();
    if (!forcar && agora - lido < 700) return;
    lido = agora;
    const alvo = document.getElementById('core');
    const r = alvo?.getBoundingClientRect();
    if (r && r.width > 40) {
      centro = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      raio = Math.max(150, Math.min(r.width, r.height) * 0.62);
    } else {
      centro = { x: w / 2, y: h * 0.45 };
      raio = Math.min(w, h) * 0.34;
    }
    const estado = document.getElementById('chamber')?.dataset.state || '';
    const alvoEnergia = /respondendo|ouvindo/.test(estado) ? 1 : /pensando/.test(estado) ? 0.55 : 0;
    energia += (alvoEnergia - energia) * 0.5;
    cor = getComputedStyle(document.documentElement).getPropertyValue('--core').trim() || '#ff2f42';
  }

  function quadro(t) {
    const dt = Math.min(0.05, (t - ultimo) / 1000 || 0.016);
    ultimo = t;
    medirCentro(false);
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, canvas.width, canvas.height);
    c.scale(dpr, dpr);
    c.fillStyle = cor;
    const vel = reduzir ? 0 : 1;

    // camada ambiente: poeira solta, quase invisível
    for (const p of ambiente) {
      if (vel) {
        p.y -= p.v * 7 * dt;
        if (p.y < -6) { p.y = h + 6; p.x = Math.random() * w; }
      }
      const cintila = reduzir ? 0.8 : 0.55 + 0.45 * Math.sin((t / 1000) * p.tw + p.fase);
      c.globalAlpha = p.a * cintila;
      c.beginPath(); c.arc(p.x, p.y, p.r, 0, Math.PI * 2); c.fill();
    }

    // camadas orbitais: densas perto do núcleo, abrindo para fora
    for (const p of orbitais) {
      if (vel) {
        p.ang += p.giro * dt * (1 + energia * 1.4);
        p.dist += p.deriva * dt * (1 + energia * 2.2);
        if (p.dist > 1.38) { p.dist = sorte(0.28, 0.52); p.ang = Math.random() * Math.PI * 2; }
      }
      const x = centro.x + Math.cos(p.ang) * p.dist * raio;
      const y = centro.y + Math.sin(p.ang) * p.dist * raio * 0.94;
      if (x < -24 || x > w + 24 || y < -24 || y > h + 24) continue;
      const cintila = reduzir ? 0.8 : 0.60 + 0.40 * Math.sin((t / 1000) * p.tw + p.fase);
      c.globalAlpha = Math.min(0.90, p.a * cintila * (1 + energia * 0.45));
      c.beginPath(); c.arc(x, y, p.r, 0, Math.PI * 2); c.fill();
      if (p.r > 1.55) {                      // brasa: halo curto, sem shadowBlur
        c.globalAlpha *= 0.16;
        c.beginPath(); c.arc(x, y, p.r * 3.1, 0, Math.PI * 2); c.fill();
      }
    }

    c.globalAlpha = 1;
    raf = requestAnimationFrame(quadro);
  }

  window.addEventListener('resize', medir);
  return {
    iniciar() { medir(); ultimo = performance.now(); raf = requestAnimationFrame(quadro); },
    parar() { cancelAnimationFrame(raf); raf = 0; },
  };
}
