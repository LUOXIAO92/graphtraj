import type { Call } from './usage';
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
export type Project = { id: string; root: string; unavailable?: string };
export type Preferences = { projects: Project[]; selected: string | null; importedLegacy?: string[] };
export type Observation = { projectId: string; graph: Graph; updatedAt: string };
export type RoleFields = Partial<Record<'runtime' | 'model' | 'base_url' | 'api_key_env' |
  'reasoning_effort' | 'instructions' | 'system_prompt' | 'developer_prompt' | 'connection' | 'approval_model' | 'approval_base_url' | 'approval_api_key_env', string | null>>;
export type RoleTree = { [reference: string]: RoleTree };
export type Settings = {
  revision: string; roles: Record<string, RoleFields>; edges: [string, string][]; role_tree: RoleTree; effect: string; applied?: boolean;
};
export type SettingsDraft = {
  role_tree?: RoleTree; remove_presets?: string[];
  revision: string; edits: Record<string, RoleFields>; renames: Record<string, string>;
  add_edges: { parent: string; child: string }[]; remove_edges: { parent: string; child: string }[];
};
export type CatalogModel = { id: string; alias?: string; source: 'manual' | 'native'; supported_efforts?: string[] };
export type CatalogProvider = { base_url?: string; api_key_env?: string; api?: string; models: Record<string, CatalogModel> };
export type CatalogRuntime = { runtime: 'codex' | 'pi' | 'dsh'; home?: string; providers: Record<string, CatalogProvider> };
export type Catalog = { version: 1; runtimes: Record<string, CatalogRuntime> };
export type ConnectionsRequest = { action: 'read' | 'discover' | 'preview' | 'save'; runtime?: string; catalog?: Catalog; expected_revision?: string };
export type Connections = { revision: string; catalog: Catalog; applied?: boolean; account_access: string;
  capabilities: { model_discovery: Record<string, string>; custom_api: Record<string, string[]> };
  discovery?: { runtime_entry: string; status: string; message?: string; account_access: string;
    provider_status?: Record<string, string>; models: (CatalogModel & { provider: string; supported_efforts?: string[] | null })[] };
};
export type UsageObservation = {
  projectId: string; calls: Call[]; notices: string[]; pending: boolean; updatedAt: string;
};
export type DesktopAPI = {
  connections: (id: string | null, request: ConnectionsRequest) => Promise<Connections>;
  usage: (id: string) => Promise<UsageObservation>;
  copyText: (text: string) => Promise<void>;
  activity: (projectId: string, request: ActivityRequest) => Promise<Activity>;
  projects: () => Promise<Preferences>;
  addProject: () => Promise<Preferences>;
  relocateProject: (id: string) => Promise<Preferences>;
  selectProject: (id: string) => Promise<Preferences>;
  removeProject: (id: string) => Promise<Preferences>;
  graph: (id: string) => Promise<Observation>;
  settings: (id: string) => Promise<Settings>;
  saveSettings: (id: string, draft: SettingsDraft) => Promise<Settings>;
};
