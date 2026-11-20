const API_PREFIX = '/api/v1';
const REQUEST_TIMEOUT_MS = 12000;
const UNLOCK_TIMEOUT_MS = 70000;
const MAX_COMMAND_LENGTH = 4000;
const FLUXO_ID_RE = /^[a-z0-9][a-z0-9._-]{0,39}$/;
const OPERATION_ID_RE = /^[a-f0-9]{32}$/;
const SKILL_SLUG_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const SKILL_ESTADOS = new Set(['ativo', 'obsoleto', 'arquivado']);
const SAFE_CONFLICT_RE = /^(skill pendente não encontrada: [a-z0-9-]+|já existe skill com esse nome: [a-z0-9-]+|limite de \d+ skills ativas:.*|nome de skill inválido|fila de skills cheia:.*)$/i;

function assertWorkflowId(id) {
  if (typeof id !== 'string' || !FLUXO_ID_RE.test(id)) {
    throw new TypeError('Identificador de fluxo inválido.');
  }
  return id;
}

function assertSkillSlug(nome) {
  if (typeof nome !== 'string' || !SKILL_SLUG_RE.test(nome)) {
    throw new TypeError('Identificador de skill inválido.');
  }
  return nome;
}

function assertPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Resposta inválida da API local.');
  }
  return value;
}

function assertSkillsPayload(data) {
  const payload = assertPlainObject(data);
  if (!Array.isArray(payload.skills) || !Array.isArray(payload.pendentes)) {
    throw new Error('Resposta inválida da API local.');
  }
  for (const s of payload.skills) {
    if (!s || typeof s !== 'object' || Array.isArray(s) ||
        typeof s.slug !== 'string' || !SKILL_SLUG_RE.test(s.slug) ||
        typeof s.nome !== 'string' || !s.nome.trim() ||
        typeof s.estado !== 'string' || !SKILL_ESTADOS.has(s.estado) ||
        (s.descricao !== undefined && typeof s.descricao !== 'string') ||
        (s.quando !== undefined && typeof s.quando !== 'string')) {
      throw new Error('Resposta inválida da API local.');
    }
  }
  for (const p of payload.pendentes) {
    if (!p || typeof p !== 'object' || Array.isArray(p) ||
        typeof p.slug !== 'string' || !SKILL_SLUG_RE.test(p.slug) ||
        typeof p.nome !== 'string' || !p.nome.trim() ||
        (p.descricao !== undefined && typeof p.descricao !== 'string') ||
        (p.quando !== undefined && typeof p.quando !== 'string') ||
        (p.corpo !== undefined && typeof p.corpo !== 'string')) {
      throw new Error('Resposta inválida da API local.');
    }
  }
  return payload;
}

function createApiClient({ baseUrl, token, fetchImpl = fetch }) {
  let url;
  try {
    url = new URL(baseUrl);
  } catch {
    throw new TypeError('URL da API local inválida.');
  }
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new TypeError('A API do ULTRON deve usar uma URL local válida.');
  }
  if (typeof token !== 'string' || token.length < 32 || typeof fetchImpl !== 'function') {
    throw new TypeError('Configuração da API local inválida.');
  }
  const origin = url.origin;

  async function request(method, route, data, timeoutMs = REQUEST_TIMEOUT_MS) {
    const controller = new AbortController();
    const headers = { Accept: 'application/json', 'X-ULTRON-Token': token };
    const init = { method, headers, signal: controller.signal };
    if (data !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(data);
    }
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(`${origin}${API_PREFIX}${route}`, init);
      const raw = await response.text();
      let result;
      try {
        result = raw ? JSON.parse(raw) : {};
      } catch {
        throw new Error('Resposta inválida da API local.');
      }
      if (!response.ok) {
        let suffix = '';
        if (response.status === 409 && result && result.error === 'conflict' &&
            typeof result.detail === 'string' && !result.detail.includes(token) &&
            SAFE_CONFLICT_RE.test(result.detail.trim())) {
          suffix = ` ${result.detail.trim().slice(0, 120)}`;
        }
        throw new Error(`A API local recusou a solicitação (${response.status}).${suffix}`);
      }
      return result;
    } catch (error) {
      if (error.message.startsWith('A API local recusou') ||
          error.message === 'Resposta inválida da API local.') throw error;
      if (error.name === 'AbortError') throw new Error('Tempo limite da API local excedido.');
      throw new Error('Não foi possível conectar à API local.');
    } finally {
      clearTimeout(timer);
    }
  }

  return Object.freeze({
    health: () => request('GET', '/health'),
    unlockInfo: () => request('GET', '/unlock'),
    unlockHello: () => request('POST', '/unlock', { method: 'hello' }, UNLOCK_TIMEOUT_MS),
    unlockPin: pin => {
      if (typeof pin !== 'string' || pin.length < 1 || pin.length > 64) {
        throw new TypeError('O PIN deve conter de 1 a 64 caracteres.');
      }
      return request('POST', '/unlock', { method: 'pin', pin }, UNLOCK_TIMEOUT_MS);
    },
    lock: () => request('POST', '/lock', {}),
    status: () => request('GET', '/status'),
    events: () => request('GET', '/events'),
    cofreStatus: () => request('GET', '/cofre'),
    cofreGuardar: (nome, valor) => request('POST', '/cofre', { nome: String(nome), valor: String(valor) }),
    cofreRemover: nome => request('POST', '/cofre/remover', { nome: String(nome) }),
    cofreTestar: nome => request('POST', '/cofre/testar', { nome: String(nome) }),
    fatosListar: busca => {
      if (busca !== undefined && busca !== null && typeof busca !== 'string') {
        throw new TypeError('Termo de busca inválido.');
      }
      if (typeof busca === 'string' && busca.length > 300) {
        throw new TypeError('Termo de busca muito longo.');
      }
      const termo = typeof busca === 'string' ? busca.trim() : '';
      return request('GET', '/fatos' + (termo ? `?busca=${encodeURIComponent(termo)}` : ''));
    },
    fatoCorrigir: (id, texto) => request('POST', '/fatos', { id, texto: String(texto || '') }),
    fatoApagar: id => request('POST', '/fatos', { id }),
    lembreteCancelar: (numero, trecho) => request('POST', '/lembretes/cancelar',
      numero == null ? { trecho: String(trecho || '') } : { numero }),
    agendaListar: () => request('GET', '/agenda'),
    agendaCancelar: (numero, trecho) => request('POST', '/agenda/cancelar',
      numero == null ? { trecho: String(trecho || '') } : { numero }),
    fluxosListar: () => request('GET', '/fluxos'),
    executarFluxo: async id => {
      const workflowId = assertWorkflowId(id);
      const result = assertPlainObject(await request('POST', '/fluxos/executar', { id: workflowId }));
      if (typeof result.operation_id !== 'string' || !OPERATION_ID_RE.test(result.operation_id)) {
        throw new Error('Resposta inválida da API local.');
      }
      return result;
    },
    skillsListar: async () => assertSkillsPayload(await request('GET', '/skills')),
    skillsAprovar: async nome => {
      const slug = assertSkillSlug(nome);
      const result = assertPlainObject(await request('POST', '/skills/approve', { nome: slug }));
      if (result.ok !== true || typeof result.slug !== 'string' || !SKILL_SLUG_RE.test(result.slug)) {
        throw new Error('Resposta inválida da API local.');
      }
      return result;
    },
    skillsDescartar: async nome => {
      const slug = assertSkillSlug(nome);
      const result = assertPlainObject(await request('POST', '/skills/discard', { nome: slug }));
      if (result.ok !== true) {
        throw new Error('Resposta inválida da API local.');
      }
      return result;
    },
    lembretesListar: () => request('GET', '/lembretes'),
    vozInfo: () => request('GET', '/voz'),
    vozSalvar: valores => request('POST', '/voz', valores || {}),
    vozRestaurar: () => request('POST', '/voz/restaurar', {}),
    vozTestar: texto => request('POST', '/voz/testar', { texto: String(texto || '') }),
    microfoneTestar: () => request('POST', '/microfone/testar', {}),
    personalidadeInfo: () => request('GET', '/personalidade'),
    personalidadeSalvar: valores => request('POST', '/personalidade', valores || {}),
    personalidadeRestaurar: () => request('POST', '/personalidade/restaurar', {}),
    personalidadePrevia: () => request('GET', '/personalidade/previa'),
    updateInfo: () => request('GET', '/update'),
    updateCheck: () => request('GET', '/update/check'),
    updateApply: restartAfter => request('POST', '/update/apply', { restart_after: restartAfter === true }),
    updateLaunch: () => request('POST', '/update/launch', {}),
    updateRollback: () => request('POST', '/update/rollback', {}),
    undoList: () => request('GET', '/undo'),
    command: text => {
      if (typeof text !== 'string' || !text.trim() || text.length > MAX_COMMAND_LENGTH) {
        throw new TypeError('O comando deve conter de 1 a 4000 caracteres.');
      }
      return request('POST', '/commands', { text });
    },
    microphone: paused => {
      if (typeof paused !== 'boolean') throw new TypeError('Estado do microfone inválido.');
      return request('POST', '/microphone', { paused });
    },
    conversation: () => request('GET', '/conversation'),
    clearConversation: () => request('POST', '/conversation/clear', {}),
    microphones: () => request('GET', '/microphones'),
    selectMicrophone: deviceId => {
      if (deviceId !== null && (typeof deviceId !== 'string' || deviceId.length > 512)) {
        throw new TypeError('Dispositivo de microfone inválido.');
      }
      return request('POST', '/microphone/device', { device_id: deviceId });
    },
    confirmation: (requestId, approved, pin) => {
      if (typeof requestId !== 'string' || !requestId || typeof approved !== 'boolean' ||
          (pin !== undefined && typeof pin !== 'string')) {
        throw new TypeError('Resposta de confirmação inválida.');
      }
      const body = { request_id: requestId, approved };
      if (pin !== undefined) body.pin = pin;
      return request('POST', '/confirmations', body);
    },
    emergencyStop: () => request('POST', '/emergency-stop', {}),
    palcoFechar: () => request('POST', '/palco/fechar', {}),
    shutdown: () => request('POST', '/shutdown', {}),
    bloco1Status: () => request('GET', '/bloco1'),
    bloco1Salvar: config => request('POST', '/bloco1', config || {}),
    bloco1Executar: (acao, params) => request('POST', '/bloco1/executar', { acao: String(acao), params: params || {} }),
    bloco2Status: () => request('GET', '/bloco2'),
    bloco2Salvar: config => request('POST', '/bloco2', config || {}),
    bloco2Executar: (acao, params) => request('POST', '/bloco2/executar', { acao: String(acao), params: params || {} }),
    mobilePairingStatus: () => request('GET', '/mobile/pairing'),
    mobilePairingRotate: (deviceId, killswitchSeparado) => {
      const payload = { killswitch_separado: killswitchSeparado === true };
      if (typeof deviceId === 'string' && deviceId.trim()) payload.device_id = deviceId.trim();
      return request('POST', '/mobile/pairing/rotate', payload);
    },
    mobilePairingRevoke: deviceId => {
      const payload = typeof deviceId === 'string' && deviceId.trim() ? { device_id: deviceId.trim() } : {};
      return request('POST', '/mobile/pairing/revoke', payload);
    },
  });
}

module.exports = { createApiClient };
