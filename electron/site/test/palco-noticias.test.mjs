import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPalcoNoticias } from '../src/palco-noticias.js';

function elementoSimulado(tag) {
  return {
    tag,
    type: '',
    className: '',
    textContent: '',
    src: '',
    alt: '',
    hidden: false,
    offsetWidth: 100,
    filhos: [],
    attrs: {},
    classes: new Set(),
    style: { props: {}, setProperty(k, v) { this.props[k] = v; } },
    classList: null,
    onclick: null,
    addEventListener() {},
    setAttribute(k, v) { this.attrs[k] = v; },
    append(...itens) { this.filhos.push(...itens); },
    replaceChildren(...itens) { this.filhos = [...itens]; },
  };
}

function docSimulado() {
  return {
    createElement(tag) {
      const el = elementoSimulado(tag);
      el.classList = {
        add: c => el.classes.add(c),
        remove: c => el.classes.delete(c),
        toggle: (c, f) => (f ? el.classes.add(c) : el.classes.delete(c)),
        contains: c => el.classes.has(c),
      };
      return el;
    },
  };
}

function buscarImgs(no) {
  const lista = [];
  if (no.tag === 'img') lista.push(no);
  for (const filho of no.filhos || []) lista.push(...buscarImgs(filho));
  return lista;
}

test('palco-noticias renderiza 5 matérias sem repetir imagem e alterna destaque no clique', async () => {
  const doc = docSimulado();
  const corpo = doc.createElement('div');
  const abertas = [];
  const selecionadas = [];

  const dados = {
    tipo: 'noticias',
    itens: [
      { titulo: 'Manchete 1', resumo: 'Resumo 1', imagem: 'https://cdn/1.jpg', url: 'https://g1/1', fonte: 'g1.globo.com' },
      { titulo: 'Manchete 2', resumo: 'Resumo 2', imagem: 'https://cdn/1.jpg', url: 'https://g1/2', fonte: 'g1.globo.com' },
      { titulo: 'Manchete 3', resumo: 'Resumo 3', imagem: 'https://cdn/3.jpg', url: 'https://g1/3', fonte: 'ge.globo.com' },
      { titulo: 'Manchete 4', resumo: 'Resumo 4', imagem: 'https://cdn/4.jpg', url: 'https://g1/4', fonte: 'g1.globo.com' },
      { titulo: 'Manchete 5', resumo: 'Resumo 5', imagem: 'https://cdn/5.jpg', url: 'https://g1/5', fonte: 'g1.globo.com' },
    ],
  };

  const ctrl = renderPalcoNoticias({
    corpo,
    dados,
    doc,
    onSelectItem: (item, idx) => selecionadas.push([idx, item.titulo]),
    abrirExterno: url => { abertas.push(url); return true; },
  });

  assert.equal(ctrl.itens.length, 5);
  assert.equal(selecionadas[0][0], 0);
  // Item 2 tinha imagem duplicada da 1 -> deve ter sido limpa para fallback visual único
  assert.equal(ctrl.itens[1].imagem, '');

  const palcoWrap = corpo.filhos[0];
  const hero = palcoWrap.filhos[0];
  const rail = palcoWrap.filhos[1];
  assert.equal(rail.filhos.length, 5);

  // Nenhum <img> repetido entre os 5 cartões da lista
  const srcsThumb = buscarImgs(rail).map(i => i.src);
  assert.equal(srcsThumb.length, new Set(srcsThumb).size);
  assert.deepEqual(srcsThumb, ['https://cdn/1.jpg', 'https://cdn/3.jpg', 'https://cdn/4.jpg', 'https://cdn/5.jpg']);

  // Clicar no cartão 3 atualiza o destaque, aplica is-swapping e muda o link ativo
  rail.filhos[2].onclick();
  assert.equal(selecionadas.at(-1)[0], 2);
  assert.equal(selecionadas.at(-1)[1], 'Manchete 3');
  assert.equal(hero.classes.has('is-swapping'), true);
  assert.equal(buscarImgs(hero.filhos[0])[0].src, 'https://cdn/3.jpg');

  // CTA abre a matéria selecionada (#3)
  const meta = hero.filhos[1];
  const cta = meta.filhos[3].filhos[0];
  cta.onclick();
  assert.deepEqual(abertas, ['https://g1/3']);
});
