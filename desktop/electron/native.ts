import path from 'node:path';

/** Use the installed Windows bundle's Python; keep external CLI discovery in development. */
export function nativeCommand(executable?: string): { executable: string; args: string[] } {
  if (executable) return { executable, args: [] };
  const runtime = process as NodeJS.Process & { resourcesPath?: string; defaultApp?: boolean };
  const resources = runtime.resourcesPath;
  if (process.platform === 'win32' && resources && !runtime.defaultApp) {
    const python = path.join(resources, 'python', 'python.exe');
    return {
      executable: python,
      args: ['-I', '-X', 'utf8', '-c', 'from graphtraj.interfaces.local_tool import main; main()'],
    };
  }
  return { executable: process.env.GRAPHTRAJ_TOOL || 'graphtraj-tool', args: [] };
}
