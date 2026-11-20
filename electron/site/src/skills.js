const SKILL_SLUG_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const SKILL_ESTADOS = new Set(['ativo', 'obsoleto', 'arquivado']);
const MAX_ERRO_MSG = 180;

export function validarSlugSkill(slug) {
  return typeof slug === 'string' && SKILL_SLUG_RE.test(slug);
}

function limparErro(erro) {
  const bruto = String(erro?.message || '')
    .replace(/^Error invoking remote method '[^']+':\s*(?:[A-Za-z]*Error:\s*)?/, '')
    .trim();
  if (!bruto || bruto.length > MAX_ERRO_MSG || /[\r\n]/.test(bruto)) {
    return 'Falha de comunicação com a API local.';
  }
  return bruto;
}

function textoLimpo(valor, fallback = '') {
  return typeof valor === 'string' ? valor : fallback;
}

export function validarRespostaSkills(dados) {
  if (!dados || typeof dados !== 'object' || Array.isArray(dados)) {
    throw new Error('Resposta inválida da API local.');
  }
  if (!Array.isArray(dados.skills) || !Array.isArray(dados.pendentes)) {
    throw new Error('Resposta inválida da API local.');
  }
  const skills = dados.skills.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        !validarSlugSkill(item.slug) || typeof item.nome !== 'string' || !item.nome.trim() ||
        typeof item.estado !== 'string' || !SKILL_ESTADOS.has(item.estado) ||
        (item.descricao !== undefined && typeof item.descricao !== 'string') ||
        (item.quando !== undefined && typeof item.quando !== 'string')) {
      throw new Error('Resposta inválida da API local.');
    }
    return Object.freeze({
      slug: item.slug,
      nome: item.nome.trim(),
      descricao: textoLimpo(item.descricao),
      quando: textoLimpo(item.quando),
      estado: item.estado,
    });
  });
  const pendentes = dados.pendentes.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        !validarSlugSkill(item.slug) || typeof item.nome !== 'string' || !item.nome.trim() ||
        (item.descricao !== undefined && typeof item.descricao !== 'string') ||
        (item.quando !== undefined && typeof item.quando !== 'string') ||
        (item.corpo !== undefined && typeof item.corpo !== 'string')) {
      throw new Error('Resposta inválida da API local.');
    }
    return Object.freeze({
      slug: item.slug,
      nome: item.nome.trim(),
      descricao: textoLimpo(item.descricao),
      quando: textoLimpo(item.quando),
      corpo: textoLimpo(item.corpo),
      estado: 'pendente',
    });
  });
  return { skills, pendentes };
}

export function criarGerenciadorSkills({ bridge, confirmar, doc = globalThis.document } = {}) {
  const el = id => doc?.getElementById?.(id) || null;
  const obterPonte = () => bridge ?? globalThis.window?.ultron ?? null;
  const pedirConfirmacao = async msg => {
    if (typeof confirmar === 'function') return Boolean(await confirmar(msg));
    if (typeof globalThis.window?.confirm === 'function') return Boolean(globalThis.window.confirm(msg));
    return false;
  };

  let skills = [];
  let pendentes = [];
  let carregado = false;
  let carregando = false;
  let erroAtual = '';
  let cargaAtual = null;
  const operacoesEmCurso = new Set();

  function nota(texto, classe = '') {
    const alvo = el('skillsNote');
    if (!alvo) return;
    alvo.textContent = texto;
    alvo.className = classe ? `micro nano ${classe}` : 'micro nano';
  }

  function atualizarCarregamento(ativo, mensagem = 'carregando skills…') {
    carregando = Boolean(ativo) || operacoesEmCurso.size > 0;
    const loading = el('skillsLoading');
    if (loading) {
      loading.hidden = !carregando;
      loading.textContent = carregando ? mensagem : '';
    }
    const block = el('skillsBlock');
    if (block?.setAttribute) block.setAttribute('aria-busy', String(carregando));
    const refresh = el('skillsRefresh');
    if (refresh) refresh.disabled = carregando;
  }

  function atualizarBotoes() {
    const pendenteBox = el('skillsPendingList');
    if (!pendenteBox?.querySelectorAll) return;
    for (const btn of pendenteBox.querySelectorAll('button')) {
      const slug = btn.dataset?.slug;
      if (slug) btn.disabled = operacoesEmCurso.has(slug);
    }
  }

  function criarDetalhes(item, { pendente = false } = {}) {
    const detalhes = doc.createElement('details');
    detalhes.className = 'skill-details';
    const resumo = doc.createElement('summary');
    resumo.textContent = pendente ? 'ver detalhes e passos' : 'ver detalhes';
    detalhes.append(resumo);

    const slugLinha = doc.createElement('p');
    slugLinha.className = 'skill-meta';
    slugLinha.textContent = `identificador: ${item.slug}`;
    detalhes.append(slugLinha);

    if (pendente && item.corpo) {
      const pre = doc.createElement('pre');
      pre.className = 'skill-body';
      pre.textContent = item.corpo;
      detalhes.append(pre);
    }
    return detalhes;
  }

  function criarCartao(item, { pendente = false } = {}) {
    const card = doc.createElement('article');
    card.className = 'skill-card';
    card.dataset.slug = item.slug;
    card.dataset.estado = item.estado;

    const top = doc.createElement('div');
    top.className = 'skill-top';

    const nome = doc.createElement('b');
    nome.className = 'skill-name';
    nome.textContent = item.nome;

    const badge = doc.createElement('span');
    badge.className = 'skill-badge';
    badge.dataset.estado = item.estado;
    badge.textContent = item.estado;

    top.append(nome, badge);
    card.append(top);

    if (item.descricao) {
      const desc = doc.createElement('p');
      desc.className = 'skill-desc';
      desc.textContent = item.descricao;
      card.append(desc);
    }
    if (item.quando) {
      const quando = doc.createElement('p');
      quando.className = 'skill-when';
      quando.textContent = `Quando: ${item.quando}`;
      card.append(quando);
    }

    card.append(criarDetalhes(item, { pendente }));

    if (pendente) {
      const acoes = doc.createElement('div');
      acoes.className = 'skill-actions';
      const ocupado = operacoesEmCurso.has(item.slug);

      const btnAprovar = doc.createElement('button');
      btnAprovar.type = 'button';
      btnAprovar.className = 'solid';
      btnAprovar.dataset.action = 'aprovar';
      btnAprovar.dataset.slug = item.slug;
      btnAprovar.disabled = ocupado;
      btnAprovar.textContent = 'aprovar';
      btnAprovar.onclick = () => aprovar(item.slug);

      const btnDescartar = doc.createElement('button');
      btnDescartar.type = 'button';
      btnDescartar.className = 'danger';
      btnDescartar.dataset.action = 'descartar';
      btnDescartar.dataset.slug = item.slug;
      btnDescartar.disabled = ocupado;
      btnDescartar.textContent = 'descartar';
      btnDescartar.onclick = () => descartar(item.slug);

      acoes.append(btnAprovar, btnDescartar);
      card.append(acoes);
    }

    return card;
  }

  function pintar() {
    if (!doc) return;
    const pendenteBox = el('skillsPendingList');
    const listaBox = el('skillsList');
    if (pendenteBox) {
      pendenteBox.replaceChildren();
      if (!carregado && erroAtual) {
        const aviso = doc.createElement('p');
        aviso.className = 'skill-empty err';
        aviso.textContent = 'skills pendentes indisponíveis no momento';
        pendenteBox.append(aviso);
      } else if (!pendentes.length) {
        const vazio = doc.createElement('p');
        vazio.className = 'skill-empty';
        vazio.textContent = 'nenhuma skill pendente de aprovação';
        pendenteBox.append(vazio);
      } else {
        for (const item of pendentes) pendenteBox.append(criarCartao(item, { pendente: true }));
      }
    }
    if (listaBox) {
      listaBox.replaceChildren();
      if (!carregado && erroAtual) {
        const aviso = doc.createElement('p');
        aviso.className = 'skill-empty err';
        aviso.textContent = 'skills registradas indisponíveis no momento';
        listaBox.append(aviso);
      } else if (!skills.length) {
        const vazio = doc.createElement('p');
        vazio.className = 'skill-empty';
        vazio.textContent = 'nenhuma skill registrada';
        listaBox.append(vazio);
      } else {
        for (const item of skills) listaBox.append(criarCartao(item, { pendente: false }));
      }
    }
  }

  async function _executarCarga({ silenciosoNota = false, preservarOcupado = false } = {}) {
    const ponte = obterPonte();
    if (!ponte || typeof ponte.skillsListar !== 'function') {
      const msg = 'Ponte de skills indisponível.';
      erroAtual = msg;
      pintar();
      if (!silenciosoNota) nota(msg, 'err');
      return { ok: false, error: msg, skills, pendentes };
    }
    atualizarCarregamento(true, 'carregando skills…');
    try {
      const dados = validarRespostaSkills(await ponte.skillsListar());
      skills = dados.skills;
      pendentes = dados.pendentes;
      carregado = true;
      erroAtual = '';
      pintar();
      if (!silenciosoNota) {
        nota(`${pendentes.length} pendente(s) · ${skills.length} registrada(s)`, '');
      }
      return { ok: true, skills, pendentes };
    } catch (erro) {
      const msg = limparErro(erro);
      erroAtual = msg;
      pintar();
      if (!silenciosoNota) nota(`não foi possível listar as skills (${msg})`, 'err');
      return { ok: false, error: msg, skills, pendentes };
    } finally {
      if (!preservarOcupado) atualizarCarregamento(false);
    }
  }

  function carregar(opcoes = {}) {
    if (cargaAtual && !opcoes.forcar) return cargaAtual;
    const execucao = _executarCarga(opcoes).finally(() => {
      if (cargaAtual === execucao) cargaAtual = null;
    });
    cargaAtual = execucao;
    return execucao;
  }

  async function _executarAcao(acao, slug) {
    if (!validarSlugSkill(slug)) {
      const msg = 'Identificador de skill inválido.';
      nota(msg, 'err');
      return { ok: false, motivo: 'invalid_slug', erro: msg };
    }
    if (operacoesEmCurso.has(slug)) {
      return { ok: false, motivo: 'duplicate' };
    }
    const alvo = pendentes.find(item => item.slug === slug);
    if (!alvo) {
      const msg = `Skill pendente não encontrada: ${slug}.`;
      nota(msg, 'err');
      await carregar({ forcar: true, silenciosoNota: true });
      return { ok: false, motivo: 'not_found', erro: msg };
    }
    const ponte = obterPonte();
    const metodo = acao === 'aprovar' ? 'skillsAprovar' : 'skillsDescartar';
    if (!ponte || typeof ponte[metodo] !== 'function') {
      const msg = 'Ponte de skills indisponível.';
      nota(msg, 'err');
      return { ok: false, motivo: 'bridge_unavailable', erro: msg };
    }

    operacoesEmCurso.add(slug);
    atualizarBotoes();
    try {
      const aviso = acao === 'aprovar'
        ? `Aprovar e ativar a skill “${alvo.nome}” (${alvo.slug})?\n\nQuando usar: ${alvo.quando || '—'}\n\nRevise os passos antes de confirmar.`
        : `Descartar permanentemente a skill pendente “${alvo.nome}” (${alvo.slug})?`;
      if (!await pedirConfirmacao(aviso)) {
        nota(`Operação cancelada para “${alvo.nome}”.`);
        return { ok: false, motivo: 'cancelled' };
      }

      atualizarCarregamento(true, acao === 'aprovar'
        ? `aprovando “${alvo.nome}”…`
        : `descartando “${alvo.nome}”…`);

      const resposta = await ponte[metodo](slug);
      if (!resposta || typeof resposta !== 'object' || Array.isArray(resposta) ||
          resposta.ok !== true || (acao === 'aprovar' && resposta.slug !== slug)) {
        throw new Error('Resposta inválida da API local.');
      }

      const carga = await carregar({ forcar: true, silenciosoNota: true, preservarOcupado: true });
      if (!carga.ok) {
        const msg = `${acao === 'aprovar' ? 'Skill aprovada' : 'Skill descartada'}: “${alvo.nome}”. Não foi possível atualizar a lista (${carga.error}).`;
        nota(msg, 'err');
        return { ok: true, slug };
      }
      nota(
        acao === 'aprovar'
          ? `Skill “${alvo.nome}” aprovada e ativada.`
          : `Skill “${alvo.nome}” descartada.`,
        'ok',
      );
      return { ok: true, slug };
    } catch (erro) {
      const msg = limparErro(erro);
      const rotulo = acao === 'aprovar' ? 'Não foi possível aprovar' : 'Não foi possível descartar';
      const completo = `${rotulo} “${alvo.nome}”: ${msg}`;
      nota(completo, 'err');
      await carregar({ forcar: true, silenciosoNota: true, preservarOcupado: true });
      return { ok: false, motivo: 'error', erro: completo };
    } finally {
      operacoesEmCurso.delete(slug);
      atualizarCarregamento(false);
      atualizarBotoes();
      pintar();
    }
  }

  const aprovar = slug => _executarAcao('aprovar', slug);
  const descartar = slug => _executarAcao('descartar', slug);
  const estado = () => Object.freeze({
    carregado,
    carregando,
    erro: erroAtual,
    skills: [...skills],
    pendentes: [...pendentes],
    emCurso: [...operacoesEmCurso],
  });

  return Object.freeze({ carregar, aprovar, descartar, estado });
}
