import type { Metadata } from "next";

import { AuthGate } from "@/features/auth/components/auth-gate";
import { WalkthroughStudio } from "@/features/walkthrough-studio/components/walkthrough-studio";

export const metadata: Metadata = {
  title: "Studio",
  description:
    "From idea to walkable space: moodboard, refine, generate a 3D space, and share it.",
};

export default function Page() {
  // P0-SEC-002 closed 60 of 63 API routes. Without the gate every call in the
  // studio returns 401 and the UI reports a network error it cannot explain.
  return (
    <AuthGate>
      <WalkthroughStudio />
    </AuthGate>
  );
}
