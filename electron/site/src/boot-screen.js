// Tela de carregamento pós-desbloqueio (exibida na janela principal após PIN/Hello).
// Controla 4 estágios reais (Núcleo, Cofre, Áudio AFE, Pronto), campo estelar e orbe 3D.

const ESTAGIOS = Object.freeze([
  {
    word: 'INICIALIZANDO',
    label: '1/4 · Núcleo Python & API local',
    hint: 'Confirmando canal com o núcleo local…',
    pct: 24,
  },
  {
    word: 'VERIFICANDO',
    label: '2/4 · Cofre cifrado & memória',
    hint: 'Carregando histórico local e diário de sessão…',
    pct: 52,
  },
  {
    word: 'CALIBRANDO',
    label: '3/4 · Audio Front-End (AEC + KWS)',
    hint: 'Aquecendo loopback WASAPI, Silero VAD e "Ei, Ultron"…',
    pct: 82,
  },
  {
    word: 'ONLINE',
    label: '4/4 · Sistemas operacionais',
    hint: 'Pronto. Diga "Ei, Ultron" ou escreva abaixo.',
    pct: 100,
  },
]);

const ESTADOS_VOZ_TERMINAIS = new Set(['ouvindo', 'capturando', 'pausado', 'desativado', 'erro']);
const ESTADOS_VOZ_AQUECENDO = new Set(['iniciando', 'aquecendo_afe', 'calibrando']);

function corHexParaRgb(hex) {
  const limpo = String(hex || '').trim().replace('#', '');
  if (/^[0-9a-fA-F]{6}$/.test(limpo)) {
    const n = parseInt(limpo, 16);
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
  }
  return '255, 52, 70';
}

function criarGeometriaIcosaedro() {
  const phi = (1 + Math.sqrt(5)) / 2;
  const verts = [
    [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
    [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
    [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1],
  ].map(([x, y, z]) => {
    const m = Math.hypot(x, y, z) || 1;
    return [x / m, y / m, z / m];
  });
  const edges = [];
  for (let i = 0; i < verts.length; i += 1) {
    for (let j = i + 1; j < verts.length; j += 1) {
      const d = Math.hypot(verts[i][0] - verts[j][0], verts[i][1] - verts[j][1], verts[i][2] - verts[j][2]);
      if (d < 1.15) edges.push([i, j]);
    }
  }
  return { verts, edges };
}

function avaliarProgresso(status, { historicoPronto = false } = {}) {
  const s = status || {};
  const estagio1 = s.api_running === true && s.core_running === true;
  const estagio2 = estagio1 && s.session_desbloqueada === true && historicoPronto === true;
  const micState = typeof s.microphone_state === 'string' ? s.microphone_state.toLowerCase() : '';
  const micIndisponivel = s.microphone_device_available === false || Boolean(s.microphone_error);
  const micAquecendo = ESTADOS_VOZ_AQUECENDO.has(micState);
  const micPronto = s.microphone_paused === true
    || ESTADOS_VOZ_TERMINAIS.has(micState)
    || (!micAquecendo && s.microphone_capturing === true)
    || micIndisponivel;
  const estagio3 = estagio2 && micPronto;

  let indice = 0;
  if (estagio3) indice = 3;
  else if (estagio2) indice = 2;
  else if (estagio1) indice = 1;

  const subs = [
    estagio1 ? 'Online' : 'Conectando',
    estagio2 ? 'Pronto' : (estagio1 ? 'Carregando' : 'Aguardando'),
    estagio3
      ? (micState === 'desativado' ? 'Desativado' : (micIndisponivel ? 'Fallback' : 'Ativo'))
      : (estagio2 ? (micState === 'aquecendo_afe' ? 'Aquecendo AFE' : 'Calibrando') : 'Aguardando'),
    estagio3 ? 'Pronto' : 'Aguardando',
  ];

  return { indice, estagio1, estagio2, estagio3, subs };
}

export function criarTelaCarregamento({
  doc = typeof document !== 'undefined' ? document : null,
  aoConcluir = () => {},
  aoTentarNovamente = () => {},
  agoraMs = () => Date.now(),
  duracaoMinMs = 900,
  fadeMs = 280,
  timeoutMs = 12000,
} = {}) {
  const el = id => doc?.getElementById?.(id) || null;
  const overlay = el('bootOverlay');
  const stage = el('stage');
  const starsCanvas = el('bootStarsCanvas');
  const orbCanvas = el('bootOrbCanvas');
  const timerEl = el('bootTimer');
  const wordEl = el('bootStateWord');
  const hintEl = el('bootStateHint');
  const stageLabelEl = el('bootStageLabel');
  const pctEl = el('bootPctLabel');
  const fillEl = el('bootProgressFill');
  const sweepEl = el('bootProgressSweep');
  const errorBar = el('bootErrorBar');
  const errorText = el('bootErrorText');
  const retryBtn = el('bootRetryBtn');
  const bypassBtn = el('bootBypassBtn');
  const cards = [...(doc?.querySelectorAll?.('.boot-stage-card') || [])];

  let estado = 'idle'; // idle | booting | error | completing
  let inicioMs = 0;
  let prazoMs = 0;
  let indiceAtual = 0;
  let ultimoStatus = null;
  let ultimoExtras = { historicoPronto: false };
  let timerConcluir = null;
  let timerFade = null;
  let timerRelogio = null;
  let rafId = null;
  let tempoAnim = 0;

  const geo = criarGeometriaIcosaedro();
  const stars = Array.from({ length: 48 }, (_, i) => ({
    x: ((i * 73) % 100) / 100,
    y: ((i * 37) % 100) / 100,
    r: 0.4 + (i % 3) * 0.35,
    a: 0.18 + (i % 4) * 0.12,
    sp: 0.00018 + (i % 5) * 0.00006,
  }));

  function movimentoReduzido() {
    try {
      return typeof window !== 'undefined'
        && window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true;
    } catch {
      return false;
    }
  }

  function rgbTema() {
    try {
      if (typeof window !== 'undefined' && doc?.documentElement) {
        const val = window.getComputedStyle(doc.documentElement).getPropertyValue('--core');
        if (val) return corHexParaRgb(val);
      }
    } catch { /* fallback */ }
    return '255, 52, 70';
  }

  function limparTimers() {
    if (timerConcluir) { clearTimeout(timerConcluir); timerConcluir = null; }
    if (timerFade) { clearTimeout(timerFade); timerFade = null; }
    if (timerRelogio) { clearInterval(timerRelogio); timerRelogio = null; }
    if (rafId && typeof cancelAnimationFrame === 'function') {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  function atualizarCronometro() {
    if (!timerEl || estado === 'idle') return;
    const decorrido = Math.max(0, (agoraMs() - inicioMs) / 1000);
    timerEl.textContent = `${decorrido.toFixed(1)}s`;
  }

  function renderizarEstado(indice, subs, emErro = false, podePular = false) {
    indiceAtual = indice;
    const info = ESTAGIOS[indice];
    if (overlay) {
      overlay.dataset.bootState = emErro ? 'error' : (indice === 3 ? 'done' : 'loading');
    }
    if (errorBar) errorBar.hidden = !emErro;
    if (bypassBtn) bypassBtn.hidden = !(emErro && podePular);
    if (sweepEl) sweepEl.hidden = emErro || info.pct >= 100;

    if (wordEl) wordEl.textContent = emErro ? 'FALHA DE CANAL' : info.word;
    if (hintEl) {
      hintEl.textContent = emErro
        ? 'Tempo limite excedido aguardando resposta do núcleo ou áudio.'
        : info.hint;
    }
    if (errorText && emErro) {
      errorText.textContent = podePular
        ? 'O Audio Front-End demorou para responder. Você pode tentar de novo ou entrar por texto.'
        : 'O núcleo local demorou para responder na porta interna.';
    }
    if (stageLabelEl) stageLabelEl.textContent = info.label;
    if (pctEl) pctEl.textContent = `${info.pct}%`;
    if (fillEl) fillEl.style.width = `${info.pct}%`;

    cards.forEach((card, i) => {
      const sub = card.querySelector?.('.boot-stage-sub');
      if (sub && subs[i] !== undefined) sub.textContent = subs[i];
      card.classList?.toggle?.('is-done', !emErro && (i < indice || indice === 3));
      card.classList?.toggle?.('is-active', !emErro && i === indice && indice < 3);
      card.classList?.toggle?.('is-error', emErro && i === indice);
    });
  }

  function desenharFrame() {
    if (estado === 'idle') return;
    const reduzido = movimentoReduzido();
    tempoAnim += reduzido ? 0.004 : 0.016;
    const rgb = estado === 'error'
      ? '255, 92, 92'
      : (indiceAtual === 3 ? '69, 214, 162' : rgbTema());

    if (starsCanvas?.getContext) {
      const sctx = starsCanvas.getContext('2d');
      if (sctx) {
        const w = starsCanvas.width || 640;
        const h = starsCanvas.height || 360;
        sctx.clearRect(0, 0, w, h);
        for (const st of stars) {
          if (!reduzido) {
            st.y -= st.sp;
            if (st.y < 0) st.y = 1;
          }
          sctx.fillStyle = `rgba(220, 230, 255, ${st.a})`;
          sctx.beginPath();
          sctx.arc(st.x * w, st.y * h, st.r, 0, Math.PI * 2);
          sctx.fill();
        }
      }
    }

    if (orbCanvas?.getContext) {
      const ctx = orbCanvas.getContext('2d');
      if (ctx) {
        const w = orbCanvas.width || 168;
        const h = orbCanvas.height || 168;
        const cx = w / 2;
        const cy = h / 2;
        ctx.clearRect(0, 0, w, h);

        const grad = ctx.createRadialGradient(cx, cy, 2, cx, cy, 58);
        grad.addColorStop(0, `rgba(${rgb}, 0.34)`);
        grad.addColorStop(0.55, `rgba(${rgb}, 0.09)`);
        grad.addColorStop(1, `rgba(${rgb}, 0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(cx, cy, 58, 0, Math.PI * 2);
        ctx.fill();

        const vel = indiceAtual === 3 ? 0.55 : 1.1;
        const ay = tempoAnim * vel;
        const ax = Math.sin(tempoAnim * 0.7) * 0.45;
        const cy1 = Math.cos(ay), sy1 = Math.sin(ay);
        const cx1 = Math.cos(ax), sx1 = Math.sin(ax);
        const radius = 36 * (reduzido ? 1 : (1 + Math.sin(tempoAnim * 3.0) * 0.035));

        const proj = geo.verts.map(([vx, vy, vz]) => {
          const x1 = vx * cy1 + vz * sy1;
          const z1 = -vx * sy1 + vz * cy1;
          const y2 = vy * cx1 - z1 * sx1;
          const z2 = vy * sx1 + z1 * cx1;
          const scale = 3.2 / (3.2 - z2);
          return { x: cx + x1 * radius * scale, y: cy + y2 * radius * scale, z: z2 };
        });

        ctx.lineWidth = 1.15;
        for (const [a, b] of geo.edges) {
          const pa = proj[a];
          const pb = proj[b];
          const alpha = 0.28 + ((pa.z + pb.z + 2) / 4) * 0.62;
          ctx.strokeStyle = `rgba(${rgb}, ${alpha.toFixed(2)})`;
          ctx.beginPath();
          ctx.moveTo(pa.x, pa.y);
          ctx.lineTo(pb.x, pb.y);
          ctx.stroke();
        }

        ctx.fillStyle = `rgba(${rgb}, 0.92)`;
        ctx.beginPath();
        ctx.arc(cx, cy, 3.2, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    if (typeof requestAnimationFrame === 'function' && estado !== 'idle') {
      rafId = requestAnimationFrame(desenharFrame);
    }
  }

  function encerrarComSucesso() {
    if (estado === 'idle') return;
    estado = 'idle';
    limparTimers();
    if (overlay) {
      overlay.classList?.remove?.('is-fading');
      overlay.hidden = true;
    }
    if (stage) stage.inert = false;
    aoConcluir();
  }

  function agendarConclusao() {
    if (estado === 'completing' || estado === 'idle') return;
    estado = 'completing';
    const restante = Math.max(0, (inicioMs + duracaoMinMs) - agoraMs());
    const esperaOnline = restante + 320;
    timerConcluir = setTimeout(() => {
      if (estado !== 'completing') return;
      if (fadeMs > 0 && overlay) {
        overlay.classList?.add?.('is-fading');
        timerFade = setTimeout(encerrarComSucesso, fadeMs);
      } else {
        encerrarComSucesso();
      }
    }, esperaOnline);
  }

  function iniciar() {
    limparTimers();
    estado = 'booting';
    inicioMs = agoraMs();
    prazoMs = inicioMs + timeoutMs;
    if (overlay) {
      overlay.classList?.remove?.('is-fading');
      overlay.hidden = false;
    }
    if (stage) stage.inert = true;
    renderizarEstado(0, ['Conectando', 'Aguardando', 'Aguardando', 'Aguardando'], false, false);
    atualizarCronometro();
    timerRelogio = setInterval(atualizarCronometro, 100);
    if (typeof requestAnimationFrame === 'function') {
      rafId = requestAnimationFrame(desenharFrame);
    }
  }

  function atualizar(status, extras = {}) {
    if (estado !== 'booting' && estado !== 'error') return;
    ultimoStatus = status;
    ultimoExtras = extras;
    atualizarCronometro();

    const prog = avaliarProgresso(status, extras);
    if (prog.estagio3) {
      renderizarEstado(3, prog.subs, false, false);
      agendarConclusao();
      return;
    }

    if (agoraMs() >= prazoMs) {
      estado = 'error';
      renderizarEstado(prog.indice, prog.subs, true, prog.estagio2);
      return;
    }

    if (estado === 'error') estado = 'booting';
    renderizarEstado(prog.indice, prog.subs, false, false);
  }

  function cancelar() {
    if (estado === 'idle') return;
    estado = 'idle';
    limparTimers();
    if (overlay) {
      overlay.classList?.remove?.('is-fading');
      overlay.hidden = true;
    }
    if (stage) stage.inert = false;
  }

  function tentarNovamente() {
    if (estado === 'idle') return;
    estado = 'booting';
    prazoMs = agoraMs() + timeoutMs;
    const prog = avaliarProgresso(ultimoStatus, ultimoExtras);
    renderizarEstado(prog.indice, prog.subs, false, false);
    aoTentarNovamente();
  }

  function entrarMesmoAssim() {
    if (estado === 'idle') return;
    encerrarComSucesso();
  }

  retryBtn?.addEventListener?.('click', tentarNovamente);
  bypassBtn?.addEventListener?.('click', entrarMesmoAssim);

  function destruir() {
    cancelar();
    retryBtn?.removeEventListener?.('click', tentarNovamente);
    bypassBtn?.removeEventListener?.('click', entrarMesmoAssim);
  }

  return Object.freeze({
    iniciar,
    atualizar,
    cancelar,
    destruir,
    ativa: () => estado !== 'idle',
  });
}
