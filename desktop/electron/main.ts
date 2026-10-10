import { app, BrowserWindow, clipboard, dialog, ipcMain, session } from 'electron';
import path from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';
import { GraphReader, Projects } from './projects';
import { SettingsClient, reviewText } from './settings';
import type { SettingsDraft } from './types';

app.setName('GraphTraj');
// The standard Chromium switch also isolates Electron preferences for desktop checks.
const userData = app.commandLine.getSwitchValue('user-data-dir');
if (userData) app.setPath('userData', path.resolve(userData));
const page = path.join(__dirname, '../dist/index.html');
let window: BrowserWindow | null = null;
let reader: GraphReader;
let projects: Projects;
let settings: SettingsClient;
let writes: Promise<unknown> = Promise.resolve();

/** Create a sandboxed observer window without a local web server. */
function createWindow(): void {
  window = new BrowserWindow({
    width: 1440, height: 900, minWidth: 960, minHeight: 600,
    title: 'GraphTraj',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      webviewTag: false,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.on('closed', () => { window = null; });
  void window.loadFile(page);
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { window?.show(); window?.focus(); });
  void app.whenReady().then(async () => {
    reader = new GraphReader();
    projects = new Projects(path.join(homedir(), '.graphtraj', 'projects.json'), reader,
      path.join(app.getPath('userData'), 'projects.json'));
    await projects.load();
    if (app.commandLine.hasSwitch('project')) await projects.add(app.commandLine.getSwitchValue('project'));
    settings = new SettingsClient(async proposal => {
      if (!window) return false;
      const answer = await dialog.showMessageBox(window, {
        type: 'question', title: 'Save project settings?', message: 'Approve these configuration changes?',
        detail: reviewText(proposal), buttons: ['Cancel', 'Save settings'],
        defaultId: 0, cancelId: 0, noLink: true,
      });
      return answer.response === 1;
    });
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);

    const handlers: Record<string, (id?: unknown, draft?: SettingsDraft) => unknown> = {
      'activity:copy': text => {
        if (typeof text !== 'string') throw new Error('Copy requires text.');
        clipboard.writeText(text);
      },
      'projects:list': () => projects.refreshAvailability(),
      'projects:relocate': async id => {
        const result = await dialog.showOpenDialog(window!, {
          title: 'Relocate GraphTraj project', properties: ['openDirectory'],
        });
        return result.canceled ? projects.list() : projects.relocate(id, result.filePaths[0]);
      },
      'projects:add': async () => {
        const result = await dialog.showOpenDialog(window!, {
          title: 'Add existing GraphTraj project', properties: ['openDirectory'],
        });
        return result.canceled ? projects.list() : projects.add(result.filePaths[0]);
      },
      'projects:select': id => projects.select(id),
      'projects:remove': id => projects.remove(id),
      'projects:graph': id => projects.graph(id),
      'projects:activity': value => projects.activity(value),
      'settings:read': async id => settings.request(await projects.settingsRoot(id)),
      'settings:save': async (id, draft) => {
        if (!draft || typeof draft !== 'object' || Object.keys(draft).some(key =>
          !['revision', 'edits', 'renames', 'add_edges', 'remove_edges'].includes(key))) {
          throw new Error('Invalid settings draft.');
        }
        return settings.request(await projects.settingsRoot(id), draft);
      },
    };
    for (const [channel, handler] of Object.entries(handlers)) {
      ipcMain.handle(channel, (event, id, draft) => {
        if (!window || event.sender !== window.webContents ||
            event.senderFrame !== window.webContents.mainFrame ||
            event.senderFrame.url !== pathToFileURL(page).href) {
          throw new Error('Desktop request from an untrusted frame.');
        }
        if (channel === 'activity:copy' || channel === 'projects:activity' || channel === 'projects:graph') return handler(id);
        // Serialize preference changes, including the native folder dialog.
        const next = writes.then(() => handler(id, draft));
        writes = next.catch(() => undefined);
        return next;
      });
    }
    createWindow();
  }).catch(error => {
    dialog.showErrorBox('GraphTraj could not open', String(error));
    app.quit();
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', () => { reader?.close(); projects?.close(); settings?.close(); });
}
