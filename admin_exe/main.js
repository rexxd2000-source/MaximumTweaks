const { app, BrowserWindow, Menu, shell } = require('electron');

const APP_URL = process.env.MAX_MANAGER_URL || process.env.SIGIL_URL || 'https://maximumtweaks.onrender.com/?admin=discord';
const ALLOW = ['maximumtweaks.onrender.com', 'discord.com'];

function inAllowlist(url) {
  try {
    const host = new URL(url).hostname;
    return ALLOW.some((origin) => host.endsWith(origin) || host === origin);
  } catch (_) {
    return false;
  }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1080,
    minHeight: 680,
    backgroundColor: '#061a1d',
    title: 'Max Manager - License admin',
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      partition: 'persist:maximumtweaks',
    },
  });

  Menu.setApplicationMenu(null);
  win.setMenuBarVisibility(false);
  win.loadURL(APP_URL);

  win.webContents.on('will-navigate', (event, url) => {
    if (!inAllowlist(url)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (inAllowlist(url)) return { action: 'allow' };
    shell.openExternal(url);
    return { action: 'deny' };
  });

  win.once('ready-to-show', () => win.show());
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
