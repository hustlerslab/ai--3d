/**
 * P2-VIEWER-001: "loads on a mid-range laptop or degrades with a clear
 * message". The 3D view needs WebGL; without it three.js throws and the
 * person sees a blank box. This asks first, so the page can say why instead.
 */

export const NO_WEBGL_MESSAGE =
  "This browser or graphics card can't show the 3D view. The 360° tour and the rendered pictures still work.";

export const CONTEXT_LOST_MESSAGE =
  "The 3D view stopped because the graphics card ran out of memory. Reload the page to try again.";

export function canRender3D(doc: Pick<Document, "createElement"> | undefined = globalThis.document): boolean {
  if (!doc) return true; // server render: decide in the browser
  try {
    const canvas = doc.createElement("canvas") as HTMLCanvasElement;
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}
