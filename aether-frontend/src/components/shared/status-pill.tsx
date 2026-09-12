import { cn } from "@/lib/utils";

/**
 * <StatusPill /> — colour **plus** a text label, always.
 *
 * Status is never communicated by colour alone anywhere in this product, so
 * this component has no label-less mode. The dot carries the functional
 * colour; the text carries the meaning.
 *
 * Note on contrast: --warning is roughly 3:1 on a light ground and fails AA
 * as small text, for the same reason gold is never body copy. So the
 * label is set in --ink-soft on a tint of the status colour rather than in the
 * status colour itself, and the saturated hue lives in the dot and the border
 * where contrast rules do not apply.
 */

export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";

const TONE_CLASS: Record<StatusTone, string> = {
  success: "bg-success/12 border-success/30",
  warning: "bg-warning/12 border-warning/30",
  danger: "bg-danger/12 border-danger/30",
  info: "bg-info/12 border-info/30",
  neutral: "bg-sand/60 border-tan/40",
};

const DOT_CLASS: Record<StatusTone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  neutral: "bg-ink-muted",
};

/**
 * Status → tone, per docs/03-design-system.md §8.
 *
 * "Revision Requested" maps to warning — a pending-action state, same family
 * as "Awaiting Client Approval".
 */
export const STATUS_TONE: Record<string, StatusTone> = {
  "On Track": "success",
  Approved: "success",
  "Handover Complete": "success",

  "Awaiting Client Approval": "warning",
  "Quotation Sent": "warning",
  Pending: "warning",
  "Revision Requested": "warning",

  Blocker: "danger",
  Delayed: "danger",
  "Delayed (On Hold)": "danger",
  Rejected: "danger",

  "In Design": "info",
  "In Execution": "info",
};

export const statusTone = (status: string): StatusTone => STATUS_TONE[status] ?? "neutral";

export interface StatusPillProps {
  /** The visible text. Required — there is no colour-only variant. */
  label: string;
  /**
   * Overrides the tone derived from `label`. Pass it when the text is a
   * paraphrase, e.g. "1 Blocker".
   */
  tone?: StatusTone;
  size?: "sm" | "md";
  className?: string;
}

export function StatusPill({ label, tone, size = "md", className }: StatusPillProps) {
  const resolved = tone ?? statusTone(label);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-pill border text-ink-soft font-medium whitespace-nowrap",
        size === "sm" ? "px-2.5 py-0.5 text-xs" : "px-3 py-1 caption",
        TONE_CLASS[resolved],
        className,
      )}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", DOT_CLASS[resolved])} aria-hidden />
      {label}
    </span>
  );
}
