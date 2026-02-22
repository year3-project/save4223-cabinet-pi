const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Receive state updates from main process
  onStateUpdate: (callback) => {
    ipcRenderer.on('state-update', (_, data) => callback(data));
  },
  
  // Receive WebSocket connection status
  onWsStatus: (callback) => {
    ipcRenderer.on('ws-status', (_, data) => callback(data));
  },
  
  // Request current state from backend
  requestState: () => {
    ipcRenderer.send('request-state');
  },
  
  // Remove all listeners (cleanup)
  removeAllListeners: () => {
    ipcRenderer.removeAllListeners('state-update');
    ipcRenderer.removeAllListeners('ws-status');
  }
});
