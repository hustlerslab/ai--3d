import type { Metadata } from "next";

import { ShareView } from "@/features/tour/components/share-view";

export const metadata: Metadata = {
  title: "Walkthrough",
  description: "A 360° walkthrough of your future home, rendered by Allure.",
};

/**
 * Public share link: /w/<projectId>. Read-only — it consumes the tour
 * package only, never the editing APIs.
 */
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <ShareView projectId={projectId} />;
}
