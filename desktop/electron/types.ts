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
export type RoleFields = Partial<Record<'runtime' | 'model' | 'base_url' | 'api_key_env' |
  'reasoning_effort' | 'instructions' | 'system_prompt' | 'developer_prompt', string | null>>;
export type Settings = {
  revision: string; roles: Record<string, RoleFields>; edges: [string, string][]; effect: string; applied?: boolean;
};
export type SettingsDraft = {
  revision: string; edits: Record<string, RoleFields>; renames: Record<string, string>;
  add_edges: { parent: string; child: string }[]; remove_edges: { parent: string; child: string }[];
};
export type DesktopAPI = {
  copyText: (text: string) => Promise<void>;
  activity: (projectId: string, request: ActivityRequest) => Promise<Activity>;
  projects: () => Promise<Preferences>;
  addProject: () => Promise<Preferences>;
  selectProject: (id: string) => Promise<Preferences>;
  removeProject: (id: string) => Promise<Preferences>;
  graph: (id: string) => Promise<Observation>;
  settings: (id: string) => Promise<Settings>;
  saveSettings: (id: string, draft: SettingsDraft) => Promise<Settings>;
};
