"use client";

import { Box, Check, Loader2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fileUrl } from "../api/projects-api";
import { buildElementInventory, humanIdentity, humanType } from "../element-inventory";
import type { CreditsDto, ElementCheck, SceneElement, SceneReadingDto } from "../types";

const human = (s: string) => s.replace(/_/g, " ");

/** What each verdict means to the person deciding, and how loudly to say it.
 *  `unchecked` and `unreadable` are deliberately not quiet: nobody has
 *  established what those crops show, which is not the same as them being fine. */
const VERDICT: Record<ElementCheck, { label: string; tone: string }> = {
  ok: { label: "looks right", tone: "border-transparent bg-muted text-ink-soft" },
  mismatch: { label: "shows something else", tone: "border-warning/50 bg-warning/10 text-ink-soft" },
  crowded: { label: "more than one thing", tone: "border-warning/50 bg-warning/10 text-ink-soft" },
  duplicate: { label: "already claimed", tone: "border-warning/50 bg-warning/10 text-ink-soft" },
  unreadable: { label: "could not tell", tone: "border-warning/50 bg-warning/10 text-ink-soft" },
  // Not a complaint about the picture — the crop may be a fine photograph of a
  // bath. The complaint is that it is in a living room, so the label reads as
  // something the model invented rather than saw.
  implausible: { label: "wrong room for this", tone: "border-warning/50 bg-warning/10 text-ink-soft" },
  unchecked: { label: "not checked", tone: "border-dashed text-ink-muted" },
};

/**
 * Element Review: the last human look before anything costs money.
 *
 * Every crop here is about to become a paid 3D generation, and the failure this
 * screen exists to catch is a crop that looks perfectly reasonable in a list —
 * a box of floorboards labelled "table lamp", the whole kitchen labelled
 * "kitchen counter". So the crop and its label are shown together, at a size
 * where they can actually be compared; the automatic check only decides what
 * order to show them in and what to warn about.
 *
 * Approving is deliberately explicit. Nothing is pre-ticked, because a default
 * of yes is not a decision, and an unreviewed element is held back rather than
 * generated on the assumption that silence meant approval.
 */
/**
 * P19: what the backend decided the room contains, shown as the backend
 * decided it. Three stools are three instances of one piece with one asset
 * because `summary.definitions` and `summary.instances` say so; this
 * component joins ids and renders. It never counts, groups or infers.
 */
function ElementInventory({ data }: { data: SceneReadingDto }) {
  const view = useMemo(() => buildElementInventory(data), [data]);
  if (view.unavailable) return null;

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="body-sm font-medium text-ink-soft">Element inventory</h4>
        <span className="caption text-ink-muted tabular">
          {view.detected_rows} detected · {view.canonical_count} canonical · {view.instance_count} instances
          · {view.asset_count} asset{view.asset_count === 1 ? "" : "s"}
        </span>
      </div>

      {view.groups.length ? (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {view.groups.map((g) => (
            <li key={g.element_id} className="flex flex-col gap-2 rounded-md border p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="body-sm text-ink-soft">{humanType(g.semantic_type)}</span>
                <span className="caption text-ink-muted">{human(g.room_id)}</span>
              </div>
              <span className="caption text-ink-muted tabular">
                {g.instance_count} instance{g.instance_count === 1 ? "" : "s"} ·{" "}
                {g.asset === "resolved" ? "1 canonical asset" : "asset unresolved"}
              </span>
              {g.instances.length ? (
                <ul className="flex flex-wrap gap-1.5">
                  {g.instances.map((i, n) => (
                    <li key={i.instance_id} className="flex flex-col items-center gap-0.5">
                      {i.crop_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={fileUrl(i.crop_url)}
                          alt={`${humanType(g.semantic_type)} instance ${n + 1}`}
                          title={i.instance_id}
                          className="h-14 w-14 rounded border bg-muted object-contain"
                        />
                      ) : (
                        <span className="flex h-14 w-14 items-center justify-center rounded border bg-muted caption text-ink-muted">
                          {n + 1}
                        </span>
                      )}
                      <span className="caption text-ink-muted">{String(n + 1).padStart(2, "0")}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              <span
                className={`w-fit rounded-full border px-2 py-0.5 caption ${
                  g.state === "unresolved" ? "border-ink-muted text-ink-muted" : "border-gold/60 text-ink-soft"
                }`}
                title={humanIdentity(g.identity)}
              >
                {g.state === "unresolved" ? "Identity unresolved" : "Validated"}
              </span>
              <span className="caption text-ink-muted">{humanIdentity(g.identity)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="caption text-ink-muted">No piece survived the checks.</p>
      )}

      {view.rejected.length ? (
        <div className="flex flex-col gap-1.5">
          <span className="caption text-ink-muted">Detected but not used</span>
          <ul className="flex flex-col gap-1">
            {view.rejected.map((r) => (
              <li key={r.element.element_id} className="flex flex-wrap items-baseline gap-2 caption">
                <span className="text-ink-soft">{humanType(r.element.semantic_type)}</span>
                <span className="text-ink-muted">{human(r.element.room_id)}</span>
                <span className="rounded-full border border-dashed px-2 py-0.5 text-ink-muted">
                  Rejected: {r.reason}
                </span>
                {r.note ? <span className="text-ink-muted">{r.note}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function ElementReview({
  data,
  onSave,
  saving = false,
  credits = null,
  onGenerate,
  generating = false,
}: {
  data: SceneReadingDto;
  onSave: (decisions: Record<string, boolean>) => Promise<void>;
  saving?: boolean;
  /** Remaining Meshy credits, or null while unknown. */
  credits?: CreditsDto | null;
  /** The paid step. Absent on read-only screens. */
  onGenerate?: () => Promise<void>;
  generating?: boolean;
}) {
  const { reading, summary } = data;
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);

  const withCrops = useMemo(
    () => reading.elements.filter((e) => e.crop_ref),
    [reading.elements],
  );

  // Re-seed from whatever the server last told us. Deliberately does NOT clear
  // `saved`: this effect re-runs on the PATCH response too, and clearing it
  // there wiped the confirmation the moment it was earned, so a reviewer who
  // had just saved successfully was shown no sign of it.
  useEffect(() => {
    setDecisions(
      Object.fromEntries(
        withCrops.filter((e) => e.approved !== null).map((e) => [e.element_id, e.approved as boolean]),
      ),
    );
  }, [withCrops]);

  // Flagged first: those are the ones that need a real look, and a reviewer who
  // stops halfway should have spent their attention on them.
  const ordered = useMemo(() => {
    const rank = (e: SceneElement) => (e.check === "ok" ? 1 : 0);
    return [...withCrops].sort(
      (a, b) => rank(a) - rank(b) || a.room_id.localeCompare(b.room_id) || a.name.localeCompare(b.name),
    );
  }, [withCrops]);

  const decide = (id: string, value: boolean) =>
    setDecisions((d) => {
      const next = { ...d };
      if (next[id] === value) delete next[id];   // clicking again un-decides
      else next[id] = value;
      setSaved(false);
      return next;
    });

  const values = Object.values(decisions);
  const yes = values.filter(Boolean).length;
  const no = values.length - yes;
  const pending = withCrops.length - values.length;

  const short =
    credits?.available === true && typeof credits.balance === "number"
      ? credits.balance < summary.credits_needed
      : false;
  const creditLine =
    credits === null
      ? ""
      : credits.available && typeof credits.balance === "number"
        ? `${credits.balance.toLocaleString()} credits left`
        : `credits unavailable — ${credits.reason ?? "unknown"}`;

  const save = async () => {
    await onSave(decisions);
    setSaved(true);
  };

  if (!withCrops.length) {
    return (
      <div className="rounded-md border border-dashed px-4 py-6 text-center body-sm text-ink-muted">
        Nothing was cut out of the approved rooms yet. Run the scene plan first.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-lg border border-gold/40 bg-gold/5 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="body text-ink">Confirm what gets built</h3>
          <span className="caption text-ink-muted tabular">
            read by {reading.provider} · {summary.flagged_by_check} of {withCrops.length} flagged
          </span>
        </div>
        <p className="caption text-ink-muted">
          Each picture below becomes a 3D model. Check that it really shows what it says
          underneath — a box can be the right shape and still be around the wrong thing.
          Anything you don&apos;t confirm is left out rather than guessed at.
        </p>
      </div>

      <ElementInventory data={data} />

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {ordered.map((el) => {
          const verdict = VERDICT[el.check] ?? VERDICT.unchecked;
          const choice = decisions[el.element_id];
          return (
            <li
              key={el.element_id}
              className={`flex flex-col overflow-hidden rounded-md border ${
                choice === true ? "border-gold" : choice === false ? "border-dashed opacity-60" : ""
              }`}
            >
              {/* Contained, not cropped to fill: a crop cropped again hides
                  exactly the edge that shows the box caught a neighbour. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={fileUrl(el.crop_url)}
                alt={el.name}
                className="h-36 w-full bg-muted object-contain"
              />
              <div className="flex flex-1 flex-col gap-1.5 p-2">
                <span className="body-sm text-ink-soft">{el.name}</span>
                <span className="caption text-ink-muted">
                  {human(el.room_id)} · {human(el.semantic_type)}
                </span>
                {el.position_m ? (
                  // Where the picture put it, in metres from the back-left corner.
                  // An anchor the planner prefers, not the final position.
                  <span className="caption text-ink-muted tabular">
                    {el.wall ? `${el.wall} wall · ` : ""}
                    x {el.position_m[0].toFixed(1)} · y {el.position_m[1].toFixed(1)} · z {el.position_m[2].toFixed(1)} m
                    {el.facing ? ` · faces ${el.facing}` : ""}
                    {/* An estimate off the crop box is not what the reader said.
                        Saying which is which is the whole point of storing it. */}
                    {el.position_source === "derived" ? " · estimated" : ""}
                  </span>
                ) : null}
                <span className={`w-fit rounded-full border px-2 py-0.5 caption ${verdict.tone}`}>
                  {verdict.label}
                </span>
                {el.check_note && el.check !== "ok" ? (
                  <span className="caption text-ink-muted">{el.check_note}</span>
                ) : null}
                <div className="mt-auto flex gap-1.5 pt-1.5">
                  <button
                    type="button"
                    onClick={() => decide(el.element_id, true)}
                    className={`flex flex-1 items-center justify-center gap-1 rounded-md border px-2 py-1 caption ${
                      choice === true ? "border-gold bg-gold/10 text-ink" : "text-ink-muted hover:bg-muted"
                    }`}
                  >
                    <Check className="size-3" /> Build
                  </button>
                  <button
                    type="button"
                    onClick={() => decide(el.element_id, false)}
                    className={`flex flex-1 items-center justify-center gap-1 rounded-md border px-2 py-1 caption ${
                      choice === false ? "border-ink-muted bg-muted text-ink" : "text-ink-muted hover:bg-muted"
                    }`}
                  >
                    <X className="size-3" /> Skip
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="caption text-ink-muted tabular">
          {yes} to build · {no} skipped
          {pending ? ` · ${pending} still to decide` : ""}
        </span>
        <button
          type="button"
          onClick={save}
          disabled={saving || !values.length}
          className="flex items-center gap-2 rounded-md border px-3 py-1.5 body-sm text-ink-soft hover:bg-muted disabled:opacity-40"
        >
          {saving ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
          {saved && !saving ? "Saved" : "Save decisions"}
        </button>
      </div>

      {onGenerate ? (
        <div className="flex flex-col gap-3 rounded-lg border border-gold/40 bg-gold/5 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="body-sm font-medium text-ink-soft">Build the confirmed pieces in 3D</h4>
            <span className="caption text-ink-muted tabular">{creditLine}</span>
          </div>
          {/* The exact number that will be spent, computed the way the job
              computes it — pieces already built are reused and cost nothing,
              and saying so is what stops this reading as a surprise charge. */}
          <p className="caption text-ink-muted">
            {summary.to_generate > 0 ? (
              <>
                {summary.to_generate} piece{summary.to_generate === 1 ? "" : "s"} to build
                {summary.already_generated > 0
                  ? `, ${summary.already_generated} already built and reused free`
                  : ""}
                . Costs {summary.credits_needed} credits.
                {short ? " That is more than the balance." : ""}
              </>
            ) : summary.approved === 0 ? (
              "Confirm at least one piece above, then come back here."
            ) : (
              `All ${summary.already_generated} confirmed piece${summary.already_generated === 1 ? " is" : "s are"} already built. Nothing to pay for.`
            )}
          </p>
          <button
            type="button"
            onClick={() => void onGenerate()}
            disabled={generating || summary.to_generate === 0 || short}
            className="flex w-fit items-center gap-2 rounded-md bg-gold px-4 py-2 body-sm font-medium text-ink hover:opacity-90 disabled:opacity-40"
          >
            {generating ? <Loader2 className="size-4 animate-spin" /> : <Box className="size-4" />}
            {generating
              ? "Building…"
              : summary.to_generate > 0
                ? `Build ${summary.to_generate} piece${summary.to_generate === 1 ? "" : "s"} · ${summary.credits_needed} credits`
                : "Nothing to build"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
