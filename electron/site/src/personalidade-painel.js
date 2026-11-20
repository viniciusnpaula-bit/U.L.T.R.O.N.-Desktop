/* Painel de personalidade: identidade, jeito, dados do usuário e saudação. */

export function criarPainelPersonalidade({
  $,
  bridge = () => window.ultron,
  doc = document,
  onPerfilMudou = null,
}) {
  let perfilAtual = 'ultron';
  let jeitoAtual = 'equilibrado';
  let jeitosCache = [];
  let saudacaoLigada = true;
  // cada perfil guarda o próprio tratamento e jeito: trocar de perfil não herda do anterior
  let tratamentosPorPerfil = {};
  let jeitosPorPerfil = {};

  function pintarPerfil(perfil) {
    perfilAtual = perfil;
    doc.querySelectorAll('[data-profile]').forEach(node => {
      node.setAttribute('aria-checked', String(node.dataset.profile === perfil));
    });
    const salvo = tratamentosPorPerfil[perfil];
    if (typeof salvo === 'string') $('tratamentoInput').value = salvo;
    const jeitoSalvo = jeitosPorPerfil[perfil];
    if (typeof jeitoSalvo === 'string') pintarJeito(jeitoSalvo);
    else if (Object.keys(jeitosPorPerfil).length) pintarJeito('equilibrado');
    $('headerProfile').textContent = String(perfil || 'ultron').toUpperCase();
  }

  function renderStyleCards(jeitos) {
    const grade = $('styleCards');
    if (!grade) return;
    grade.replaceChildren();
    for (const jeito of jeitos) {
      const cartao = doc.createElement('button');
      cartao.type = 'button';
      cartao.className = 'choice-card';
      cartao.dataset.jeito = jeito.id;
      cartao.setAttribute('role', 'radio');
      cartao.setAttribute('aria-checked', 'false');
      const titulo = doc.createElement('b');
      titulo.textContent = jeito.rotulo || jeito.id;
      const nota = doc.createElement('span');
      nota.textContent = jeito.descricao || '';
      cartao.append(titulo, nota);
      cartao.addEventListener('click', () => escolherJeito(jeito.id));
      grade.append(cartao);
    }
  }

  function pintarJeito(jeito) {
    jeitoAtual = jeito || 'equilibrado';
    doc.querySelectorAll('#styleCards [data-jeito]').forEach(node => {
      node.setAttribute('aria-checked', String(node.dataset.jeito === jeitoAtual));
    });
    $('headerStyle').textContent = jeitosCache.find(j => j.id === jeitoAtual)?.rotulo || jeitoAtual;
  }

  function pintarSaudacao(ligada) {
    saudacaoLigada = Boolean(ligada);
    const botao = $('greetingToggle');
    if (!botao) return;
    botao.setAttribute('aria-checked', String(saudacaoLigada));
    botao.textContent = `saudação ao abrir: ${saudacaoLigada ? 'ligada' : 'desligada'}`;
  }

  function preencherUsuario(usuario = {}) {
    if ($('userName')) $('userName').value = usuario.nome || '';
    if ($('userNickname')) $('userNickname').value = usuario.apelido || '';
    if ($('userAge')) $('userAge').value = usuario.idade || '';
    if ($('userGender')) $('userGender').value = usuario.genero || '';
    if ($('userAbout')) $('userAbout').value = usuario.sobre || '';
  }

  function dadosDoUsuario() {
    return {
      nome: $('userName')?.value.trim() || '',
      apelido: $('userNickname')?.value.trim() || '',
      idade: $('userAge')?.value.trim() || '',
      genero: $('userGender')?.value || '',
      sobre: $('userAbout')?.value.trim() || '',
    };
  }

  async function carregarPersonalidade() {
    try {
      const info = await bridge().personalidadeInfo();
      const atual = info.atual || {};
      tratamentosPorPerfil = { ...(atual.tratamentos || {}) };
      jeitosPorPerfil = { ...(atual.jeitos || {}) };
      for (const p of info.perfis || []) {
        if (typeof p.tratamento === 'string' && !tratamentosPorPerfil[p.id]) {
          tratamentosPorPerfil[p.id] = p.tratamento;
        }
        if (typeof p.jeito === 'string' && !jeitosPorPerfil[p.id]) {
          jeitosPorPerfil[p.id] = p.jeito;
        }
      }
      const perfilAtivo = atual.perfil || 'ultron';
      if (typeof atual.tratamento === 'string') tratamentosPorPerfil[perfilAtivo] = atual.tratamento;
      if (typeof atual.jeito === 'string') jeitosPorPerfil[perfilAtivo] = atual.jeito;
      jeitosCache = Array.isArray(info.jeitos) ? info.jeitos : [];
      renderStyleCards(jeitosCache);
      pintarPerfil(perfilAtivo);
      pintarJeito(atual.jeito || jeitosPorPerfil[perfilAtivo] || 'equilibrado');
      $('tratamentoInput').value = atual.tratamento || tratamentosPorPerfil[perfilAtivo] || '';
      onPerfilMudou?.(perfilAtivo);
      preencherUsuario(atual.usuario || {});
      pintarSaudacao(atual.saudacao !== false);
      $('profileNote').textContent = `perfil ${perfilAtivo} · jeito ${atual.jeito || 'equilibrado'} · tratamento “${atual.tratamento || '—'}”`;
      $('profileNote').className = 'micro nano ok';
    } catch (error) {
      $('profileNote').textContent = `não consegui ler a personalidade (${error.message})`;
      $('profileNote').className = 'micro nano err';
    }
  }

  async function salvarPersonalidade({ usuario = false, saudacao = false, apenasPerfil = false } = {}) {
    try {
      const dados = apenasPerfil
        ? { perfil: perfilAtual }
        : {
            perfil: perfilAtual,
            tratamento: $('tratamentoInput').value.trim(),
            jeito: jeitoAtual,
          };
      if (usuario) dados.usuario = dadosDoUsuario();
      if (saudacao) dados.saudacao = saudacaoLigada;
      const salvo = await bridge().personalidadeSalvar(dados);
      tratamentosPorPerfil = { ...tratamentosPorPerfil, ...(salvo.tratamentos || {}) };
      if (typeof salvo.tratamento === 'string') tratamentosPorPerfil[salvo.perfil] = salvo.tratamento;
      jeitosPorPerfil = { ...jeitosPorPerfil, ...(salvo.jeitos || {}) };
      if (typeof salvo.jeito === 'string') jeitosPorPerfil[salvo.perfil] = salvo.jeito;
      pintarPerfil(salvo.perfil);
      pintarJeito(salvo.jeito);
      $('tratamentoInput').value = salvo.tratamento || '';
      onPerfilMudou?.(salvo.perfil);
      if (usuario && salvo.usuario) preencherUsuario(salvo.usuario);
      pintarSaudacao(salvo.saudacao !== false);
      const nomeJeito = jeitosCache.find(j => j.id === salvo.jeito)?.rotulo || salvo.jeito;
      $('profileNote').textContent = `aplicado: ${salvo.perfil} · ${nomeJeito} · tratamento “${salvo.tratamento}”`;
      $('profileNote').className = 'micro nano ok';
      return salvo;
    } catch (error) {
      $('profileNote').textContent = `não consegui aplicar (${error.message})`;
      $('profileNote').className = 'micro nano err';
      return null;
    }
  }

  async function escolherJeito(jeito) {
    if (!jeito) return;
    jeitosPorPerfil[perfilAtual] = jeito;
    pintarJeito(jeito);
    await salvarPersonalidade();
  }

  async function selecionarPerfil(perfil) {
    if (!perfil) return null;
    pintarPerfil(perfil);
    onPerfilMudou?.(perfil);
    return salvarPersonalidade({ apenasPerfil: true });
  }

  async function alternarSaudacao() {
    pintarSaudacao(!saudacaoLigada);
    try {
      const salvo = await bridge().personalidadeSalvar({ saudacao: saudacaoLigada });
      pintarSaudacao(salvo.saudacao !== false);
      $('profileNote').textContent = `saudação ao abrir: ${saudacaoLigada ? 'ligada' : 'desligada'}`;
      $('profileNote').className = 'micro nano ok';
    } catch (error) {
      pintarSaudacao(!saudacaoLigada);
      $('profileNote').textContent = `não consegui salvar a saudação (${error.message})`;
      $('profileNote').className = 'micro nano err';
    }
  }

  async function previaPersonalidade() {
    try {
      const r = await bridge().personalidadePrevia();
      $('profileNote').textContent = r.instrucao;
      $('profileNote').className = 'micro nano';
    } catch (error) {
      $('profileNote').textContent = `não consegui montar a prévia (${error.message})`;
      $('profileNote').className = 'micro nano err';
    }
  }

  async function restaurarPersonalidade() {
    try {
      await bridge().personalidadeRestaurar();
      await carregarPersonalidade();
      $('profileNote').textContent = 'personalidade restaurada ao padrão.';
    } catch (error) {
      $('profileNote').textContent = `não consegui restaurar (${error.message})`;
    }
  }

  return {
    pintarPerfil,
    selecionarPerfil,
    carregarPersonalidade,
    salvarPersonalidade,
    escolherJeito,
    alternarSaudacao,
    previaPersonalidade,
    restaurarPersonalidade,
  };
}
