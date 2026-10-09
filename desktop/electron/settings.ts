import { nativeCommand } from './native.ts';
import { spawn, type ChildProcess } from 'node:child_process';
import { createInterface } from 'node:readline';
import type { RoleFields, Settings, SettingsDraft } from './types';

export type SettingsReview = {
  project: string; effect: string;
  edits: SettingsDraft['edits']; before: SettingsDraft['edits']; renames: Record<string, string>;
  add_edges: { parent: string; child: string }[]; remove_edges: { parent: string; child: string }[];
};

/** Format only the native operation's safe edited fields for human approval. */
export function reviewText(review: SettingsReview): string {
  const lines = [review.project, '', review.effect, ''];
  for (const [role, fields] of Object.entries(review.edits)) {
    for (const [field, value] of Object.entries(fields)) {
      lines.push(`${role} · ${field}\n  ${review.before[role]?.[field as keyof RoleFields] ?? '(not set)'} → ${value ?? '(clear)'}`);
    }
  }
  for (const [before, after] of Object.entries(review.renames)) lines.push(`Role name: ${before} → ${after}`);
  for (const edge of review.add_edges) lines.push(`Allow dispatch: ${edge.parent} → ${edge.child}`);
  for (const edge of review.remove_edges) lines.push(`Remove dispatch: ${edge.parent} → ${edge.child}`);
  return lines.join('\n');
}

/** Own the restricted native settings pipe and main-process review callback. */
export class SettingsClient {
  private children = new Set<ChildProcess>();
  constructor(private review: (proposal: SettingsReview) => Promise<boolean>,
    private executable?: string) {}

  request(root: string, draft?: SettingsDraft): Promise<Settings> {
    return new Promise((resolve, reject) => {
      const command = nativeCommand(this.executable);
      const child = spawn(command.executable, [...command.args, '--desktop-settings'], {
        cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      });
      this.children.add(child);
      let finished = false;
      let reviewing = false;
      const fail = (error: unknown) => { if (!finished) { finished = true; reject(error); } child.kill(); };
      child.on('error', () => fail(new Error('Native settings unavailable. Check the matching GraphTraj installation.')));
      child.stdin.on('error', () => fail(new Error('Native settings connection closed. Reload to check the saved state.')));
      // Native diagnostics are not copied into renderer logs or error strings.
      child.stderr.resume();
      const lines = createInterface({ input: child.stdout });
      lines.on('line', line => {
        void (async () => {
          const reply = JSON.parse(line);
          if (reply.review) {
            if (!draft || reviewing) throw new Error('Unexpected native review request.');
            reviewing = true;
            const accepted = await this.review(reply.review);
            child.stdin.end(JSON.stringify({ decision: accepted ? 'accept' : 'decline' }) + '\n');
          } else if (reply.failed) {
            fail(new Error(reply.error || 'Settings were not saved.'));
          } else if (reply.result && !finished) {
            finished = true;
            resolve(reply.result);
            child.stdin.end();
          } else throw new Error('Native settings returned an invalid response.');
        })().catch(fail);
      });
      child.on('close', () => {
        this.children.delete(child);
        lines.close();
        if (!finished) fail(new Error('Native settings connection ended. Reload to check the saved state.'));
      });
      child.stdin.write(JSON.stringify(draft ? { action: 'save', ...draft } : { action: 'read' }) + '\n');
    });
  }

  close(): void {
    for (const child of this.children) child.kill();
    this.children.clear();
  }
}
