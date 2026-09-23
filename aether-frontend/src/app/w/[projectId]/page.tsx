import type { Metadata } from "next";

import { ShareView } from "@/features/tour/components/share-view";

export const metadata: Metadata = {
  title: "Walkthrough",
  description: "A 360° walkthrough of your future home, rendered by Allure.",
};

/**
 * Share link: /w/<projectId>?k=<token>. Read-only — it consumes the tour
 * package only, never the editing APIs.
 *
 * P0-SEC-004: the `k` is the capability. The project id identifies which
 * project; it no longer grants access to it, because an id travels in URLs,
 * logs and support emails and the owner can neither rotate nor revoke it.
 * A signed-in owner needs no `k` — their session is enough.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ k?: string }>;
}) {
  const { projectId } = await params;
  const { k } = await searchParams;
  return <ShareView projectId={projectId} token={k} />;
}
