import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopAPI } from './types';

const api: DesktopAPI = {
  projects: () => ipcRenderer.invoke('projects:list'),
  addProject: () => ipcRenderer.invoke('projects:add'),
  selectProject: id => ipcRenderer.invoke('projects:select', id),
  removeProject: id => ipcRenderer.invoke('projects:remove', id),
  graph: id => ipcRenderer.invoke('projects:graph', id),
  settings: id => ipcRenderer.invoke('settings:read', id),
  saveSettings: (id, draft) => ipcRenderer.invoke('settings:save', id, draft),
};
contextBridge.exposeInMainWorld('graphtraj', api);
