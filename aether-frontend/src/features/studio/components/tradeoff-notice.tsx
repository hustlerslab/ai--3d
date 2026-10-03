"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import { getTradeoffs } from "../api/projects-api";
import type { TradeoffDto } from "../types";

/**
 * P1-SPATIAL-002: what the plan could not fit, said the way a person would
 * say it, with the choices they have. The words come from the backend, which
 * guarantees no internal key or code reaches them; this renders and never
 * rephrases. The options are listed, not buttons: nothing here acts on them
 * yet, and a button that does nothing would be a promise the app breaks.
 */
export function TradeoffList({ tradeoffs }: { tradeoffs: TradeoffDto[] }) {
  if (!tradeoffs.length) return null;
  return (
    <section
      aria-label="Pieces that did not fit"
      className="flex flex-col gap-3 rounded-lg border border-warning/50 bg-warning/5 p-4"
    >
      {tradeoffs.map((t, i) => (
        <div key={`${t.kind}-${t.room}-${i}`} className="flex flex-col gap-2">
          <p className="flex items-start gap-2 body-sm text-ink">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
            {t.statement}
          </p>
          <div className="flex flex-col gap-1 pl-6">
            <span className="caption text-ink-muted">What you can do</span>
            <ul className="flex flex-col gap-1">
              {t.options.map((o) => (
                <li key={o.id} className="caption text-ink-soft">
                  · {o.label}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ))}
    </section>
  );
}

export function TradeoffNotice({ projectId, refreshKey }: { projectId: string; refreshKey: string | number }) {
  const [tradeoffs, setTradeoffs] = useState<TradeoffDto[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    getTradeoffs(projectId, ctrl.signal)
      .then(setTradeoffs)
      .catch(() => setTradeoffs([]));
    return () => ctrl.abort();
  }, [projectId, refreshKey]);

  return <TradeoffList tradeoffs={tradeoffs} />;
}
