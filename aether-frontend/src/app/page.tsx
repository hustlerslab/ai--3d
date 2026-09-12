import type { Metadata } from "next";

import { WalkthroughStudio } from "@/features/walkthrough-studio/components/walkthrough-studio";

export const metadata: Metadata = {
  title: "Studio",
  description:
    "From idea to walkable space: moodboard, refine, generate a 3D space, and share it.",
};

export default function Page() {
  return <WalkthroughStudio />;
}
