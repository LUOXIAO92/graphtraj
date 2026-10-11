import { useMemo, useState } from 'react';
import { ReactFlow, Background, Controls, Handle, Position, type NodeProps, type Node, type Edge, Panel } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { RoleFields, RoleTree } from '../electron/types';
import { connectTeamNode, ownRole, roleName, treeEdges } from './settings-draft';

type AgentNode = Node<{ name: string; model: string; effort: string; external: boolean }, 'agent'>;

/** Keep the established D agent card, with native connection handles. */
function AgentCard({ data, selected }: NodeProps<AgentNode>) {
  return <div className={`d-org-node ${selected ? 'selected' : ''}`}>
    <Handle type="target" position={Position.Top} aria-label="Parent connection" />
    <span className="d-org-role">{data.external ? 'Cross-team parent · preserved' : 'Agent'}</span>
    <strong>{data.name}</strong><small>{data.model}</small>
    <span className="d-org-child-count">{data.effort} effort</span>
    <Handle type="source" position={Position.Bottom} aria-label="Connect a child" />
  </div>;
}
const nodeTypes = { agent: AgentCard };

/** Edit exact native occurrences; cross-team relationships are listed separately. */
export function TeamGraph({ tree, references, roles, renames, selected, busy, onSelect, onChange, onError, modelLabel }: {
  tree: RoleTree; references: string[]; roles: Record<string, RoleFields>; renames: Record<string, string>;
  selected: string; busy: boolean; onSelect: (ref: string) => void; onChange: (tree: RoleTree) => void;
  onError: (error: string) => void; modelLabel: (ref: string) => string;
}) {
  const [connection, setConnection] = useState<string | null>(null);
  const { nodes, edges } = useMemo(() => {
    const members = new Set(references);
    const nodes: AgentNode[] = [], edges: Edge[] = [];
    const present = new Set<string>();
    let column = 0;
    function visit(branch: RoleTree, path: string[], depth: number): void {
      for (const [ref, children] of Object.entries(branch)) {
        const next = [...path, ref], id = JSON.stringify(next);
        const internal = members.has(ref), parentInternal = members.has(path.at(-1) ?? '');
        const level = internal && parentInternal ? depth : 0;
        if (internal) {
          present.add(ref);
          nodes.push({ id, type: 'agent', ariaLabel: `Configure agent ${roleName(renames, ref)}`, position: { x: column * 230, y: level * 190 }, selected: ref === selected,
            data: { name: roleName(renames, ref).split('.').at(-1)!, model: modelLabel(ref),
              effort: ownRole(roles, ref)?.reasoning_effort || 'Default', external: !!path.length && !parentInternal } });
          if (parentInternal) edges.push({ id, source: JSON.stringify(path), target: id, type: 'smoothstep', reconnectable: 'source' });
        }
        visit(children, next, level + 1);
        if (internal && !Object.keys(children).some(child => members.has(child))) column++;
      }
    }
    visit(tree, [], 0);
    for (const ref of references) if (!present.has(ref)) {
      nodes.push({ id: JSON.stringify([ref]), type: 'agent', ariaLabel: `Configure agent ${roleName(renames, ref)}`, position: { x: column++ * 230, y: 0 }, selected: ref === selected,
        data: { name: roleName(renames, ref).split('.').at(-1)!, model: modelLabel(ref), effort: ownRole(roles, ref)?.reasoning_effort || 'Default', external: false } });
    }
    return { nodes, edges };
  }, [tree, references.join('\0'), roles, renames, selected, modelLabel]);
  const cross = treeEdges(tree).filter(([a,b]) => references.includes(a) !== references.includes(b));
  function connect(source: string | null, target: string | null): void {
    if (!source || !target || busy) return;
    try { onChange(connectTeamNode(tree, JSON.parse(target), JSON.parse(source))); }
    catch (error) { onError(String(error)); }
  }
  return <>
    <div className="d-team-flow" role="region" aria-label="Team organization tree">
      <ReactFlow key={nodes.map(node => node.id).join('|')} nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false}
        panActivationKeyCode={null} selectionKeyCode={null} multiSelectionKeyCode={null} zoomActivationKeyCode={null}
        nodesConnectable={!busy} edgesReconnectable={!busy} deleteKeyCode={null}
        onNodeClick={(_, node) => { setConnection(null); onSelect(JSON.parse(node.id).at(-1)); }}
        onEdgeClick={(_, edge) => setConnection(edge.target)}
        onConnect={({ source, target }) => connect(source, target)}
        onReconnect={(_, { source, target }) => connect(source, target)}
        fitView fitViewOptions={{ padding: .22, maxZoom: 1 }} minZoom={.3} maxZoom={1.5}>
        <Background gap={20}/><Controls showInteractive={false}/>
        {connection && edges.some(edge => edge.target === connection) && <Panel position="top-right"><button className="d-disconnect" disabled={busy} onClick={() => {
          try { onChange(connectTeamNode(tree, JSON.parse(connection), null)); setConnection(null); }
          catch (error) { onError(String(error)); }
        }}>Disconnect parent · make root</button></Panel>}
      </ReactFlow>
    </div>
    {cross.length > 0 && <details className="d-cross-team"><summary>Historical cross-team relationships ({cross.length})</summary>
      <p>Preserved when editing this team. These connections cannot be reassigned here.</p>
      <ul>{cross.map(([a,b], i) => <li key={i}>{roleName(renames,a)} → {roleName(renames,b)}</li>)}</ul>
    </details>}
  </>;
}
