import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopAPI } from './types';

const api: DesktopAPI = {
  usage: id => ipcRenderer.invoke('projects:usage', id),
  copyText: text => ipcRenderer.invoke('activity:copy', text),
  activity: (projectId, request) => ipcRenderer.invoke('projects:activity', { ...request, projectId }),
  projects: refresh => ipcRenderer.invoke('projects:list', refresh),
  addProject: () => ipcRenderer.invoke('projects:add'),
  relocateProject: id => ipcRenderer.invoke('projects:relocate', id),
  selectProject: id => ipcRenderer.invoke('projects:select', id),
  removeProject: id => ipcRenderer.invoke('projects:remove', id),
  graph: id => ipcRenderer.invoke('projects:graph', id),
  connections: (id, request) => ipcRenderer.invoke('connections:request', id, request),
  settings: id => ipcRenderer.invoke('settings:read', id),
  saveSettings: (id, draft) => ipcRenderer.invoke('settings:save', id, draft),
  saveArchive: (id, choices) => ipcRenderer.invoke('settings:archive', id, choices),
  members: (projectId, summaryTaskId) => ipcRenderer.invoke('projects:members', { projectId, ...(summaryTaskId ? { summary_task_id: summaryTaskId } : {}) }),
};
contextBridge.exposeInMainWorld('graphtraj', api);
