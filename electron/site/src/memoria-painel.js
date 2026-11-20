/* Painel de memória: fatos, lembretes e agenda (somente leitura/confirmação explícita). */

export function criarPainelMemoria({
  $,
  bridge = () => window.ultron,
  win = window,
  doc = document,
}) {
  function notaFatos(texto, classe = '') {
    const alvo = $('factsNote');
    alvo.textContent = texto;
    alvo.className = `micro nano ${classe}`;
  }

  function fatoLinha(fato) {
    const item = doc.createElement('div');
    item.className = 'fact';
    item.dataset.id = String(fato.id);
    const texto = doc.createElement('p');
    texto.textContent = fato.texto;
    const acoes = doc.createElement('div');
    acoes.className = 'fact-actions';

    const editar = doc.createElement('button');
    editar.type = 'button';
    editar.textContent = 'editar';
    editar.title = 'Corrigir este fato';
    editar.onclick = async () => {
      const novo = win.prompt('Corrigir o fato:', fato.texto);
      if (novo === null) return;
      const limpo = novo.trim();
      if (!limpo || limpo === fato.texto) return;
      try {
        const r = await bridge().fatoCorrigir(fato.id, limpo);
        pintarFatos(r.fatos, 'fato corrigido.');
      } catch (error) {
        notaFatos(`não consegui corrigir (${error.message})`, 'err');
      }
    };

    const apagar = doc.createElement('button');
    apagar.type = 'button';
    apagar.textContent = 'apagar';
    apagar.title = 'Apagar este fato';
    apagar.onclick = async () => {
      if (!win.confirm(`Apagar este fato?\n\n“${fato.texto}”`)) return;
      try {
        const r = await bridge().fatoApagar(fato.id);
        pintarFatos(r.fatos, 'fato apagado.');
      } catch (error) {
        notaFatos(`não consegui apagar (${error.message})`, 'err');
      }
    };

    acoes.append(editar, apagar);
    item.append(texto, acoes);
    return item;
  }

  function pintarFatos(fatos, aviso = '') {
    const lista = $('factsList');
    lista.replaceChildren();
    if (!fatos || !fatos.length) {
      const vazio = doc.createElement('span');
      vazio.className = 'micro nano';
      const termo = $('factsSearch')?.value?.trim();
      vazio.textContent = termo ? 'nenhum fato encontrado' : 'nenhum fato guardado';
      lista.append(vazio);
    } else {
      for (const fato of fatos) lista.append(fatoLinha(fato));
    }
    if (aviso) notaFatos(`${aviso} (${fatos?.length ?? 0} guardados)`, 'ok');
  }

  async function carregarFatos() {
    try {
      const r = await bridge().fatosListar($('factsSearch').value.trim());
      pintarFatos(r.fatos, '');
      notaFatos(`${r.fatos.length} de até ${r.limite} fatos`);
    } catch (error) {
      notaFatos(`não consegui ler a memória (${error.message})`, 'err');
    }
  }

  function paginaLembretes(itens, aviso = '') {
    const lista = $('lembretesList');
    lista.replaceChildren();
    if (!itens || !itens.length) {
      const vazio = doc.createElement('span');
      vazio.className = 'micro nano';
      vazio.textContent = 'nenhum lembrete pendente';
      lista.append(vazio);
    }
    for (const item of itens || []) {
      const linha = doc.createElement('div');
      linha.className = 'fact';
      const texto = doc.createElement('p');
      texto.textContent = `${item.hora_local} — ${item.texto}`;
      const acoes = doc.createElement('div');
      acoes.className = 'fact-actions';
      const cancelar = doc.createElement('button');
      cancelar.type = 'button';
      cancelar.textContent = 'cancelar';
      cancelar.title = 'Apagar este lembrete';
      cancelar.onclick = async () => {
        if (!win.confirm(`Cancelar o lembrete “${item.texto}”?`)) return;
        try {
          const r = await bridge().lembreteCancelar(item.numero, '');
          paginaLembretes(r.lembretes, r.mensagem);
        } catch (error) {
          $('lembretesNote').textContent = `não consegui cancelar (${error.message})`;
        }
      };
      acoes.append(cancelar);
      linha.append(texto, acoes);
      lista.append(linha);
    }
    if (aviso) $('lembretesNote').textContent = `${aviso} · ${(itens || []).length} pendente(s)`;
  }

  async function carregarLembretes() {
    try {
      const r = await bridge().lembretesListar();
      paginaLembretes(r.lembretes, '');
      $('lembretesNote').textContent = (r.lembretes || []).length
        ? `${r.lembretes.length} pendente(s) · ${r.aviso}`
        : r.aviso;
    } catch {
      $('lembretesNote').textContent = 'não consegui ler os lembretes';
    }
  }

  function paginaAgenda(itens, aviso = '') {
    const lista = $('agendaList');
    lista.replaceChildren();
    if (!itens || !itens.length) {
      const vazio = doc.createElement('span');
      vazio.className = 'micro nano';
      vazio.textContent = 'nenhum evento na agenda';
      lista.append(vazio);
    }
    for (const item of itens || []) {
      const linha = doc.createElement('div');
      linha.className = 'fact';
      const texto = doc.createElement('p');
      const repeticao = item.repetir_minutos > 0 ? ` (repete a cada ${item.repetir_minutos} min)` : '';
      texto.textContent = `${item.hora_local} — ${item.texto}${repeticao}`;
      const acoes = doc.createElement('div');
      acoes.className = 'fact-actions';
      const cancelar = doc.createElement('button');
      cancelar.type = 'button';
      cancelar.textContent = 'cancelar';
      cancelar.title = 'Apagar este evento';
      cancelar.onclick = async () => {
        if (!win.confirm(`Cancelar o evento “${item.texto}”?`)) return;
        try {
          const r = await bridge().agendaCancelar(item.numero, '');
          paginaAgenda(r.eventos, r.mensagem);
        } catch (error) {
          $('agendaNote').textContent = `não consegui cancelar (${error.message})`;
        }
      };
      acoes.append(cancelar);
      linha.append(texto, acoes);
      lista.append(linha);
    }
    if (aviso) $('agendaNote').textContent = `${aviso} · ${(itens || []).length} evento(s)`;
  }

  async function carregarAgenda() {
    try {
      const r = await bridge().agendaListar();
      paginaAgenda(r.eventos, '');
      $('agendaNote').textContent = (r.eventos || []).length
        ? `${r.eventos.length} evento(s) · ${r.aviso}`
        : r.aviso;
    } catch {
      $('agendaNote').textContent = 'não consegui ler a agenda';
    }
  }

  return { carregarFatos, carregarLembretes, carregarAgenda };
}
