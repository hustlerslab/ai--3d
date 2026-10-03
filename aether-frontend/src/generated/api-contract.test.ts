/**
 * P1-FRONTEND-003: every API function the frontend exposes must send a method
 * + path the backend actually serves.
 *
 * The bug this exists for: `reviewElementImages` built
 * `{ method: "PATCH", ...json(body) }`, the helper's own `method: "POST"`
 * spread on top, and a person's Build/Skip choices were routed to the enqueue
 * endpoint. Both answered 200, and BOTH ROUTES EXIST - so "does the backend
 * serve this?" alone would not have caught it. Here every exported function
 * names the endpoint it is meant to call; fetch and XMLHttpRequest are
 * replaced by recorders; the recorded request must match that endpoint
 * exactly, and the endpoint must exist in API_ENDPOINTS - which is generated
 * from the backend's own OpenAPI document, not written by hand.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as auth from "../features/auth/api/auth-api";
import * as projects from "../features/studio/api/projects-api";
import * as tour from "../features/tour/api/tour-api";
import * as viewer from "../features/walkthrough3d/api/aether-api";
import { API_ENDPOINTS } from "./api-types";

type Sent = { method: string; path: string };
let sent: Sent[] = [];

function record(method: string | undefined, url: string) {
  const u = new URL(url, "http://localhost:8000");
  sent.push({ method: (method ?? "GET").toUpperCase(), path: u.pathname });
}

// A body every caller can read without throwing: enveloped reads, flat writes.
const OK_BODY = { success: true, data: {}, project: {}, job: {}, scene: {}, user: {} };

class RecordingXHR {
  status = 200;
  responseText = JSON.stringify(OK_BODY);
  upload = { onprogress: null as unknown };
  withCredentials = false;
  timeout = 0;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  private method = "GET";
  private url = "";
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  send() {
    record(this.method, this.url);
    this.onload?.();
  }
  setRequestHeader() {}
}

beforeEach(() => {
  sent = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    record(init?.method, url);
    return new Response(JSON.stringify(OK_BODY), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  vi.stubGlobal("XMLHttpRequest", RecordingXHR);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const ROUTES = API_ENDPOINTS.map((e) => ({
  method: e.method,
  path: e.path,
  re: new RegExp("^" + e.path.replace(/\{path\}/g, ".+").replace(/\{[^}]+\}/g, "[^/]+") + "$"),
}));

function matches({ method, path }: Sent, endpoint: string): boolean {
  const [m, template] = endpoint.split(" ");
  const route = ROUTES.find((r) => r.method === m && r.path === template);
  return !!route && method === m && route.re.test(path);
}

const SERVED = new Set(API_ENDPOINTS.map((e) => `${e.method} ${e.path}`));

/** Every exported function: the endpoint it is meant to call, and a call.
 *  Adding an API function without adding it here fails the coverage test. */
const CALLS: Record<string, Record<string, [string, () => unknown]>> = {
  projects: {
    createProject: ["POST /api/projects", () => projects.createProject({ name: "x" })],
    listProjects: ["GET /api/projects", () => projects.listProjects()],
    getProject: ["GET /api/projects/{project_id}", () => projects.getProject("p1")],
    updateProject: ["PATCH /api/projects/{project_id}", () => projects.updateProject("p1", { name: "x" })],
    listInputs: ["GET /api/projects/{project_id}/inputs", () => projects.listInputs("p1")],
    deleteInput: ["DELETE /api/projects/{project_id}/inputs/{input_id}", () => projects.deleteInput("p1", "i1")],
    deleteProject: ["DELETE /api/projects/{project_id}", () => projects.deleteProject("p1")],
    uploadInputs: ["POST /api/projects/{project_id}/inputs", () => projects.uploadInputs("p1", { files: [] })],
    analyze: ["POST /api/projects/{project_id}/analyze", () => projects.analyze("p1")],
    elementImages: ["POST /api/projects/{project_id}/element-images", () => projects.elementImages("p1")],
    reviewElementImages: ["PATCH /api/projects/{project_id}/element-images", () => projects.reviewElementImages("p1", { d1: true })],
    getElementImages: ["GET /api/projects/{project_id}/element-images", () => projects.getElementImages("p1")],
    repaintRoom: ["POST /api/projects/{project_id}/moodboard/rooms/{room_id}/repaint", () => projects.repaintRoom("p1", "living_room")],
    scenePlan: ["POST /api/projects/{project_id}/scene-plan", () => projects.scenePlan("p1")],
    resolveAssets: ["POST /api/projects/{project_id}/assets/resolve", () => projects.resolveAssets("p1")],
    build: ["POST /api/projects/{project_id}/build", () => projects.build("p1")],
    preview: ["POST /api/projects/{project_id}/preview", () => projects.preview("p1")],
    walkthrough: ["POST /api/projects/{project_id}/walkthrough", () => projects.walkthrough("p1")],
    film: ["POST /api/projects/{project_id}/film", () => projects.film("p1")],
    getAnalysis: ["GET /api/projects/{project_id}/analysis", () => projects.getAnalysis("p1")],
    patchAnalysis: ["PATCH /api/projects/{project_id}/analysis", () => projects.patchAnalysis("p1", {})],
    getSceneSpec: ["GET /api/projects/{project_id}/scene-spec", () => projects.getSceneSpec("p1")],
    getTradeoffs: ["GET /api/projects/{project_id}/tradeoffs", () => projects.getTradeoffs("p1")],
    getBuild: ["GET /api/projects/{project_id}/build", () => projects.getBuild("p1")],
    getJob: ["GET /api/jobs/{job_id}", () => projects.getJob("j1")],
    getEvents: ["GET /api/projects/{project_id}/events", () => projects.getEvents("p1", 3)],
    getSceneReading: ["GET /api/projects/{project_id}/scene-reading", () => projects.getSceneReading("p1")],
    reviewSceneReading: ["PATCH /api/projects/{project_id}/scene-reading", () => projects.reviewSceneReading("p1", { e1: true }, { e2: true })],
    getCredits: ["GET /api/credits", () => projects.getCredits()],
    generateElements: ["POST /api/projects/{project_id}/elements/generate", () => projects.generateElements("p1")],
    listVersions: ["GET /api/projects/{project_id}/versions", () => projects.listVersions("p1")],
    saveVersion: ["POST /api/projects/{project_id}/versions", () => projects.saveVersion("p1", { accept: true })],
    restoreVersion: ["POST /api/projects/{project_id}/versions/{version_id}/restore", () => projects.restoreVersion("p1", "v1")],
    getReview: ["GET /api/projects/{project_id}/review", () => projects.getReview("p1")],
  },
  viewer: {
    getHealth: ["GET /api/health", () => viewer.getHealth()],
    listScenes: ["GET /api/scenes", () => viewer.listScenes()],
    createScene: ["POST /api/scenes", () => viewer.createScene("x")],
    getScene: ["GET /api/scenes/{scene_id}", () => viewer.getScene("s1")],
    commitPatch: ["POST /api/scenes/{scene_id}/patches", () => viewer.commitPatch("s1", 1, [])],
    undo: ["POST /api/scenes/{scene_id}/undo", () => viewer.undo("s1")],
    redo: ["POST /api/scenes/{scene_id}/redo", () => viewer.redo("s1")],
    getTour: ["GET /api/scenes/{scene_id}/walkthrough/tour", () => viewer.getTour("s1")],
    getSpawn: ["GET /api/scenes/{scene_id}/walkthrough/spawn", () => viewer.getSpawn("s1")],
    createProposal: ["POST /api/scenes/{scene_id}/design/proposals", () => viewer.createProposal("s1", "add a plant")],
    applyProposal: ["POST /api/scenes/{scene_id}/design/proposals/{proposal_id}/apply", () => viewer.applyProposal("s1", "pr1")],
    rejectProposal: ["POST /api/scenes/{scene_id}/design/proposals/{proposal_id}/reject", () => viewer.rejectProposal("s1", "pr1")],
    getCatalog: ["GET /api/catalog", () => viewer.getCatalog("p1")],
    upgradeSceneAssets: ["POST /api/scenes/{scene_id}/assets/upgrade", () => viewer.upgradeSceneAssets("s1")],
    getMaterials: ["GET /api/materials", () => viewer.getMaterials()],
    getProvenance: ["GET /api/projects/{project_id}/provenance/{scene_object_id}", () => viewer.getProvenance("p1", "o1")],
  },
  auth: {
    signIn: ["POST /api/auth/login", () => auth.signIn("a@b.c", "pw")],
    register: ["POST /api/auth/register", () => auth.register("a@b.c", "pw")],
    currentUser: ["GET /api/auth/session", () => auth.currentUser()],
    signOut: ["POST /api/auth/logout", () => auth.signOut()],
  },
  tour: {
    getTour: ["GET /api/projects/{project_id}/tour", () => tour.getTour("p1")],
  },
};

/** Exports that are not requests: constants and pure URL builders. */
const NOT_REQUESTS: Record<string, string[]> = {
  projects: ["AETHER_BASE_URL", "fileUrl", "TERMINAL", "isTerminal"],
  viewer: ["AETHER_BASE_URL", "fileUrl"],
  auth: ["AuthError"],
  tour: ["AETHER_BASE_URL", "fileUrl"],
};
const MODULES: Record<string, Record<string, unknown>> = { projects, viewer, auth, tour };

describe("API contract (generated from the backend's OpenAPI)", () => {
  for (const [mod, calls] of Object.entries(CALLS)) {
    for (const [name, [endpoint, call]] of Object.entries(calls)) {
      it(`${mod}.${name} calls ${endpoint}`, async () => {
        expect(SERVED.has(endpoint), `${endpoint} is not a backend route`).toBe(true);
        try {
          await call();
        } catch {
          // Parsing the canned body may fail; the request was already recorded.
        }
        expect(sent.length, `${name} sent no request`).toBe(1);
        expect(matches(sent[0], endpoint), `${name} sent ${sent[0].method} ${sent[0].path}, not ${endpoint}`).toBe(true);
      });
    }
  }

  it("covers every exported API function", () => {
    for (const [mod, exports] of Object.entries(MODULES)) {
      const uncovered = Object.keys(exports).filter(
        (k) => !(k in CALLS[mod]) && !NOT_REQUESTS[mod].includes(k),
      );
      expect(uncovered, `${mod}: add these to CALLS or NOT_REQUESTS`).toEqual([]);
    }
  });

});
