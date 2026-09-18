"use client";

import { AlertCircle, Check, HelpCircle } from "lucide-react";

import type { SceneSpecDto } from "../types";

/**
 * What the spatial engine verified about the committed plan: hard validation
 * violations (`validate_scene`), the P4 repair outcome, and the independent
 * intent check of the plan's own "facing" relations. Read-only; the numbers
 * are the backend's, not derived here. Relation types the evaluator cannot
 * check yet are listed as such rather than hidden.
 */
export function SpatialCheckPanel({ spec }: { spec: SceneSpecDto }) {
  const hard = spec.violations.filter((v) => v.severity === "hard");
  const soft = spec.violations.filter((v) => v.severity !== "hard");
  const check = spec.spatial_check ?? null;
  const intent = check?.intent ?? null;
  const unsupported = intent ? Object.entries(intent.unsupported_relations) : [];
  const violated = intent?.results.filter((r) => r.verdict === "violated") ?? [];

  return (
    <section className="flex flex-col gap-2 rounded-md border p-4" aria-label="Spatial check">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <p className="body-sm font-medium text-ink-soft">Spatial check</p>
        <Line ok={hard.length === 0} text={hard.length === 0 ? "No hard violations" : `${hard.length} hard violation${hard.length === 1 ? "" : "s"}`} />
        {soft.length ? <Line ok={null} text={`${soft.length} soft`} /> : null}
        {check?.repair ? (
          <Line
            ok={check.repair.hard_after === 0}
            text={
              check.repair.terminal_state === "ALREADY_VALID"
                ? "Repair: nothing to fix"
                : `Repair: ${check.repair.terminal_state.toLowerCase()} · moved ${check.repair.moved.length}`
            }
          />
        ) : null}
        {intent ? (
          <Line
            ok={intent.violated === 0 ? (intent.satisfied > 0 ? true : null) : false}
            text={`Facing: ${intent.satisfied} kept · ${intent.violated} not met${intent.unknown ? ` · ${intent.unknown} unknown` : ""}`}
          />
        ) : null}
      </div>
      {hard.length ? (
        <ul className="caption text-ink-muted">
          {hard.slice(0, 6).map((v, i) => (
            <li key={`${v.code}-${i}`}>{v.code}: {v.message}</li>
          ))}
        </ul>
      ) : null}
      {violated.length ? (
        <ul className="caption text-ink-muted">
          {violated.slice(0, 6).map((r) => (
            <li key={r.constraint_id}>{r.message}</li>
          ))}
        </ul>
      ) : null}
      {unsupported.length ? (
        <p className="caption text-ink-muted">
          Not checked yet: {unsupported.map(([t, n]) => `${t.replace(/_/g, " ")} (${n})`).join(", ")}
        </p>
      ) : null}
      <DesignIntentRows spec={spec} />
    </section>
  );
}

const CLASS_LABEL: Record<string, string> = {
  exact_object: "your piece",
  design_reference: "look reference",
  style_reference: "style",
  inspiration_only: "inspiration",
  uncertain: "needs a decision",
};

/**
 * What your reference photos were understood to mean, and how much of that
 * reached the 3D scene. Every number here is the backend's own — an unresolved
 * intent shows the engine's actual reason rather than a generic "done".
 */
function DesignIntentRows({ spec }: { spec: SceneSpecDto }) {
  const intent = spec.design_intent ?? null;
  const fidelity = spec.visual_intent_fidelity ?? null;
  if (!intent || !intent.reference_ids.length) return null;

  const counts = intent.intents.reduce<Record<string, number>>((acc, i) => {
    acc[i.reference_class] = (acc[i.reference_class] ?? 0) + 1;
    return acc;
  }, {});
  const blocked = (fidelity?.resolutions ?? []).filter((r) => r.needs_input);
  const generating = (fidelity?.resolutions ?? []).filter((r) => r.rung === "generate");
  const appearance = fidelity?.metrics.appearance_fidelity;

  return (
    <div className="flex flex-col gap-1 border-t pt-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <p className="body-sm font-medium text-ink-soft">Your references</p>
        <Line
          ok={intent.unread.length === 0}
          text={`${intent.intents.length} of ${intent.reference_ids.length} read${
            intent.unread.length ? ` · ${intent.unread.length} unreadable` : ""
          }`}
        />
        {Object.entries(counts).map(([cls, n]) => (
          <span key={cls} className="caption text-ink-muted">
            {n} {CLASS_LABEL[cls] ?? cls.replace(/_/g, " ")}
          </span>
        ))}
        {appearance !== null && appearance !== undefined ? (
          <Line ok={appearance === 1} text={`Appearance kept: ${Math.round(appearance * 100)}%`} />
        ) : null}
      </div>
      {intent.conflicts.length ? (
        <ul className="caption text-ink-muted">
          {intent.conflicts.slice(0, 4).map((c, i) => (
            <li key={`${c.attribute}-${i}`}>{c.message}</li>
          ))}
        </ul>
      ) : null}
      {generating.length ? (
        <p className="caption text-ink-muted">
          To be made: {generating.map((r) => r.object_category.replace(/_/g, " ")).join(", ")}
        </p>
      ) : null}
      {blocked.length ? (
        <ul className="caption text-ink-muted">
          {blocked.slice(0, 4).map((r) => (
            <li key={r.object_category}>
              {r.object_category.replace(/_/g, " ")}: {r.reason}
            </li>
          ))}
        </ul>
      ) : null}
      {intent.unread.length ? (
        <p className="caption text-ink-muted">Could not read: {intent.unread.join(", ")}</p>
      ) : null}
    </div>
  );
}

function Line({ ok, text }: { ok: boolean | null; text: string }) {
  const Icon = ok === true ? Check : ok === false ? AlertCircle : HelpCircle;
  return (
    <span className="flex items-center gap-1 caption text-ink-muted">
      <Icon className="size-3.5" aria-hidden />
      {text}
    </span>
  );
}
