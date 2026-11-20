/* Painéis de automação do Bloco 1 (disco) e Bloco 2 (processos e hardware). */

export function criarPainelBlocos({
  $,
  transport,
  toast,
  bridge = () => window.ultron,
}) {
  async function carregarBloco1() {
    try {
      const ultron = bridge();
      const data = await (ultron?.bloco1Status ? ultron.bloco1Status() : transport.bloco1Status());
      if (!data || !data.config) return;
      const cfg = data.config;
      $('switchBloco1Pdf').checked = Boolean(cfg.downloads_pdf_ativo);
      $('switchBloco1Extrator').checked = Boolean(cfg.downloads_extrator_ativo);
      $('switchBloco1Prints').checked = Boolean(cfg.capturas_desktop_ativo);
      $('switchBloco1Usb').checked = Boolean(cfg.usb_ejetar_ativo);
      $('switchBloco1DiscoAuto').checked = Boolean(cfg.disco_alerta_ativo);
      $('inputBloco1Projetos').value = (cfg.projetos_pastas || []).join('; ');
      $('inputBloco1BackupOrigem').value = (cfg.backup_origens || []).join('; ');
      $('inputBloco1BackupDestino').value = cfg.backup_destino || '';
      if (data.status_monitores?.ultimo_relatorio) {
        $('statusBloco1Relatorio').textContent = data.status_monitores.ultimo_relatorio;
      }
    } catch (error) {
      $('statusBloco1Relatorio').textContent = `falha ao ler bloco 1: ${error.message}`;
    }
  }

  async function salvarBloco1() {
    const pastasProj = $('inputBloco1Projetos').value.split(';').map(s => s.trim()).filter(Boolean);
    const backupOrig = $('inputBloco1BackupOrigem').value.split(';').map(s => s.trim()).filter(Boolean);
    const novoCfg = {
      downloads_pdf_ativo: $('switchBloco1Pdf').checked,
      downloads_extrator_ativo: $('switchBloco1Extrator').checked,
      capturas_desktop_ativo: $('switchBloco1Prints').checked,
      usb_ejetar_ativo: $('switchBloco1Usb').checked,
      disco_alerta_ativo: $('switchBloco1DiscoAuto').checked,
      projetos_pastas: pastasProj,
      backup_origens: backupOrig,
      backup_destino: $('inputBloco1BackupDestino').value.trim(),
    };
    try {
      const ultron = bridge();
      const fn = ultron?.bloco1Salvar ? ultron.bloco1Salvar : transport.bloco1Salvar.bind(transport);
      await fn(novoCfg);
      toast('Configurações do Bloco 1 salvas.');
      $('statusBloco1Relatorio').textContent = 'configurações salvas com sucesso.';
    } catch (error) {
      toast(`Erro ao salvar: ${error.message}`);
      $('statusBloco1Relatorio').textContent = `erro: ${error.message}`;
    }
  }

  async function executarBloco1(acao, params = {}) {
    try {
      toast(`Executando ${acao.replace('_', ' ')}…`);
      const ultron = bridge();
      const fn = ultron?.bloco1Executar ? ultron.bloco1Executar : transport.bloco1Executar.bind(transport);
      const res = await fn(acao, params);
      if (res && res.sucesso) {
        toast('Ação concluída com sucesso.');
        $('statusBloco1Relatorio').textContent = `Ação ${acao} concluída com sucesso.`;
      } else {
        toast(`Falha: ${res?.erro || 'erro desconhecido'}`);
        $('statusBloco1Relatorio').textContent = `Falha em ${acao}: ${res?.erro || 'erro desconhecido'}`;
      }
    } catch (error) {
      toast(`Erro: ${error.message}`);
    }
  }

  async function carregarBloco2() {
    try {
      const ultron = bridge();
      const data = await (ultron?.bloco2Status ? ultron.bloco2Status() : transport.bloco2Status());
      if (!data || !data.config) return;
      const cfg = data.config;
      $('switchBloco2Abas').checked = Boolean(cfg.suspensao_abas_ativo);
      $('switchBloco2Travados').checked = Boolean(cfg.matar_travados_ativo);
      $('switchBloco2Janela').checked = Boolean(cfg.otimizar_janela_ativa_ativo);
      $('switchBloco2Energia').checked = Boolean(cfg.plano_energia_ativo);
      $('switchBloco2Termica').checked = Boolean(cfg.protecao_termica_ativo);
      $('switchBloco2Startup').checked = Boolean(cfg.guardiao_startup_ativo);
      $('switchBloco2Ram').checked = Boolean(cfg.limpar_ram_ativo);

      if (data.temperatura_cpu !== undefined && data.temperatura_cpu !== null) {
        $('valBloco2Temp').textContent = `${data.temperatura_cpu} °C`;
      }
      if (data.plano_ativo) {
        $('valBloco2Plano').textContent = data.plano_ativo;
      }
      if (data.status_monitores?.ultimo_relatorio) {
        $('statusBloco2Relatorio').textContent = data.status_monitores.ultimo_relatorio;
      }
    } catch (error) {
      $('statusBloco2Relatorio').textContent = `falha ao ler bloco 2: ${error.message}`;
    }
  }

  async function salvarBloco2() {
    const novoCfg = {
      suspensao_abas_ativo: $('switchBloco2Abas').checked,
      matar_travados_ativo: $('switchBloco2Travados').checked,
      otimizar_janela_ativa_ativo: $('switchBloco2Janela').checked,
      plano_energia_ativo: $('switchBloco2Energia').checked,
      protecao_termica_ativo: $('switchBloco2Termica').checked,
      guardiao_startup_ativo: $('switchBloco2Startup').checked,
      limpar_ram_ativo: $('switchBloco2Ram').checked,
    };
    try {
      const ultron = bridge();
      const fn = ultron?.bloco2Salvar ? ultron.bloco2Salvar : transport.bloco2Salvar.bind(transport);
      await fn(novoCfg);
      toast('Configurações do Bloco 2 salvas.');
      $('statusBloco2Relatorio').textContent = 'configurações salvas com sucesso.';
    } catch (error) {
      toast(`Erro ao salvar: ${error.message}`);
      $('statusBloco2Relatorio').textContent = `erro: ${error.message}`;
    }
  }

  async function executarBloco2(acao, params = {}) {
    try {
      toast(`Executando ${acao.replace('_', ' ')}…`);
      const ultron = bridge();
      const fn = ultron?.bloco2Executar ? ultron.bloco2Executar : transport.bloco2Executar.bind(transport);
      const res = await fn(acao, params);
      if (res && res.sucesso) {
        toast('Ação concluída com sucesso.');
        $('statusBloco2Relatorio').textContent = `Ação ${acao} concluída com sucesso.`;
        carregarBloco2();
      } else {
        toast(`Falha: ${res?.erro || 'erro desconhecido'}`);
        $('statusBloco2Relatorio').textContent = `Falha em ${acao}: ${res?.erro || 'erro desconhecido'}`;
      }
    } catch (error) {
      toast(`Erro: ${error.message}`);
    }
  }

  function vincularControles() {
    $('bloco1Refresh').onclick = () => carregarBloco1();
    $('btnBloco1SalvarConfig').onclick = () => salvarBloco1();
    $('btnBloco1LimparDisco').onclick = () => executarBloco1('limpar_disco', { executar: true });
    $('btnBloco1Deduplicar').onclick = () => executarBloco1('limpar_duplicados', { pasta: '~/Downloads', executar: false });
    $('btnBloco1BackupAgora').onclick = () => executarBloco1('backup_incremental', {});

    $('bloco2Refresh').onclick = () => carregarBloco2();
    $('btnBloco2SalvarConfig').onclick = () => salvarBloco2();
    $('btnBloco2PurgarRam').onclick = () => executarBloco2('limpar_ram', { agressivo: false });
    $('btnBloco2MatarTravados').onclick = () => executarBloco2('matar_travados', { matar: true });
    $('btnBloco2SuspenderAbas').onclick = () => executarBloco2('suspender_abas', { limite_mb: 500 });
    $('btnBloco2AuditarStartup').onclick = () => executarBloco2('guardiao_startup', { acao: 'auditar' });
  }

  return { carregarBloco1, salvarBloco1, executarBloco1, carregarBloco2, salvarBloco2, executarBloco2, vincularControles };
}
