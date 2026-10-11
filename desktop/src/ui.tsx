import { useEffect, useRef, type ReactNode } from 'react';
import { Button, TextField, Input, Label, Description } from '@heroui/react';

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    graph: <><rect x="3" y="3" width="6" height="6" rx="1.4"/><rect x="15" y="15" width="6" height="6" rx="1.4"/><rect x="15" y="3" width="6" height="6" rx="1.4"/><path d="M9 6h6M6 9v9h9"/></>,
    usage: <><path d="M4 19V5M4 19h16M8 15v-4m5 4V6m5 9V9"/></>,
    settings: <><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    down: <path d="m7 10 5 5 5-5"/>,
    right: <path d="m9 6 6 6-6 6"/>,
    left: <path d="m15 6-6 6 6 6"/>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    layers: <><path d="m12 3 10 5-10 5L2 8l10-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/></>,
    eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
    terminal: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3m6 0h4"/></>,
    copy: <><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></>,
    expand: <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>,
    fit: <><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><rect x="8" y="8" width="8" height="8" rx="1"/></>,
    book: <><path d="M12 5v16M3 3c4-1 7 0 9 2 2-2 5-3 9-2v15c-4-1-7 0-9 3-2-3-5-4-9-3Z"/></>,
    folder: <path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10H3Z"/>,
    branch: <><circle cx="6" cy="5" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="19" r="2"/><path d="M6 7v10m0-5c10 0 12-1 12-4"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/></>,
    bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7l1-7Z"/>,
    pause: <><path d="M8 5v14M16 5v14"/></>,
    play: <path d="m7 4 13 8-13 8Z"/>,
    shield: <><path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/></>,
    link: <><path d="m10 13 4-4M8 15l-2 2a3 3 0 0 1-4-4l5-5a3 3 0 0 1 4 0m2 1 2-2a3 3 0 0 1 4 4l-5 5a3 3 0 0 1-4 0"/></>,
    sidebar: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M5.5 8h1M5.5 11h1"/></>,
    trash: <><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 14 6M18 18A8 8 0 0 1 4 12"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.graph}</svg>;
}

const statusClass = (status: string) => status.toLowerCase().replaceAll(' ', '-');
export function Status({ value }: { value: string }) { return <span className={`status status-${statusClass(value)}`}><span className="status-dot"/>{value}</span>; }
export function Avatar({ name, small = false }: { name: string; small?: boolean }) { return <span className={`avatar avatar-${name.toLowerCase().split(' ')[0]} ${small ? 'small' : ''}`}>{name.slice(0, 1)}</span>; }
export function Logo() { return <span className="logo-mark"><svg width="25" height="25" viewBox="0 0 28 28" fill="none" aria-hidden="true"><path d="M7 6v14h14M7 7h13v13" stroke="currentColor" strokeWidth="1.7"/><circle cx="7" cy="6" r="3" fill="currentColor"/><circle cx="7" cy="21" r="3" fill="currentColor"/><circle cx="21" cy="21" r="3" fill="currentColor"/><circle cx="21" cy="7" r="3" fill="currentColor"/></svg></span>; }

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="dialog" onCancel={onClose} aria-labelledby="dialog-title"><div className="dialog-heading"><h2 id="dialog-title">{title}</h2><Button isIconOnly variant="ghost" aria-label="Close dialog" onPress={onClose}><Icon name="close"/></Button></div><div className="dialog-body">{children}</div></dialog>;
}

export function Field({ label, value, onChange, hint, invalid, error }: { label: string; value: string; onChange: (value: string) => void; hint?: string; invalid?: boolean; error?: string }) {
  return <TextField className="settings-field" value={value} onChange={onChange} isInvalid={invalid || !!error}><Label>{label}</Label><Input variant="secondary" spellCheck={false}/>{hint && <Description>{hint}</Description>}{(invalid || error) && <span className="field-error" role="alert">{error || (label === 'Base URL' ? 'Use an http:// or https:// URL.' : 'Use an environment variable name, such as OPENAI_API_KEY.')}</span>}</TextField>;
}
