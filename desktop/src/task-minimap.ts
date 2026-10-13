import { MiniMap, type Dom } from '@antv/x6';

/** Navigate the fitted miniature using its actual transform, not its paper ratio. */
export class TaskMiniMap extends MiniMap {
  protected scrollTo(event: Dom.MouseDownEvent): void {
    const pointer = this.normalizeEvent(event);
    // Client coordinates are stable across the SVG, graph and viewport targets.
    const point = this.targetGraph.clientToLocal(pointer.clientX, pointer.clientY);
    this.sourceGraph.centerPoint(point.x, point.y);
  }

  protected doAction(event: Dom.MouseMoveEvent): void {
    // MiniMap fits the content after computing its nominal paper-size ratio.
    // Drag deltas must use the same current scale as the visible miniature.
    this.ratio = this.targetGraph.transform.getScale().sx;
    super.doAction(event);
  }
}
