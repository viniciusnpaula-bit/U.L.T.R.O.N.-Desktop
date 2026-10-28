const MENSAGENS = {
  hello_unavailable: 'Windows Hello indisponível neste PC.',
  not_verified: 'Não foi possível verificar. Tente de novo ou use o PIN.',
  busy: 'Já existe uma verificação do Windows Hello em andamento.',
  pin_invalid: 'PIN incorreto.',
  no_method_configured: 'Nenhum método configurado: defina ULTRON_PIN ou use o Windows Hello.',
  too_many_attempts: 'Muitas tentativas. Aguarde 30 segundos.',
};

const MOTIVOS_CAMERA = {
  NotAllowedError: 'Permissão da câmera negada',
  NotFoundError: 'Nenhuma câmera encontrada',
  NotReadableError: 'Câmera em uso por outro app',
};

export function motivoCamera(erro) {
  return MOTIVOS_CAMERA[erro?.name] || 'Câmera indisponível';
}

export function criarDesbloqueio({ transport, aoMudarSessao = () => {},
  doc = document, midia = navigator.mediaDevices } = {}) {
  const el = id => doc.getElementById(id);
  const overlay = el('unlock');
  const stage = el('stage');
  const video = el('unlockCameraVideo');
  const status = el('unlockStatus');
  const pin = el('unlockPin');
  const pinBlock = el('unlockPinBlock');
  const helloBtn = el('unlockHello');
  const laterBtn = el('unlockLater');
  const log = el('unlockLog');
  let sessao = null;
  let stream = null;
  let aberto = false;
  const tentativas = [];

  function escrever(id, texto) {
    const alvo = el(id);
    if (alvo) alvo.textContent = texto;
  }

  function pararCamera() {
    for (const faixa of stream?.getTracks?.() || []) faixa.stop();
    stream = null;
    if (video) video.srcObject = null;
    escrever('unlockCameraState', 'desligada');
  }

  async function ligarCamera() {
    if (stream) return;
    if (!midia?.getUserMedia) {
      escrever('unlockCameraState', 'indisponível');
      return;
    }
    escrever('unlockCameraState', 'iniciando');
    try {
      stream = await midia.getUserMedia({ video: true, audio: false });
      if (!aberto) { pararCamera(); return; }
      if (video) {
        video.srcObject = stream;
        const promessa = video.play?.();
        if (promessa?.catch) promessa.catch(() => {});
      }
      escrever('unlockCameraState', 'ativa');
    } catch (erro) {
      const motivo = motivoCamera(erro);
      escrever('unlockCameraState', motivo);
      escrever('unlockCameraError', motivo);
    }
  }

  function renderInfo(info) {
    const hello = info?.hello || {};
    escrever('unlockHelloState', hello.disponivel ? 'disponível' : (hello.motivo || 'indisponível'));
    escrever('unlockPinState', info?.pin_configurado ? 'configurado' : 'não configurado');
    if (pinBlock) pinBlock.hidden = !info?.pin_configurado;
    if (helloBtn) helloBtn.disabled = !hello.disponivel;
    escrever('unlockIrreversiveis', (info?.irreversiveis || []).join(', ') || 'nenhuma');
    escrever('unlockHistorico', info?.historico
      ? `AES-256-GCM · ${info.historico.chave === 'indisponivel' ? 'chave indisponível' : 'cifrado'}`
      : 'histórico local');
    escrever('unlockVersion', info?.versao || '—');
    escrever('unlockSession', info?.session?.desbloqueada
      ? `liberado via ${info.session.metodo}` : 'bloqueado');
  }

  function focar() {
    if (pinBlock && !pinBlock.hidden && pin) pin.focus();
    else if (helloBtn && !helloBtn.disabled) helloBtn.focus();
    else laterBtn?.focus();
  }

  async function abrir() {
    aberto = true;
    if (overlay) overlay.hidden = false;
    if (stage) stage.inert = true;
    if (status) status.textContent = 'Aguardando autorização local.';
    try { renderInfo(await transport.unlockInfo()); } catch { /* mantém os padrões */ }
    if (!aberto) return;
    ligarCamera();
    focar();
  }

  function esconder() {
    aberto = false;
    if (overlay) overlay.hidden = true;
    if (stage) stage.inert = false;
    pararCamera();
  }

  function definirSessao(desbloqueada) {
    const anterior = sessao;
    sessao = desbloqueada === true;
    if (sessao) { esconder(); return; }
    if (anterior === true) abrir();       // só na transição liberado -> bloqueado
  }

  function registrar(metodo, resultado) {
    tentativas.unshift({ hora: new Date().toLocaleTimeString('pt-BR'), metodo, resultado });
    tentativas.length = Math.min(tentativas.length, 5);
    if (!log) return;
    log.replaceChildren(...tentativas.map(item => {
      const linha = doc.createElement('li');
      linha.textContent = `${item.hora} · ${item.metodo} · ${item.resultado}`;
      return linha;
    }));
  }

  async function tentarHello() {
    if (!helloBtn) return;
    helloBtn.disabled = true;
    if (status) status.textContent = 'VERIFICANDO…';
    pararCamera();                        // o prompt do Windows pode disputar a câmera
    let resultado;
    try { resultado = await transport.unlockHello(); }
    catch { resultado = { unlocked: false, error: 'hello_unavailable' }; }
    if (resultado?.unlocked) {
      registrar('hello', 'liberado');
      sessao = true;
      esconder();
      aoMudarSessao(true);
      return;
    }
    registrar('hello', resultado?.error || 'falhou');
    if (status) status.textContent = MENSAGENS[resultado?.error] || 'Não foi possível desbloquear.';
    helloBtn.disabled = false;
    ligarCamera();
  }

  async function tentarPin(evento) {
    evento?.preventDefault?.();
    const valor = String(pin?.value || '');
    if (!valor) return;
    if (status) status.textContent = 'VERIFICANDO…';
    let resultado;
    try { resultado = await transport.unlockPin(valor); }
    catch { resultado = { unlocked: false, error: 'pin_invalid' }; }
    if (pin) pin.value = '';
    if (resultado?.unlocked) {
      registrar('pin', 'liberado');
      sessao = true;
      esconder();
      aoMudarSessao(true);
      return;
    }
    registrar('pin', resultado?.error || 'falhou');
    if (status) status.textContent = MENSAGENS[resultado?.error] || 'Não foi possível desbloquear.';
    pin?.focus();
  }

  helloBtn?.addEventListener('click', tentarHello);
  el('unlockPinForm')?.addEventListener('submit', tentarPin);
  laterBtn?.addEventListener('click', esconder);

  return Object.freeze({ abrir, definirSessao, parar: pararCamera });
}
