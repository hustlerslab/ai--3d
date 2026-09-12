import type { ReactNode } from "react";

/**
 * The heading block every portal page opens with.
 *
 * Playfair earns its place here and only here on a dashboard: this is a page
 * title, not UI chrome. Everything below it is Inter.
 */
export function PageHeader({
  overline,
  title,
  meta,
  actions,
}: {
  overline: string;
  title: string;
  /** One line of context under the title. Where the record identifies itself. */
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
      <div className="flex flex-col gap-1.5">
        <p className="overline text-ink-muted">{overline}</p>
        <h1 className="display-md text-ink-soft">{title}</h1>
        {meta ? <div className="body-sm flex flex-wrap items-center gap-x-3 gap-y-1 text-ink-muted">{meta}</div> : null}
      </div>
      {actions ? <div className="flex items-center gap-3">{actions}</div> : null}
    </header>
  );
}

/** A hairline section heading for the blocks inside a page. */
export function SectionHeading({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
      <h2 className="overline text-ink-muted">{title}</h2>
      {hint ? <p className="caption tabular text-ink-muted">{hint}</p> : null}
      {action}
    </div>
  );
}
