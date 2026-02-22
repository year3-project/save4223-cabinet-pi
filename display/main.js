const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const WebSocket = require('ws');

// Keep a global reference of the window object
let mainWindow;
let wsClient = null;
let reconnectInterval = null;

const WS_URL = 'ws://localhost:8765';
const RECONNECT_DELAY = 3000;

function createWindow() {
  // Create the browser window
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    fullscreen: !process.argv.includes('--dev'),
    kiosk: !process.argv.includes('--dev'),
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  // Load the index.html
  mainWindow.loadFile('index.html');

  // Open DevTools in dev mode
  if (process.argv.includes('--dev')) {
    mainWindow.webContents.openDevTools();
  }

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function connectWebSocket() {
  console.log(`[Display] Connecting to ${WS_URL}...`);
  
  wsClient = new WebSocket(WS_URL);
  
  wsClient.on('open', () => {
    console.log('[Display] WebSocket connected');
    if (mainWindow) {
      mainWindow.webContents.send('ws-status', { connected: true });
    }
    
    // Clear reconnection interval if exists
    if (reconnectInterval) {
      clearInterval(reconnectInterval);
      reconnectInterval = null;
    }
  });
  
  wsClient.on('message', (data) => {
    try {
      const message = JSON.parse(data);
      console.log('[Display] Received:', message.type);
      
      if (mainWindow) {
        mainWindow.webContents.send('state-update', message);
      }
    } catch (err) {
      console.error('[Display] Failed to parse message:', err);
    }
  });
  
  wsClient.on('close', () => {
    console.log('[Display] WebSocket disconnected');
    if (mainWindow) {
      mainWindow.webContents.send('ws-status', { connected: false });
    }
    
    // Schedule reconnection
    if (!reconnectInterval) {
      reconnectInterval = setInterval(connectWebSocket, RECONNECT_DELAY);
    }
  });
  
  wsClient.on('error', (err) => {
    console.error('[Display] WebSocket error:', err.message);
  });
}

// IPC handlers
ipcMain.on('request-state', () => {
  // Request current state from Python backend
  if (wsClient && wsClient.readyState === WebSocket.OPEN) {
    wsClient.send(JSON.stringify({ type: 'GET_STATE' }));
  }
});

// App event handlers
app.whenReady().then(() => {
  createWindow();
  connectWebSocket();
  
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (wsClient) {
    wsClient.close();
  }
  if (reconnectInterval) {
    clearInterval(reconnectInterval);
  }
  
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Handle keyboard shortcuts for kiosk mode exit
app.on('browser-window-created', (_, window) => {
  window.webContents.on('before-input-event', (event, input) => {
    // Exit kiosk with Ctrl+Shift+Q
    if (input.control && input.shift && input.key.toLowerCase() === 'q') {
      app.quit();
    }
  });
});
