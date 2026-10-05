import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopAPI } from './types';

const api: DesktopAPI = {
  copyText: text => ipcRenderer.invoke('activity:copy', text),
  activity: (projectId, request) => ipcRenderer.invoke('projects:activity', { ...request, projectId }),
  projects: () => ipcRenderer.invoke('projects:list'),
  addProject: () => ipcRenderer.invoke('projects:add'),
  selectProject: id => ipcRenderer.invoke('projects:select', id),
  removeProject: id => ipcRenderer.invoke('projects:remove', id),
  graph: id => ipcRenderer.invoke('projects:graph', id),
};
contextBridge.exposeInMainWorld('graphtraj', api);
