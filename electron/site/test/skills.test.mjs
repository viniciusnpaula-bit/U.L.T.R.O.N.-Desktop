import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { criarGerenciadorSkills } from '../src/skills.js';

function criarElemento(tag = 'div', doc = null) {
  const el = {
    tagName: String(tag).toUpperCase(),
    id: '',
    type: '',
    className: '',
    hidden: false,
    disabled: false,
    textContent: '',
    dataset: {},
    attrs: {},
    children: [],
    listeners: {},
    onclick: null,
    parentNode: null,
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return Object.hasOwn(this.attrs, k) ? this.attrs[k] : null; },
    addEventListener(tipo, fn) {
      if (!this.listeners[tipo]) this.listeners[tipo] = [];
      this.listeners[tipo].push(fn);
    },
    append(...nos) {
      for (const n of nos) {
        if (typeof n === 'string') {
          const txt = criarElemento('#text', doc);
          txt.textContent = n;
          this.children.push(txt);
        } else if (n) {
          n.parentNode = this;
          this.children.push(n);
        }
      }
    },
    replaceChildren(...nos) {
      this.children = [];
      this.append(...nos);
    },
    querySelectorAll(selector) {
      const encontrados = [];
      const visit = node => {
        for (const child of node.children || []) {
          if (seleciona(child, selector)) encontrados.push(child);
          visit(child);
        }
      };
      visit(this);
      return encontrados;
    },
    querySelector(selector) {
      return this.querySelectorAll(selector)[0] || null;
    },
    click() {
      if (this.disabled) return;
      if (typeof this.onclick === 'function') this.onclick();
      for (const fn of this.listeners.click || []) fn({ target: this, preventDefault() {} });
    },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return ''; },
    set() { throw new Error('innerHTML proibido em skills UI'); },
  });
  return el;
}

function seleciona(el, selector) {
  if (selector.startsWith('.')) {
    const cls = selector.slice(1).split('[')[0];
    const classes = String(el.className || '').split(/\s+/);
    if (!classes.includes(cls)) return false;
    const m = selector.match(/\[data-([a-z-]+)="([^"]+)"\]/);
    if (m) return el.dataset[m[1]] === m[2];
    return true;
  }
  const attrOnly = selector.match(/^\[data-([a-z-]+)="([^"]+)"\]$/);
  if (attrOnly) return el.dataset[attrOnly[1]] === attrOnly[2];
  return String(el.tagName || '').toLowerCase() === selector.toLowerCase();
}

function textoDe(node) {
  if (!node) return '';
  let out = node.textContent || '';
  for (const child of node.children || []) out += ' ' + textoDe(child);
  return out.trim();
}

function documentoFalso() {
  const ids = ['skillsBlock', 'skillsRefresh', 'skillsLoading', 'skillsNote', 'skillsPendingList', 'skillsList'];
  const mapa = Object.fromEntries(ids.map(id => {
    const el = criarElemento(id === 'skillsRefresh' ? 'button' : 'div');
    el.id = id;
    return [id, el];
  }));
  mapa.skillsLoading.hidden = true;
  const doc = {
    mapa,
    getElementById: id => mapa[id] || null,
    createElement: tag => criarElemento(tag, doc),
  };
  return doc;
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test('1. listagem de skills renderiza pendentes e ativas com detalhes do backend sem usar innerHTML', async () => {
  const doc = documentoFalso();
  const bridge = {
    skillsListar: async () => ({
      skills: [
        { slug: 'modo-foco', nome: 'Modo foco', descricao: 'Silencia distrações', quando: 'pedir foco', estado: 'ativo' },
        { slug: 'relatorio-antigo', nome: 'Relatório', descricao: 'Resumo semanal', quando: 'toda sexta', estado: 'obsoleto' },
      ],
      pendentes: [
        { slug: 'abrir-git', nome: 'Abrir Git', quando: 'quando disser abrir git', corpo: '1. Abrir terminal\n2. Executar git status' },
      ],
    }),
    skillsAprovar: async () => ({ ok: true, slug: 'abrir-git' }),
    skillsDescartar: async () => ({ ok: true }),
  };

  const gerenciador = criarGerenciadorSkills({ bridge, confirmar: () => true, doc });
  const r = await gerenciador.carregar();
  assert.equal(r.ok, true);
  assert.equal(doc.mapa.skillsLoading.hidden, true);
  assert.equal(doc.mapa.skillsBlock.getAttribute('aria-busy'), 'false');

  const cardsPendentes = doc.mapa.skillsPendingList.querySelectorAll('.skill-card');
  assert.equal(cardsPendentes.length, 1);
  const txtPend = textoDe(cardsPendentes[0]);
  assert.match(txtPend, /Abrir Git/);
  assert.match(txtPend, /pendente/);
  assert.match(txtPend, /quando disser abrir git/);
  assert.match(txtPend, /Executar git status/);
  assert.match(txtPend, /abrir-git/);
  assert.ok(cardsPendentes[0].querySelector('[data-action="aprovar"]'));
  assert.ok(cardsPendentes[0].querySelector('[data-action="descartar"]'));

  const cardsAtivos = doc.mapa.skillsList.querySelectorAll('.skill-card');
  assert.equal(cardsAtivos.length, 2);
  assert.match(textoDe(cardsAtivos[0]), /Modo foco/);
  assert.match(textoDe(cardsAtivos[0]), /Silencia distrações/);
  assert.match(textoDe(cardsAtivos[0]), /ativo/);
  assert.match(textoDe(cardsAtivos[1]), /obsoleto/);
  assert.equal(cardsAtivos[0].querySelector('[data-action="aprovar"]'), null);
  assert.equal(cardsAtivos[0].querySelector('[data-action="descartar"]'), null);
});

test('2. estado vazio quando não há skills pendentes nem registradas', async () => {
  const doc = documentoFalso();
  const bridge = {
    skillsListar: async () => ({ skills: [], pendentes: [] }),
    skillsAprovar: async () => ({ ok: true, slug: 'x' }),
    skillsDescartar: async () => ({ ok: true }),
  };
  const gerenciador = criarGerenciadorSkills({ bridge, confirmar: () => true, doc });
  const r = await gerenciador.carregar();
  assert.equal(r.ok, true);
  assert.equal(doc.mapa.skillsPendingList.querySelectorAll('.skill-card').length, 0);
  assert.equal(doc.mapa.skillsList.querySelectorAll('.skill-card').length, 0);
  assert.match(textoDe(doc.mapa.skillsPendingList), /nenhuma skill pendente/i);
  assert.match(textoDe(doc.mapa.skillsList), /nenhuma skill registrada/i);
});

test('3 e 10. aprovação bem-sucedida confirma, chama backend e atualiza a interface após operação', async () => {
  const doc = documentoFalso();
  let pendentes = [
    { slug: 'backup-notas', nome: 'Backup Notas', quando: 'pedir backup', corpo: '1. Compactar pasta' },
  ];
  const skills = [];
  const confirmacoes = [];
  const chamadas = [];
  const bridge = {
    skillsListar: async () => {
      chamadas.push('listar');
      return { skills: skills.map(s => ({ ...s })), pendentes: pendentes.map(p => ({ ...p })) };
    },
    skillsAprovar: async nome => {
      chamadas.push(['aprovar', nome]);
      const item = pendentes.find(p => p.slug === nome);
      pendentes = pendentes.filter(p => p.slug !== nome);
      skills.push({ slug: item.slug, nome: item.nome, descricao: item.quando, quando: item.quando, estado: 'ativo' });
      return { ok: true, slug: nome };
    },
    skillsDescartar: async () => ({ ok: true }),
  };

  const gerenciador = criarGerenciadorSkills({
    bridge,
    confirmar: msg => (confirmacoes.push(msg), true),
    doc,
  });
  await gerenciador.carregar();
  const approveBtn = doc.mapa.skillsPendingList.querySelector('[data-action="aprovar"]');
  approveBtn.click();
  await new Promise(r => setTimeout(r, 0));

  assert.equal(confirmacoes.length, 1);
  assert.match(confirmacoes[0], /Backup Notas/);
  assert.deepEqual(chamadas, ['listar', ['aprovar', 'backup-notas'], 'listar']);
  assert.equal(doc.mapa.skillsPendingList.querySelectorAll('.skill-card').length, 0);
  assert.match(textoDe(doc.mapa.skillsPendingList), /nenhuma skill pendente/i);
  assert.equal(doc.mapa.skillsList.querySelectorAll('.skill-card').length, 1);
  assert.match(textoDe(doc.mapa.skillsList), /Backup Notas/);
  assert.match(doc.mapa.skillsNote.className, /ok/);
  assert.match(doc.mapa.skillsNote.textContent, /aprovada/i);
});

test('4 e 10. descarte bem-sucedido confirma, chama backend e atualiza a interface', async () => {
  const doc = documentoFalso();
  let pendentes = [
    { slug: 'rascunho-x', nome: 'Rascunho X', quando: 'teste', corpo: '1. Fazer nada' },
  ];
  const calls = [];
  const bridge = {
    skillsListar: async () => (calls.push('listar'), { skills: [], pendentes: [...pendentes] }),
    skillsAprovar: async () => ({ ok: true, slug: 'rascunho-x' }),
    skillsDescartar: async nome => {
      calls.push(['descartar', nome]);
      pendentes = pendentes.filter(p => p.slug !== nome);
      return { ok: true };
    },
  };
  const gerenciador = criarGerenciadorSkills({ bridge, confirmar: () => true, doc });
  await gerenciador.carregar();
  const discardBtn = doc.mapa.skillsPendingList.querySelector('[data-action="descartar"]');
  discardBtn.click();
  await new Promise(r => setTimeout(r, 0));

  assert.deepEqual(calls, ['listar', ['descartar', 'rascunho-x'], 'listar']);
  assert.equal(doc.mapa.skillsPendingList.querySelectorAll('.skill-card').length, 0);
  assert.match(textoDe(doc.mapa.skillsPendingList), /nenhuma skill pendente/i);
  assert.match(doc.mapa.skillsNote.className, /ok/);
  assert.match(doc.mapa.skillsNote.textContent, /descartada/i);
});

test('5. erro de comunicação com a API mostra erro claro e encerra o indicador de carregamento', async () => {
  const doc = documentoFalso();
  const p = deferred();
  const bridge = {
    skillsListar: () => p.promise,
    skillsAprovar: async () => { throw new Error('Não foi possível conectar à API local.'); },
    skillsDescartar: async () => { throw new Error('Tempo limite da API local excedido.'); },
  };
  const gerenciador = criarGerenciadorSkills({ bridge, confirmar: () => true, doc });
  const loadPromise = gerenciador.carregar();
  assert.equal(doc.mapa.skillsLoading.hidden, false);
  assert.equal(doc.mapa.skillsRefresh.disabled, true);
  assert.equal(doc.mapa.skillsBlock.getAttribute('aria-busy'), 'true');

  p.reject(new Error('Não foi possível conectar à API local.'));
  const r = await loadPromise;
  assert.equal(r.ok, false);
  assert.equal(doc.mapa.skillsLoading.hidden, true);
  assert.equal(doc.mapa.skillsRefresh.disabled, false);
  assert.equal(doc.mapa.skillsBlock.getAttribute('aria-busy'), 'false');
  assert.match(doc.mapa.skillsNote.className, /err/);
  assert.match(doc.mapa.skillsNote.textContent, /Não foi possível conectar/);

  bridge.skillsListar = async () => ({
    skills: [],
    pendentes: [{ slug: 'teste-api', nome: 'Teste API', quando: 'sempre', corpo: 'passo' }],
  });
  await gerenciador.carregar();
  const resApprove = await gerenciador.aprovar('teste-api');
  assert.equal(resApprove.ok, false);
  assert.equal(doc.mapa.skillsLoading.hidden, true);
  assert.match(doc.mapa.skillsNote.className, /err/);
  assert.match(doc.mapa.skillsNote.textContent, /Não foi possível conectar/);
});

test('6. resposta inválida da API não corrompe estado e informa erro claro', async () => {
  const doc = documentoFalso();
  for (const respostaInvalida of [
    null,
    [],
    {},
    { skills: 'invalido', pendentes: [] },
    { skills: [{ slug: 'ok', nome: 'OK', estado: 'estado-falso' }], pendentes: [] },
    { skills: [], pendentes: [{ slug: '../hack', nome: 'Hack' }] },
  ]) {
    const bridge = {
      skillsListar: async () => respostaInvalida,
      skillsAprovar: async () => ({ ok: true, slug: 'x' }),
      skillsDescartar: async () => ({ ok: true }),
    };
    const gerenciador = criarGerenciadorSkills({ bridge, confirmar: () => true, doc });
    const r = await gerenciador.carregar();
    assert.equal(r.ok, false);
    assert.match(doc.mapa.skillsNote.className, /err/);
    assert.match(doc.mapa.skillsNote.textContent, /inválida/i);
    assert.equal(doc.mapa.skillsPendingList.querySelectorAll('.skill-card').length, 0);
  }

  const bridgeBadMut = {
    skillsListar: async () => ({
      skills: [],
      pendentes: [{ slug: 'boa', nome: 'Boa', quando: 'q', corpo: 'c' }],
    }),
    skillsAprovar: async () => ({ ok: false }),
    skillsDescartar: async () => ({ ok: 'sim' }),
  };
  const gerenciador = criarGerenciadorSkills({ bridge: bridgeBadMut, confirmar: () => true, doc });
  await gerenciador.carregar();
  assert.equal((await gerenciador.aprovar('boa')).ok, false);
  assert.match(doc.mapa.skillsNote.className, /err/);
  assert.equal((await gerenciador.descartar('boa')).ok, false);
  assert.match(doc.mapa.skillsNote.className, /err/);
});

test('7. identificador inexistente é bloqueado ou reconciliado em caso de 409 conflict', async () => {
  const doc = documentoFalso();
  let calls = 0;
  let serverPendentes = [
    { slug: 'removida-fora', nome: 'Removida', quando: 'q', corpo: 'c' },
  ];
  const bridge = {
    skillsListar: async () => ({ skills: [], pendentes: serverPendentes }),
    skillsAprovar: async () => {
      calls += 1;
      serverPendentes = [];
      throw new Error("Error invoking remote method 'skills:aprovar': Error: A API local recusou a solicitação (409). skill pendente não encontrada: removida-fora");
    },
    skillsDescartar: async () => { calls += 1; return { ok: true }; },
  };
  const gerenciador = criarGerenciadorSkills({ bridge, confirmar: () => true, doc });
  await gerenciador.carregar();

  // Identificador que não existe (e nomes reservados do JS) nunca chegam à API
  for (const inexistente of ['nao-existe', 'constructor']) {
    const missing = await gerenciador.aprovar(inexistente);
    assert.equal(missing.ok, false);
    assert.equal(missing.motivo, 'not_found');
    const missingDiscard = await gerenciador.descartar(inexistente);
    assert.equal(missingDiscard.ok, false);
    assert.equal(missingDiscard.motivo, 'not_found');
  }
  assert.equal(calls, 0);
  assert.match(doc.mapa.skillsNote.className, /err/);

  // Caso exista localmente mas o backend responda 409, reconcilia a lista removendo da UI
  const raced = await gerenciador.aprovar('removida-fora');
  assert.equal(raced.ok, false);
  assert.equal(calls, 1);
  assert.match(doc.mapa.skillsNote.className, /err/);
  assert.match(doc.mapa.skillsNote.textContent, /não encontrada|409/i);
  assert.equal(doc.mapa.skillsPendingList.querySelectorAll('.skill-card').length, 0);
});

test('8. cliques duplicados não enviam operações repetidas', async () => {
  const doc = documentoFalso();
  const pendingApproval = deferred();
  let approveCount = 0;
  let confirmCount = 0;
  let current = [{ slug: 'unica-skill', nome: 'Única', quando: 'q', corpo: 'c' }];

  const bridge = {
    skillsListar: async () => ({ skills: [], pendentes: current }),
    skillsAprovar: () => {
      approveCount += 1;
      return pendingApproval.promise;
    },
    skillsDescartar: async () => {
      throw new Error('não deveria descartar enquanto aprova');
    },
  };

  const gerenciador = criarGerenciadorSkills({
    bridge,
    confirmar: () => { confirmCount += 1; return true; },
    doc,
  });
  await gerenciador.carregar();

  const btnApprove = doc.mapa.skillsPendingList.querySelector('[data-action="aprovar"]');
  const btnDiscard = doc.mapa.skillsPendingList.querySelector('[data-action="descartar"]');

  const p1 = gerenciador.aprovar('unica-skill');
  assert.equal(btnApprove.disabled, true);
  assert.equal(btnDiscard.disabled, true);
  btnApprove.click();
  const p2 = gerenciador.aprovar('unica-skill');
  const p3 = gerenciador.descartar('unica-skill');

  assert.equal((await p2).motivo, 'duplicate');
  assert.equal((await p3).motivo, 'duplicate');
  assert.equal(confirmCount, 1);
  assert.equal(approveCount, 1);

  current = [];
  pendingApproval.resolve({ ok: true, slug: 'unica-skill' });
  const r1 = await p1;
  assert.equal(r1.ok, true);
  assert.equal(approveCount, 1);
});

test('9. restrições de segurança: confirmação, slug traversal, XSS via textContent, IPC/preload/HTML/CSS', async () => {
  const doc = documentoFalso();
  let mutCalled = false;
  const bridge = {
    skillsListar: async () => ({
      skills: [],
      pendentes: [{
        slug: 'xss-skill',
        nome: '<img src=x onerror=alert(1)>',
        quando: '<script>alert(2)</script>',
        corpo: '<svg onload=alert(3)>',
      }],
    }),
    skillsAprovar: async () => { mutCalled = true; return { ok: true, slug: 'xss-skill' }; },
    skillsDescartar: async () => { mutCalled = true; return { ok: true }; },
  };

  // Cancelar confirmação bloqueia execução
  const gerenciadorNegado = criarGerenciadorSkills({ bridge, confirmar: () => false, doc });
  await gerenciadorNegado.carregar();
  const resCancel = await gerenciadorNegado.aprovar('xss-skill');
  assert.equal(resCancel.ok, false);
  assert.equal(resCancel.motivo, 'cancelled');
  assert.equal(mutCalled, false);

  // Texto malicioso foi preservado literalmente via textContent (sem HTML parsing)
  const card = doc.mapa.skillsPendingList.querySelector('.skill-card');
  assert.match(textoDe(card), /<img src=x onerror=alert\(1\)>/);

  // Slugs inválidos / traversal / caracteres não permitidos são rejeitados localmente
  for (const slugRuim of ['../etc', 'A', '__proto__', 'a/b', 'a b', '', 'x'.repeat(41), null]) {
    const r = await gerenciadorNegado.aprovar(slugRuim);
    assert.equal(r.ok, false);
    assert.equal(r.motivo, 'invalid_slug');
  }
  assert.equal(mutCalled, false);

  // Verificar isolamento IPC/preload/HTML/CSS/app/preview/package
  const site = new URL('../', import.meta.url);
  const main = await readFile(fileURLToPath(new URL('../main.js', site)), 'utf8');
  const preload = await readFile(fileURLToPath(new URL('../preload.js', site)), 'utf8');
  const html = await readFile(fileURLToPath(new URL('index.html', site)), 'utf8');
  const preview = await readFile(fileURLToPath(new URL('preview.html', site)), 'utf8');
  const mock = await readFile(fileURLToPath(new URL('preview-mock.js', site)), 'utf8');
  const app = await readFile(fileURLToPath(new URL('app.js', site)), 'utf8');
  const css = await readFile(fileURLToPath(new URL('style.css', site)), 'utf8');
  const pkg = JSON.parse(await readFile(fileURLToPath(new URL('../package.json', site)), 'utf8'));
  const skillsMod = await readFile(fileURLToPath(new URL('src/skills.js', site)), 'utf8');

  for (const canal of ['skills:listar', 'skills:aprovar', 'skills:descartar']) {
    assert.match(main, new RegExp(`ipcMain\\.handle\\('${canal}'`), canal);
  }
  assert.match(main, /ipcMain\.handle\('skills:aprovar'[\s\S]*isSender\(event, mainWindow\)[\s\S]*SKILL_SLUG_RE\.test/);
  assert.match(main, /ipcMain\.handle\('skills:descartar'[\s\S]*isSender\(event, mainWindow\)[\s\S]*SKILL_SLUG_RE\.test/);
  assert.match(preload, /skillsListar:\s*\(\)\s*=>\s*ipcRenderer\.invoke\('skills:listar'\)/);
  assert.match(preload, /skillsAprovar:\s*nome\s*=>\s*ipcRenderer\.invoke\('skills:aprovar',\s*nome\)/);
  assert.match(preload, /skillsDescartar:\s*nome\s*=>\s*ipcRenderer\.invoke\('skills:descartar',\s*nome\)/);
  assert.doesNotMatch(skillsMod, /innerHTML/);
  assert.match(app, /criarGerenciadorSkills/);
  assert.match(app, /\$\('skillsRefresh'\)\.onclick = carregarSkills;/);
  assert.match(app, /carregarSkills\(\);/);
  assert.match(mock, /skillsListar:/);
  assert.match(mock, /skillsAprovar:/);
  assert.match(mock, /skillsDescartar:/);
  assert.match(html, /id="skillsBlock"/);
  assert.match(preview, /id="skillsBlock"/);
  assert.match(css, /\.skill-card\[data-estado="pendente"\]/);
  assert.match(css, /\.skill-badge\[data-estado="pendente"\]/);
  assert.ok(pkg.build.files.includes('site/src/skills.js'));
});
