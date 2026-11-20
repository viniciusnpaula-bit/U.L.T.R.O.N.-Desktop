import test from 'node:test';
import assert from 'node:assert/strict';
import { criarPainelPersonalidade } from '../src/personalidade-painel.js';
import { criarPainelMemoria } from '../src/memoria-painel.js';
import { criarPainelBlocos } from '../src/bloco12-painel.js';

function criarDomSimulado() {
  const mapa = new Map();
  function obter(id) {
    if (!mapa.has(id)) {
      mapa.set(id, {
        id,
        value: '',
        checked: false,
        textContent: '',
        className: '',
        filhos: [],
        attrs: {},
        onclick: null,
        setAttribute(k, v) { this.attrs[k] = v; },
        addEventListener() {},
        append(...itens) { this.filhos.push(...itens); },
        replaceChildren(...itens) { this.filhos = [...itens]; },
      });
    }
    return mapa.get(id);
  }
  const doc = {
    querySelectorAll: () => [],
    createElement: tag => ({
      tag,
      type: '',
      className: '',
      textContent: '',
      title: '',
      dataset: {},
      filhos: [],
      attrs: {},
      onclick: null,
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener() {},
      append(...itens) { this.filhos.push(...itens); },
    }),
  };
  return { $, doc };
  function $(id) { return obter(id); }
}

test('personalidade-painel preserva tratamentos já salvos por perfil e troca corretamente', async () => {
  const { $, doc } = criarDomSimulado();
  const bridge = () => ({
    personalidadeInfo: async () => ({
      atual: {
        perfil: 'ultron',
        jeito: 'equilibrado',
        tratamento: 'Senhor',
        tratamentos: { ultron: 'Senhor', jarvis: 'Chefe' },
        saudacao: true,
        usuario: { nome: 'Ana' },
      },
      perfis: [
        { id: 'ultron', tratamento: 'Padrão' },
        { id: 'jarvis', tratamento: 'Sir' },
        { id: 'sexta', tratamento: 'Mestre' },
      ],
      jeitos: [{ id: 'equilibrado', rotulo: 'Equilibrado', descricao: 'Neutro' }],
    }),
  });

  const painel = criarPainelPersonalidade({ $, bridge, doc });
  await painel.carregarPersonalidade();
  assert.equal($('tratamentoInput').value, 'Senhor');
  assert.equal($('userName').value, 'Ana');

  painel.pintarPerfil('jarvis');
  assert.equal($('tratamentoInput').value, 'Chefe');

  painel.pintarPerfil('sexta');
  assert.equal($('tratamentoInput').value, 'Mestre');
});

test('personalidade-painel isola jeito por perfil e notifica mudança para sincronizar tema', async () => {
  const { $, doc } = criarDomSimulado();
  const perfisMudados = [];
  const salvamentos = [];
  const estado = {
    perfil: 'ultron',
    jeito: 'equilibrado',
    tratamento: 'senhor',
    tratamentos: { ultron: 'senhor', jarvis: 'chefe', visao: 'capitão', edith: 'chefe' },
    jeitos: { ultron: 'equilibrado', jarvis: 'equilibrado', visao: 'equilibrado', edith: 'equilibrado' },
  };
  const bridge = () => ({
    personalidadeInfo: async () => ({
      atual: { ...estado },
      perfis: Object.keys(estado.tratamentos).map(id => ({
        id,
        tratamento: estado.tratamentos[id],
        jeito: estado.jeitos[id],
      })),
      jeitos: [
        { id: 'equilibrado', rotulo: 'Equilibrado', descricao: 'Neutro' },
        { id: 'sarcastico', rotulo: 'Sarcástico', descricao: 'Irônico' },
        { id: 'mordomo', rotulo: 'Mordomo', descricao: 'Clássico' },
      ],
    }),
    personalidadeSalvar: async (dados) => {
      salvamentos.push(dados);
      const perfil = dados.perfil || estado.perfil;
      estado.perfil = perfil;
      if (dados.jeito) estado.jeitos[perfil] = dados.jeito;
      if (dados.tratamento) estado.tratamentos[perfil] = dados.tratamento;
      estado.jeito = estado.jeitos[perfil];
      estado.tratamento = estado.tratamentos[perfil];
      return {
        ...estado,
        tratamentos: { ...estado.tratamentos },
        jeitos: { ...estado.jeitos },
      };
    },
  });

  const painel = criarPainelPersonalidade({
    $,
    bridge,
    doc,
    onPerfilMudou: p => perfisMudados.push(p),
  });
  await painel.carregarPersonalidade();
  assert.equal($('headerStyle').textContent, 'Equilibrado');

  await painel.escolherJeito('sarcastico');
  assert.equal($('headerStyle').textContent, 'Sarcástico');
  assert.equal(estado.jeitos.ultron, 'sarcastico');

  await painel.selecionarPerfil('jarvis');
  assert.deepEqual(salvamentos.at(-1), { perfil: 'jarvis' });
  assert.equal($('headerStyle').textContent, 'Equilibrado');
  assert.equal($('headerProfile').textContent, 'JARVIS');

  await painel.escolherJeito('mordomo');
  await painel.selecionarPerfil('ultron');
  assert.equal($('headerStyle').textContent, 'Sarcástico');
  assert.deepEqual(perfisMudados, ['ultron', 'ultron', 'jarvis', 'jarvis', 'jarvis', 'ultron', 'ultron']);
});

test('memoria-painel carrega fatos, lembretes e agenda mantendo notas corretas', async () => {
  const { $, doc } = criarDomSimulado();
  const bridge = () => ({
    fatosListar: async () => ({ fatos: [{ id: 1, texto: 'prefere café' }], limite: 100 }),
    lembretesListar: async () => ({ lembretes: [], aviso: 'limpo' }),
    agendaListar: async () => ({
      eventos: [{ numero: 1, hora_local: '10:00', texto: 'reunião', repetir_minutos: 60 }],
      aviso: 'ok',
    }),
  });

  const painel = criarPainelMemoria({ $, bridge, win: {}, doc });
  await painel.carregarFatos();
  assert.equal($('factsList').filhos.length, 1);
  assert.match($('factsNote').textContent, /1 de até 100 fatos/);

  await painel.carregarLembretes();
  assert.equal($('lembretesNote').textContent, 'limpo');

  await painel.carregarAgenda();
  assert.equal($('agendaList').filhos.length, 1);
  assert.match($('agendaNote').textContent, /1 evento\(s\) · ok/);
});

test('bloco12-painel preenche switches/inputs e vincula controles sem depender de app.js', async () => {
  const { $ } = criarDomSimulado();
  const mensagens = [];
  const bridge = () => ({
    bloco1Status: async () => ({
      config: {
        downloads_pdf_ativo: true,
        downloads_extrator_ativo: false,
        capturas_desktop_ativo: true,
        usb_ejetar_ativo: false,
        disco_alerta_ativo: true,
        projetos_pastas: ['C:\\ProjA', 'C:\\ProjB'],
        backup_origens: ['C:\\Docs'],
        backup_destino: 'D:\\Backup',
      },
      status_monitores: { ultimo_relatorio: 'disco ok' },
    }),
    bloco2Status: async () => ({
      config: {
        suspensao_abas_ativo: true,
        matar_travados_ativo: true,
        otimizar_janela_ativa_ativo: false,
        plano_energia_ativo: true,
        protecao_termica_ativo: false,
        guardiao_startup_ativo: true,
        limpar_ram_ativo: false,
      },
      temperatura_cpu: 61,
      plano_ativo: 'Equilibrado',
      status_monitores: { ultimo_relatorio: 'processos ok' },
    }),
  });

  const painel = criarPainelBlocos({ $, transport: {}, toast: m => mensagens.push(m), bridge });
  painel.vincularControles();
  assert.equal(typeof $('bloco1Refresh').onclick, 'function');
  assert.equal(typeof $('bloco2Refresh').onclick, 'function');

  await painel.carregarBloco1();
  assert.equal($('switchBloco1Pdf').checked, true);
  assert.equal($('inputBloco1Projetos').value, 'C:\\ProjA; C:\\ProjB');
  assert.equal($('statusBloco1Relatorio').textContent, 'disco ok');

  await painel.carregarBloco2();
  assert.equal($('switchBloco2Abas').checked, true);
  assert.equal($('valBloco2Temp').textContent, '61 °C');
  assert.equal($('valBloco2Plano').textContent, 'Equilibrado');
  assert.equal($('statusBloco2Relatorio').textContent, 'processos ok');
});
