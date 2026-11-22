/* Pré-visualização local da interface: mock do núcleo para ver a tela no navegador.
   Não faz parte do app; o Electron injeta a ponte real (preload.js). */
const verbose = new URLSearchParams(location.search).has('live');
let estadoVersao = '3.0.0';
let jobUpdate = null;
const agora = () => Date.now() / 1000;
const status = () => ({
  core_running: true, api_running: true,
  session_desbloqueada: true,
  microphone_paused: false, microphone_capturing: true, microphone_state: 'ouvindo',
  microphone_threshold: 400, microphone_level: 180 + 220 * (0.5 + 0.5 * Math.sin(agora() * 1.7)),
  cpu_percent: 23, ram_percent: 58, disk_percent: 71,
  autostart_installed: true, speaking: false,
});
const fila = [];
const previewSkills = {
  skills: [
    { slug: 'rotina-matinal', nome: 'Rotina matinal', descricao: 'Resumo diário de agenda e clima.', quando: 'quando o usuário pedir resumo da manhã', estado: 'ativo' },
  ],
  pendentes: [
    { slug: 'modo-foco', nome: 'Modo foco', quando: 'quando pedir foco no trabalho', corpo: '1. Pausar notificações\n2. Minimizar janelas secundárias' },
  ],
};
window.ultron = {
  health: async () => ({ ok: true }),
  status: async () => status(),
  events: async () => ({ events: fila.splice(0) }),
  command: async text => {
    const id = `op-${Math.random().toString(36).slice(2, 8)}`;
    setTimeout(() => fila.push({
      type: 'command_result', operation_id: id,
      response: text.toLowerCase().includes('abr') ? 'Abrindo agora, senhor.' :
        'Às ordens. Registrei o comando e o núcleo respondeu no canal local.',
    }), 900);
    return { operation_id: id };
  },
  microphone: async paused => ({ paused }),
  conversation: async () => ({ turns: [] }),
  clearConversation: async () => ({ ok: true }),
  version: '3.0.0',
  updateInfo: async () => ({ current_version: '3.0.0', auto_check: false, job: null }),
  updateCheck: async () => ({ status: 'ok', current_version: '3.0.0', latest_version: '3.0.0', update_available: false, notes: '' }),
  updateApply: async () => ({ status: 'baixando' }),
  updateLaunch: async () => true,
  updateRollback: async () => true,
  setZoom: async () => false,
  microphones: async () => ({
    devices: [{ id: null, name: 'Padrão do sistema' }, { id: '["WASAPI","Microfone USB",0]', name: 'Microfone USB' }],
    selected_id: null, selected_name: 'Padrão do sistema', selected_available: true, active_name: 'Padrão do sistema',
  }),
  selectMicrophone: async id => ({ selected_name: 'Microfone USB', active_name: 'Microfone USB' }),
  confirmation: async () => true,
  emergencyStop: async () => true,
  setAutostart: async enabled => ({ autostart_installed: enabled === true }),
  shutdown: async () => true,
  quitApp: async () => true,
  toggleHud: async () => true,
  publishHudSnapshot: async () => true,
  onHudVisibility: () => () => {},
  onHudAction: () => () => {},
  onHudCommand: () => () => {},
  hudActionResult: () => {},
  undoList: async () => ({
    limite: 10,
    itens: [
      { id: 'a'.repeat(12), operacao: 'arquivo.apagar', resumo: 'apagar C:\\Users\\você\\Downloads\\nota.txt', desfeito: false, criado: agora() - 120 },
      { id: 'b'.repeat(12), operacao: 'arquivo.mover', resumo: 'mover 3 arquivos para a pasta Projetos', desfeito: false, criado: agora() - 900 },
      { id: 'c'.repeat(12), operacao: 'arquivo.extrair', resumo: 'extrair pacote.zip', desfeito: true, criado: agora() - 3600 },
    ],
  }),
  unlockInfo: async () => ({
    session: { desbloqueada: true, metodo: 'pin', desde: agora() - 60 },
    hello: { disponivel: true, motivo: 'Windows Hello pronto' },
    pin_configurado: true,
    irreversiveis: ['apagar_arquivo', 'executar_comando'],
    versao: '3.0.0',
    historico: { cifrado: true, algoritmo: 'AES-256-GCM', chave: 'DPAPI', migrado: true },
  }),
  unlockHello: async () => ({ unlocked: true, method: 'hello' }),
  unlockPin: async () => ({ unlocked: true, method: 'pin' }),
  lock: async () => ({ locked: true }),
  onSessionLocked: () => () => {},
  personalidadeInfo: async () => ({
    atual: { perfil: 'ultron', jeito: 'equilibrado', tratamento: 'senhor', saudacao: true,
      usuario: { nome: '', apelido: '', idade: '', genero: '', sobre: '' } },
    perfis: [{ id: 'ultron', rotulo: 'U.L.T.R.O.N.', tratamento: 'senhor' }],
    jeitos: [{ id: 'equilibrado', rotulo: 'Equilibrado', descricao: 'O padrão.' }],
  }),
  personalidadeSalvar: async valores => ({ perfil: 'ultron', jeito: 'equilibrado',
    tratamento: 'senhor', saudacao: true, usuario: {}, ...valores }),
  personalidadeRestaurar: async () => ({ perfil: 'ultron', jeito: 'equilibrado', tratamento: 'senhor',
    saudacao: true, usuario: {} }),
  personalidadePrevia: async () => ({ instrucao: 'Prévia local.' }),
  vozInfo: async () => ({ vozes: [], ativa: { nome: 'Padrão' } }),
  vozSalvar: async valores => valores,
  vozRestaurar: async () => ({ ok: true }),
  vozTestar: async () => ({ ok: true }),
  microfoneTestar: async () => ({ ok: true }),
  cofreStatus: async () => ({ itens: [] }),
  cofreGuardar: async () => ({ ok: true }),
  cofreRemover: async () => ({ ok: true }),
  cofreTestar: async () => ({ ok: true }),
  fatosListar: async busca => ({ fatos: [], limite: 50 }),
  fatoCorrigir: async () => ({ ok: true }),
  fatoApagar: async () => ({ ok: true }),
  lembreteCancelar: async () => ({ ok: true }),
  lembretesListar: async () => ({ lembretes: [] }),
  agendaListar: async () => ({ eventos: [], aviso: '' }),
  agendaCancelar: async () => ({ eventos: [], mensagem: '' }),
  fluxosListar: async () => ({ fluxos: [] }),
  executarFluxo: async id => ({ operation_id: `preview-${id}` }),
  skillsListar: async () => ({
    skills: previewSkills.skills.map(s => ({ ...s })),
    pendentes: previewSkills.pendentes.map(p => ({ ...p })),
  }),
  skillsAprovar: async nome => {
    const idx = previewSkills.pendentes.findIndex(p => p.slug === nome);
    if (idx === -1) throw new Error('A API local recusou a solicitação (409).');
    const [item] = previewSkills.pendentes.splice(idx, 1);
    previewSkills.skills.push({ slug: item.slug, nome: item.nome, descricao: item.quando, quando: item.quando, estado: 'ativo' });
    return { ok: true, slug: nome };
  },
  skillsDescartar: async nome => {
    const idx = previewSkills.pendentes.findIndex(p => p.slug === nome);
    if (idx !== -1) previewSkills.pendentes.splice(idx, 1);
    return { ok: true };
  },
  abrirLink: async () => true,
  abrirExterno: async () => true,
  palcoFechar: async () => true,
  palcoAbrir: async () => true,
  bloco1Status: async () => ({
    config: {
      downloads_pdf_ativo: true,
      downloads_extrator_ativo: true,
      capturas_desktop_ativo: true,
      usb_ejetar_ativo: true,
      disco_alerta_ativo: true,
      disco_limite_pct: 80,
      projetos_pastas: [],
      backup_origens: [],
      backup_destino: ""
    },
    status_monitores: { ativo: true, ultimo_relatorio: "monitores ativos" },
    admin_elevated: true,
    admin_mode: true
  }),
  bloco1Salvar: async config => ({ sucesso: true, config }),
  bloco1Executar: async (acao, params) => ({ sucesso: true, acao, resultado: "simulado" }),
  bloco2Status: async () => ({
    config: {
      suspensao_abas_ativo: true,
      matar_travados_ativo: true,
      otimizar_janela_ativa_ativo: true,
      plano_energia_ativo: true,
      protecao_termica_ativo: true,
      guardiao_startup_ativo: true,
      limpar_ram_ativo: true
    },
    status_monitores: { ativo: true, ultimo_relatorio: "monitores bloco 2 ativos" },
    temperatura_cpu: 48.5,
    plano_ativo: "Equilibrado",
    admin_elevated: true,
    admin_mode: true
  }),
  bloco2Salvar: async config => ({ sucesso: true, config }),
  bloco2Executar: async (acao, params) => ({ sucesso: true, acao, resultado: "simulado" }),
};
/* modo ?chat: simula uma conversa de voz chegando, para ver o bat-papo */
if (new URLSearchParams(location.search).has('chat')) {
  const falas = [
    ['user', 'Ei, Ultron, qual é a previsão do tempo para amanhã?'],
    ['assistant', 'Amanhã fica nublado pela manhã, com máxima de 27 graus e chance de chuva à tarde.'],
    ['user', 'Ative o modo jogo.'],
    ['assistant', 'Modo jogo ativado: janelas minimizadas e Rocket League aberto.'],
  ];
  /* mesma linha do tempo para todos, sem aleatoriedade */
  falas.forEach(([role, text], indice) => {
    setTimeout(() => fila.push({ type: 'conversation_turn', role, text, source: 'voz', at: Date.now() / 1000 }), 900 + indice * 1600);
  });
}
if (verbose) {
  /* cliques na prévia: um comando de exemplo após 1,2 s para ver a resposta chegando */
  setTimeout(() => {
    const form = document.getElementById('consoleForm');
    document.getElementById('commandInput').value = 'Ei, Ultron, abra o navegador';
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  }, 1200);
  setTimeout(() => {
    document.querySelector('[data-command="Abra o Rocket League"]')?.click();
  }, 3600);
  setTimeout(() => document.getElementById('openSettings').click(), 5600);
}
