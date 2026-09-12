import { ArrowLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { WalkthroughView } from "@/features/walkthrough/components/walkthrough-view";

export const metadata: Metadata = {
  title: "Cinematic Walkthrough",
  description:
    "Turn property photographs into a cinematic walkthrough film, room by room.",
};

/**
 * The photo-to-film studio, backed by the RE Walkthrough Pro engine on port
 * 4000. Optional: without that engine the view shows its own
 * "engine not running" state and nothing else is affected.
 */
export default function Page() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 body-sm text-ink-muted transition-colors hover:bg-muted hover:text-ink-soft"
        >
          <ArrowLeft className="size-3.5" />
          Back to Studio
        </Link>
      </div>
      <WalkthroughView />
    </div>
  );
}
