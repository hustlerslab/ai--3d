/**
 * P2-VIEWER-002: the viewer loads Draco-compressed models with a decoder the
 * app serves itself, and that decoder really decodes what the backend writes.
 *
 * The fixture `draco-piece.glb` is a genuine web copy from the backend
 * (web_variant.build through the pinned gltf-transform), and it is decoded here
 * with the very file the browser is served from public/draco/.
 */
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import piece from "./__fixtures__/draco-piece.json";
import { DRACO_DECODER_PATH } from "./components/scene-meshes";

const root = process.cwd();
const served = join(root, "public", DRACO_DECODER_PATH);
const shipped = join(root, "node_modules", "three", "examples", "jsm", "libs", "draco", "gltf");

function parseGlb(bytes: Buffer) {
  const jsonLength = bytes.readUInt32LE(12);
  const json = JSON.parse(bytes.subarray(20, 20 + jsonLength).toString("utf8"));
  const binStart = 20 + jsonLength + 8;
  return { json, bin: bytes.subarray(binStart, binStart + bytes.readUInt32LE(20 + jsonLength)) };
}

describe("the Draco decoder is the app's own", () => {
  it("is served from the app, never a CDN", () => {
    expect(DRACO_DECODER_PATH).toBe("/draco/");
    expect(DRACO_DECODER_PATH).not.toMatch(/^https?:|gstatic/);
  });

  it("is three.js's own decoder, byte for byte, so it matches the loader that calls it", () => {
    const files = readdirSync(shipped).filter((f) => f.startsWith("draco_"));
    expect(files.sort()).toEqual(["draco_decoder.js", "draco_decoder.wasm", "draco_wasm_wrapper.js"]);
    for (const f of files) {
      expect(readFileSync(join(served, f)).equals(readFileSync(join(shipped, f))), f).toBe(true);
    }
  });

  it("is the path the model loader is given", () => {
    const src = readFileSync(join(root, "src/features/walkthrough3d/components/scene-meshes.tsx"), "utf8");
    const calls = src.match(/useGLTF\([^)]*\)/g) ?? [];
    expect(calls.length).toBeGreaterThan(0);
    for (const call of calls) expect(call).toMatch(/useGLTF\(url, DRACO_DECODER_PATH,/);
  });
});

describe("the served decoder decodes the backend's compressed model", () => {
  it("gets back every triangle and the true size", async () => {
    const { json, bin } = parseGlb(readFileSync(join(root, "src/features/walkthrough3d/__fixtures__/draco-piece.glb")));
    expect(json.extensionsRequired).toContain("KHR_draco_mesh_compression");
    const prim = json.meshes[0].primitives[0];
    const ext = prim.extensions.KHR_draco_mesh_compression;
    const view = json.bufferViews[ext.bufferView];
    const data = new Int8Array(bin.subarray(view.byteOffset ?? 0, (view.byteOffset ?? 0) + view.byteLength));

    const load = createRequire(import.meta.url);
    const DracoDecoderModule = load(join(served, "draco_decoder.js"));
    const draco = await DracoDecoderModule();
    const decoder = new draco.Decoder();
    const mesh = new draco.Mesh();
    const status = decoder.DecodeArrayToMesh(data, data.byteLength, mesh);
    expect(status.ok(), status.error_msg()).toBe(true);

    // Only the zero-area pole triangles may go; every visible one is kept.
    expect(mesh.num_faces()).toBeGreaterThanOrEqual(piece.triangles - piece.degenerate_at_poles);
    expect(mesh.num_faces()).toBeLessThanOrEqual(piece.triangles);

    const attr = decoder.GetAttributeByUniqueId(mesh, ext.attributes.POSITION);
    const values = new draco.DracoFloat32Array();
    decoder.GetAttributeFloatForAllPoints(mesh, attr, values);
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < mesh.num_points(); i++) {
      for (let k = 0; k < 3; k++) {
        const v = values.GetValue(i * 3 + k);
        min[k] = Math.min(min[k], v);
        max[k] = Math.max(max[k], v);
      }
    }
    // 14-bit position quantization: within one grid step of the source.
    for (let k = 0; k < 3; k++) {
      const step = (piece.max[k] - piece.min[k]) / (2 ** 14 - 1);
      expect(Math.abs(min[k] - piece.min[k])).toBeLessThanOrEqual(step + 1e-6);
      expect(Math.abs(max[k] - piece.max[k])).toBeLessThanOrEqual(step + 1e-6);
    }
    draco.destroy(values);
    draco.destroy(mesh);
    draco.destroy(decoder);
  });
});
