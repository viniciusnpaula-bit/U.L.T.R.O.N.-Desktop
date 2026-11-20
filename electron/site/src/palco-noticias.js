/* Palco de notícias: destaque editorial + seletor individual de cada matéria.
   Cada matéria preserva sua própria imagem e alterna por clique ou teclado
   com transição suave de foco e foco luminoso (Spotlight). */

function urlSegura(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url.trim()) ? url.trim() : '';
}

function limparDominio(url, fonteExplicita = '') {
  if (typeof fonteExplicita === 'string' && fonteExplicita.trim()) {
    return fonteExplicita.trim();
  }
  try {
    const host = new URL(url).hostname || '';
    return host.replace(/^www\./i, '');
  } catch {
    return '';
  }
}

function ativarSpotlight(cartao) {
  if (!cartao || typeof cartao.addEventListener !== 'function') return;
  cartao.addEventListener('pointermove', evento => {
    if (typeof cartao.getBoundingClientRect !== 'function') return;
    const ret = cartao.getBoundingClientRect();
    if (!ret.width || !ret.height) return;
    cartao.style.setProperty('--spot-x', `${Math.round(evento.clientX - ret.left)}px`);
    cartao.style.setProperty('--spot-y', `${Math.round(evento.clientY - ret.top)}px`);
  });
}

function criarVisualEditorial(doc, indice, fonte, titulo) {
  const bloco = doc.createElement('div');
  bloco.className = 'palco-news-visual';

  const selo = doc.createElement('span');
  selo.className = 'palco-news-visual-idx';
  selo.textContent = String(indice + 1).padStart(2, '0');

  const seloFonte = doc.createElement('span');
  seloFonte.className = 'palco-news-visual-host';
  seloFonte.textContent = fonte || 'feed rss';

  const monograma = doc.createElement('span');
  monograma.className = 'palco-news-visual-mark';
  monograma.setAttribute('aria-hidden', 'true');
  monograma.textContent = String(titulo || fonte || 'N').trim().slice(0, 1).toUpperCase();

  bloco.append(selo, monograma, seloFonte);
  return bloco;
}

function montarMidia({ doc, item, indice, fonte, className }) {
  const moldura = doc.createElement('div');
  moldura.className = className;
  const imgUrl = urlSegura(item.imagem);

  const fallback = () => criarVisualEditorial(doc, indice, fonte, item.titulo);
  if (!imgUrl) {
    moldura.append(fallback());
    return moldura;
  }

  const img = doc.createElement('img');
  img.src = imgUrl;
  img.alt = item.titulo || `Notícia ${indice + 1}`;
  img.decoding = 'async';
  img.loading = indice === 0 ? 'eager' : 'lazy';
  img.referrerPolicy = 'no-referrer';
  img.addEventListener('error', () => {
    moldura.replaceChildren(fallback());
  });
  moldura.append(img);
  return moldura;
}

export function renderPalcoNoticias({
  corpo,
  dados,
  onSelectItem = () => {},
  abrirExterno = async () => false,
  doc = document,
}) {
  const listaBruta = Array.isArray(dados?.itens) ? dados.itens : [];
  const itens = listaBruta
    .filter(item => item && typeof item.titulo === 'string' && item.titulo.trim())
    .slice(0, 6);

  if (!itens.length) {
    const aviso = doc.createElement('p');
    aviso.className = 'palco-aviso';
    aviso.textContent = 'Nenhuma matéria disponível para exibir agora.';
    corpo.append(aviso);
    return null;
  }

  // Garante na camada visual que duas matérias jamais compartilhem a mesma imagem.
  const imgsVistas = new Set();
  const itensUnicos = itens.map(item => {
    const imgUrl = urlSegura(item.imagem);
    const duplicada = imgUrl && imgsVistas.has(imgUrl);
    if (imgUrl && !duplicada) imgsVistas.add(imgUrl);
    return {
      ...item,
      imagem: duplicada ? '' : imgUrl,
      url: urlSegura(item.url),
      fonte: limparDominio(item.url, item.fonte),
    };
  });

  const palcoWrap = doc.createElement('div');
  palcoWrap.className = 'palco-news';
  palcoWrap.setAttribute('role', 'region');
  palcoWrap.setAttribute('aria-label', 'Destaques de notícias');

  const hero = doc.createElement('article');
  hero.className = 'palco-news-hero';
  ativarSpotlight(hero);

  const heroMediaSlot = doc.createElement('div');
  heroMediaSlot.className = 'palco-news-hero-media';

  const heroMeta = doc.createElement('div');
  heroMeta.className = 'palco-news-meta';

  const kicker = doc.createElement('div');
  kicker.className = 'palco-news-kicker';
  const badgeIdx = doc.createElement('span');
  badgeIdx.className = 'palco-news-count';
  const badgeFonte = doc.createElement('span');
  badgeFonte.className = 'palco-news-source';
  const badgeHora = doc.createElement('span');
  badgeHora.className = 'palco-news-time';
  kicker.append(badgeIdx, badgeFonte, badgeHora);

  const heroTitulo = doc.createElement('h3');
  heroTitulo.className = 'palco-news-title';

  const heroResumo = doc.createElement('p');
  heroResumo.className = 'palco-news-summary';

  const acoesHero = doc.createElement('div');
  acoesHero.className = 'palco-news-actions';
  const cta = doc.createElement('button');
  cta.type = 'button';
  cta.className = 'palco-news-cta';
  cta.textContent = 'ler matéria completa';
  let itemAtual = itensUnicos[0];
  cta.onclick = () => {
    if (itemAtual?.url) abrirExterno(itemAtual.url);
  };
  acoesHero.append(cta);

  heroMeta.append(kicker, heroTitulo, heroResumo, acoesHero);
  hero.append(heroMediaSlot, heroMeta);

  const rail = doc.createElement('div');
  rail.className = 'palco-news-rail';
  rail.setAttribute('role', 'listbox');
  rail.setAttribute('aria-label', 'Lista de notícias');

  let ativo = 0;
  const botoes = [];

  function aplicarDestaque(indice, { animar = true } = {}) {
    ativo = Math.max(0, Math.min(itensUnicos.length - 1, indice));
    const item = itensUnicos[ativo];
    itemAtual = item;

    if (animar && hero.classList) {
      hero.classList.remove('is-swapping');
      void hero.offsetWidth;
      hero.classList.add('is-swapping');
    }

    const midia = montarMidia({
      doc,
      item,
      indice: ativo,
      fonte: item.fonte,
      className: 'palco-news-media',
    });
    heroMediaSlot.replaceChildren(midia);

    badgeIdx.textContent = `${String(ativo + 1).padStart(2, '0')} / ${String(itensUnicos.length).padStart(2, '0')}`;
    badgeFonte.textContent = item.fonte || 'notícias';
    badgeHora.textContent = item.publicado || '';
    badgeHora.hidden = !item.publicado;

    heroTitulo.textContent = item.titulo;
    heroResumo.textContent = item.resumo || 'Clique para abrir a cobertura completa no navegador.';
    cta.hidden = !item.url;
    cta.setAttribute('aria-label', `Ler matéria completa: ${item.titulo}`);

    botoes.forEach((btn, idx) => {
      const ligado = idx === ativo;
      btn.setAttribute('aria-selected', String(ligado));
      btn.classList.toggle('is-active', ligado);
    });

    onSelectItem(item, ativo);
  }

  itensUnicos.forEach((item, idx) => {
    const cartao = doc.createElement('button');
    cartao.type = 'button';
    cartao.className = 'palco-news-card';
    cartao.setAttribute('role', 'option');
    cartao.setAttribute('aria-selected', String(idx === 0));
    cartao.setAttribute('aria-label', item.titulo);
    ativarSpotlight(cartao);

    const thumb = montarMidia({
      doc,
      item,
      indice: idx,
      fonte: item.fonte,
      className: 'palco-news-thumb',
    });

    const info = doc.createElement('div');
    info.className = 'palco-news-card-body';

    const topo = doc.createElement('div');
    topo.className = 'palco-news-card-meta';
    const num = doc.createElement('span');
    num.className = 'palco-news-card-num';
    num.textContent = String(idx + 1).padStart(2, '0');
    const fonte = doc.createElement('span');
    fonte.className = 'palco-news-card-src';
    fonte.textContent = item.fonte || 'notícias';
    topo.append(num, fonte);

    const linhaTitulo = doc.createElement('span');
    linhaTitulo.className = 'palco-news-card-title';
    linhaTitulo.textContent = item.titulo;

    info.append(topo, linhaTitulo);
    cartao.append(thumb, info);

    cartao.onclick = () => aplicarDestaque(idx, { animar: idx !== ativo });
    cartao.addEventListener('keydown', evento => {
      if (evento.key === 'ArrowDown' || evento.key === 'ArrowRight') {
        evento.preventDefault();
        const proximo = (idx + 1) % itensUnicos.length;
        botoes[proximo]?.focus();
        aplicarDestaque(proximo);
      } else if (evento.key === 'ArrowUp' || evento.key === 'ArrowLeft') {
        evento.preventDefault();
        const anterior = (idx - 1 + itensUnicos.length) % itensUnicos.length;
        botoes[anterior]?.focus();
        aplicarDestaque(anterior);
      }
    });

    botoes.push(cartao);
    rail.append(cartao);
  });

  palcoWrap.append(hero, rail);
  corpo.append(palcoWrap);
  aplicarDestaque(0, { animar: false });
  return { selecionar: aplicarDestaque, itens: itensUnicos };
}
