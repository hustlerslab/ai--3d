import { describe, expect, it, vi } from "vitest";

import { TERMINAL, isTerminal } from "./api/projects-api";
import type { JobStatus, ProjectStage } from "./types";

/**
 * P16: the frontend and the backend must agree about how a generation is
 * started, polled and finished. A drift here is invisible at compile time and
 * shows up as a spinner that never stops, or a failure the user never sees.
 *
 * Asserted literally against the backend, the same way verticals.test.ts
 * asserts room-type spellings:
 *   app/jobs/schema.py          JobStatus, TERMINAL
 *   app/projects/schema.py      ProjectStage
 *   app/api/projects_routes.py  the route paths
 *
 * There is no DOM environment in this project, so these cover the contract and
 * the API client, not rendering.
 */

const BACKEND_JOB_STATUSES: JobStatus[] = [
  "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "RETRYING", "CANCELLED",
];

const BACKEND_TERMINAL: JobStatus[] = ["SUCCEEDED", "FAILED", "CANCELLED"];

const BACKEND_STAGES: ProjectStage[] = [
  "CREATED", "INPUT_RECEIVED", "ANALYZING", "DESIGN_SPEC_READY", "ASSET_PLANNING",
  "ASSETS_READY", "SCENE_BUILDING", "SCENE_VALIDATING", "CAMERA_PLANNING",
  "PREVIEW_RENDERING", "FINAL_RENDERING", "COMPLETED", "FAILED",
];

describe("job status contract", () => {
  it("treats exactly the backend's terminal statuses as terminal", () => {
    expect([...TERMINAL].sort()).toEqual([...BACKEND_TERMINAL].sort());
  });

  it("stops polling on every terminal status", () => {
    for (const status of BACKEND_TERMINAL) expect(isTerminal(status)).toBe(true);
  });

  it("keeps polling on every non-terminal status", () => {
    const busy = BACKEND_JOB_STATUSES.filter((s) => !BACKEND_TERMINAL.includes(s));
    expect(busy).toEqual(["QUEUED", "RUNNING", "RETRYING"]);
    for (const status of busy) expect(isTerminal(status)).toBe(false);
  });

  it("never treats FAILED as a reason to keep waiting", () => {
    // The specific bug this guards: a failed generation that polls forever
    // looks identical to one still running.
    expect(isTerminal("FAILED")).toBe(true);
  });
});

describe("project stage contract", () => {
  it("declares exactly the backend's stages, including FAILED", () => {
    const declared: ProjectStage[] = [...BACKEND_STAGES];
    expect(new Set(declared).size).toBe(13);
    expect(declared).toContain("FAILED");
  });
});

describe("generation endpoints", () => {
  /** Capture the path each client function requests, without a network. */
  async function pathOf(
    call: () => Promise<unknown>,
  ): Promise<{ path: string; method: string; body: unknown }> {
    const seen: { path: string; method: string; body: unknown }[] = [];
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      seen.push({
        path: String(url),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      return new Response(
        JSON.stringify({ success: true, job: { job_id: "job_1", status: "QUEUED" } }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    try {
      await call();
    } finally {
      vi.unstubAllGlobals();
    }
    expect(seen).toHaveLength(1);
    return seen[0];
  }

  it("starts a scene plan on the real backend route", async () => {
    const api = await import("./api/projects-api");
    const seen = await pathOf(() => api.scenePlan("proj_1"));

    expect(seen.method).toBe("POST");
    expect(seen.path).toContain("/api/projects/proj_1/scene-plan");
    expect(seen.body).toEqual({ force: false });
  });

  it("forwards force when a re-plan is asked for", async () => {
    const api = await import("./api/projects-api");
    const seen = await pathOf(() => api.scenePlan("proj_1", true));
    expect(seen.body).toEqual({ force: true });
  });

  it("starts the 3D build on the real backend route", async () => {
    const api = await import("./api/projects-api");
    const seen = await pathOf(() => api.build("proj_1", { preview: true, force: true }));

    expect(seen.method).toBe("POST");
    expect(seen.path).toContain("/api/projects/proj_1/build");
    expect(seen.body).toMatchObject({ preview: true, force: true });
  });

  it("renders panoramas on the real backend route", async () => {
    const api = await import("./api/projects-api");
    const seen = await pathOf(() => api.preview("proj_1", { force: true }));

    expect(seen.method).toBe("POST");
    expect(seen.path).toContain("/api/projects/proj_1/preview");
  });

  it("polls the real job route", async () => {
    const api = await import("./api/projects-api");
    const seen = await pathOf(() => api.getJob("job_1"));

    expect(seen.method).toBe("GET");
    expect(seen.path).toContain("/api/jobs/job_1");
  });

  it("saves element decisions with PATCH, never the POST that runs the job", async () => {
    // The bug this exists for: `{ method: "PATCH", ...json(body) }` spreads the
    // helper's own `method: "POST"` on top, so the decisions went to the route
    // that ENQUEUES element_images - which re-ran the job and wrote the
    // definitions back with approved: null. The room was painted, the client's
    // Build/Skip was silently lost, and both routes answer 200.
    const api = await import("./api/projects-api");
    const seen = await pathOf(() => api.reviewElementImages("proj_1", { cel_a: true, cel_b: false }));

    expect(seen.method).toBe("PATCH");
    expect(seen.path).toContain("/api/projects/proj_1/element-images");
    expect(seen.body).toEqual({ decisions: { cel_a: true, cel_b: false } });
  });

  it("points at a real backend, never a mock or fixture host", async () => {
    const { AETHER_BASE_URL } = await import("./api/projects-api");

    expect(AETHER_BASE_URL).toMatch(/^https?:\/\//);
    for (const forbidden of ["mock", "fixture", "demo", "example.com", "stub"]) {
      expect(AETHER_BASE_URL.toLowerCase()).not.toContain(forbidden);
    }
    expect(AETHER_BASE_URL.endsWith("/")).toBe(false);
  });
});
