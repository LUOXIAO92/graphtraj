import type { Activity, ActivityRequest } from './activity';
export type Ticket = {
  ticket_id: string;
  ticket_name: string;
  title: string;
  status: string;
  active: boolean;
  ready: boolean;
  dependencies: string[];
  replaced_by: string[];
};
export type Graph = { tickets: Ticket[] };
export type Project = { id: string; root: string };
export type Preferences = { projects: Project[]; selected: string | null };
export type Observation = { projectId: string; graph: Graph; updatedAt: string };
export type DesktopAPI = {
  copyText: (text: string) => Promise<void>;
  activity: (projectId: string, request: ActivityRequest) => Promise<Activity>;
  projects: () => Promise<Preferences>;
  addProject: () => Promise<Preferences>;
  selectProject: (id: string) => Promise<Preferences>;
  removeProject: (id: string) => Promise<Preferences>;
  graph: (id: string) => Promise<Observation>;
};
