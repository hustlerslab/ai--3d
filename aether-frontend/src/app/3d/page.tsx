import type { Metadata } from "next";

import { Walkthrough3DView } from "@/features/walkthrough3d/components/walkthrough3d-view";

export const metadata: Metadata = {
  title: "3D Walkthrough",
  description:
    "Interactive 3D walkthrough on the Aether engine — orbit, walk in first person, take the guided tour, and edit with validated AI proposals.",
};

/**
 * The raw viewer. Without a query it shows the seed apartment; `?scene=<id>`
 * opens any scene the engine holds (compiled project scenes included). The
 * Studio route (/) reaches the same component with a freshly generated scene.
 */
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ scene?: string }>;
}) {
  const { scene } = await searchParams;
  return <Walkthrough3DView sceneId={scene || undefined} />;
}
