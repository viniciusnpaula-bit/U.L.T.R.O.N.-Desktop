const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('ultron', Object.freeze({
  health: () => ipcRenderer.invoke('api:health'),
  status: () => ipcRenderer.invoke('api:status'),
  events: () => ipcRenderer.invoke('api:events'),
  command: text => ipcRenderer.invoke('api:command', text),
  microphone: paused => ipcRenderer.invoke('api:microphone', paused),
  microphones: () => ipcRenderer.invoke('api:microphones'),
  conversation: () => ipcRenderer.invoke('api:conversation'),
  cofreStatus: () => ipcRenderer.invoke('cofre:status'),
  cofreGuardar: (nome, valor) => ipcRenderer.invoke('cofre:guardar', nome, valor),
  cofreRemover: nome => ipcRenderer.invoke('cofre:remover', nome),
  cofreTestar: nome => ipcRenderer.invoke('cofre:testar', nome),
  abrirLink: url => ipcRenderer.invoke('link:abrir', url),
  fatosListar: busca => ipcRenderer.invoke('mem:fatos', busca),
  fatoCorrigir: (id, texto) => ipcRenderer.invoke('mem:fato-corrigir', id, texto),
  fatoApagar: id => ipcRenderer.invoke('mem:fato-apagar', id),
  lembreteCancelar: (numero, trecho) => ipcRenderer.invoke('mem:lembrete-cancelar', numero, trecho),
  fluxosListar: () => ipcRenderer.invoke('fluxos:listar'),
  lembretesListar: () => ipcRenderer.invoke('mem:lembretes'),
  vozInfo: () => ipcRenderer.invoke('voz:info'),
  vozSalvar: valores => ipcRenderer.invoke('voz:salvar', valores),
  vozRestaurar: () => ipcRenderer.invoke('voz:restaurar'),
  vozTestar: texto => ipcRenderer.invoke('voz:testar', texto),
  microfoneTestar: () => ipcRenderer.invoke('voz:testar-microfone'),
  personalidadeInfo: () => ipcRenderer.invoke('voz:personalidade'),
  personalidadeSalvar: valores => ipcRenderer.invoke('voz:personalidade-salvar', valores),
  personalidadeRestaurar: () => ipcRenderer.invoke('voz:personalidade-restaurar'),
  personalidadePrevia: () => ipcRenderer.invoke('voz:personalidade-previa'),
  updateInfo: () => ipcRenderer.invoke('update:info'),
  updateCheck: () => ipcRenderer.invoke('update:check'),
  updateApply: restartAfter => ipcRenderer.invoke('update:apply', restartAfter === true),
  updateLaunch: () => ipcRenderer.invoke('update:launch'),
  updateRollback: () => ipcRenderer.invoke('update:rollback'),
  setZoom: enabled => ipcRenderer.invoke('view:zoom', enabled === true),
  selectMicrophone: deviceId => ipcRenderer.invoke('api:microphone-device', deviceId),
  confirmation: (requestId, approved, pin) => ipcRenderer.invoke('api:confirmation', requestId, approved, pin),
  emergencyStop: () => ipcRenderer.invoke('api:emergency-stop'),
  shutdown: () => ipcRenderer.invoke('api:shutdown'),
  toggleHud: () => ipcRenderer.invoke('hud:toggle'),
  publishHudSnapshot: snapshot => ipcRenderer.invoke('hud:publish', snapshot),
  onHudVisibility: callback => {
    const listener = (_event, visible) => callback(visible === true);
    ipcRenderer.on('hud:visibility', listener);
    return () => ipcRenderer.removeListener('hud:visibility', listener);
  },
  onHudAction: callback => {
    const listener = (_event, request) => callback(request);
    ipcRenderer.on('hud:run-action', listener);
    return () => ipcRenderer.removeListener('hud:run-action', listener);
  },
  hudActionResult: (requestId, accepted) => ipcRenderer.send('hud:action-result', requestId, accepted === true),
  version: '1.11.0',
}));
