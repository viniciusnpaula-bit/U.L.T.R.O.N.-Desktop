const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('ultron', Object.freeze({
  getHudSnapshot: () => ipcRenderer.invoke('hud:snapshot'),
  onHudSnapshot: callback => {
    const listener = (_event, snapshot) => callback(snapshot);
    ipcRenderer.on('hud:snapshot', listener);
    return () => ipcRenderer.removeListener('hud:snapshot', listener);
  },
  returnToMain: () => ipcRenderer.invoke('hud:return'),
  setIslandExpanded: expanded => ipcRenderer.invoke('hud:expand', expanded === true),
  moveOrb: (dx, dy, commit) => ipcRenderer.invoke('hud:move', { dx, dy, commit: commit === true }),
  runHudAction: actionId => ipcRenderer.invoke('hud:action', actionId),
  sendHudCommand: text => ipcRenderer.invoke('hud:command', text),
  quitApp: () => ipcRenderer.invoke('hud:quit'),
  version: '3.0.0',
}));
