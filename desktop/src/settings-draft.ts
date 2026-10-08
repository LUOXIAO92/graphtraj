import type { RoleFields, SettingsDraft } from '../electron/types';

export const fieldLabels: Record<keyof RoleFields, string> = {
  runtime: 'Runtime', model: 'Model', base_url: 'Base URL', api_key_env: 'Credential environment variable (api_key_env)',
  reasoning_effort: 'Reasoning effort', instructions: 'Instruction file reference',
  system_prompt: 'System prompt', developer_prompt: 'Developer prompt',
};

/** Read only a declared role key, including names shared with Object.prototype. */
export function ownRole<T>(roles: Record<string, T> | undefined, reference: string): T | undefined {
  return roles && Object.hasOwn(roles, reference) ? roles[reference] : undefined;
}

/** Use an explicitly staged name in role controls and dispatch labels. */
export function roleName(renames: Record<string, string>, reference: string): string {
  return ownRole(renames, reference) ?? reference;
}

/** Build the renderer's serializable role edits and readable before/after rows. */
export function roleChanges(roles: Record<string, RoleFields>, saved?: Record<string, RoleFields>) {
  const edits: SettingsDraft['edits'] = Object.create(null);
  const changes: { label: string; before: string; after: string }[] = [];
  for (const [role, fields] of Object.entries(roles)) {
    for (const field of Object.keys(fieldLabels) as (keyof RoleFields)[]) {
      const before = ownRole(saved, role)?.[field] ?? null;
      const after = fields[field] || null;
      if (before !== after) {
        (edits[role] ??= {})[field] = after;
        changes.push({ label: `${role} · ${fieldLabels[field]}`, before: before ?? '(not set)', after: after ?? '(clear)' });
      }
    }
  }
  return { edits, changes };
}
