import type { Call } from './usage';
import type { Activity, ActivityRequest } from './activity';
export type Delivery = {
  event_id: string; event: string; ticket_id: string; candidate: string | null;
  dev_commit: string | null; reason: string | null;
  accepted_definition: string | null; evidence_refs: string[];
};
export type Ticket = {
  ticket_id: string;
  ticket_name: string;
  title: string;
  schema_version?: number;
  parent_id?: string | null;
  disposition?: string;
  parent_known?: boolean;
  progress?: { total: number; completed: number };
  status: string;
  active: boolean;
  ready: boolean;
  dependencies: string[];
  replaced_by: string[];
  delivery?: Delivery[];
};
export type Graph = { tickets: Ticket[]; schema_version?: number };
export type Project = { id: string; root: string; unavailable?: string };
export type Preferences = { projects: Project[]; selected: string | null; importedLegacy?: string[] };
export type Observation = { projectId: string; graph: Graph; updatedAt: string };
export type RoleFields = Partial<Record<'runtime' | 'model' | 'base_url' | 'api_key_env' |
  'reasoning_effort' | 'instructions' | 'system_prompt' | 'developer_prompt' | 'connection' | 'approval_connection' | 'approval_model' | 'approval_base_url' | 'approval_api_key_env', string | null>>;
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
  capabilities: { reasoning_efforts?: Record<string, string[]>; model_discovery: Record<string, string>; custom_api: Record<string, string[]> };
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
  projects: (refreshAvailability?: boolean) => Promise<Preferences>;
  addProject: () => Promise<Preferences>;
  relocateProject: (id: string) => Promise<Preferences>;
  selectProject: (id: string) => Promise<Preferences>;
  removeProject: (id: string) => Promise<Preferences>;
  graph: (id: string) => Promise<Observation>;
  settings: (id: string) => Promise<Settings>;
  saveSettings: (id: string, draft: SettingsDraft) => Promise<Settings>;
};
