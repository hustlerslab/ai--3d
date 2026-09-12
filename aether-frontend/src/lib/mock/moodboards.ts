import type { ImageSlot } from "./images";

/**
 * Moodboard concepts for the Walkthrough Studio flow.
 *
 * The "AI generates a personalized moodboard" step is mock, like everything
 * outside the two walkthrough engines — so these are hand-written concepts
 * composed from the existing photography set. Regenerate cycles through them
 * in order, which keeps the demo identical every run (project rule 3).
 *
 * Palette hexes live here as data, not in components; they are rendered as
 * swatches with inline style the same way designer avatars are rendered from
 * their URLs.
 */
export interface PaletteSwatch {
  name: string;
  hex: string;
}

export interface MoodboardConcept {
  id: string;
  name: string;
  /** One line of designer-voice rationale shown under the board title. */
  caption: string;
  imageSlots: ImageSlot[];
  materialSlots: ImageSlot[];
  palette: PaletteSwatch[];
}

export const MOODBOARD_CONCEPTS: readonly MoodboardConcept[] = [
  {
    id: "mood-001",
    name: "Warm Sandstone",
    caption:
      "Low contrast, layered neutrals and oak — a calm base that lets one brass accent carry the room.",
    imageSlots: ["gallery-1", "gallery-3", "gallery-5"],
    materialSlots: ["material-oak", "material-linen", "material-brass"],
    palette: [
      { name: "Cream", hex: "#EEE2D2" },
      { name: "Sand", hex: "#E6D3BF" },
      { name: "Tan", hex: "#C8AE8C" },
      { name: "Ink", hex: "#131313" },
    ],
  },
  {
    id: "mood-002",
    name: "Quiet Marble",
    caption:
      "Cooler stone against warm wood — for rooms that get hard afternoon light and need it softened.",
    imageSlots: ["gallery-2", "gallery-4", "gallery-1"],
    materialSlots: ["material-marble", "material-walnut", "material-linen"],
    palette: [
      { name: "Ivory", hex: "#F2EDE4" },
      { name: "Stone", hex: "#D9D2C5" },
      { name: "Walnut", hex: "#6B4F35" },
      { name: "Copper", hex: "#C87F5A" },
    ],
  },
  {
    id: "mood-003",
    name: "Terrazzo Evening",
    caption:
      "Speckled surfaces and deeper wood — a little more drama without leaving the warm-neutral family.",
    imageSlots: ["gallery-4", "gallery-5", "gallery-2"],
    materialSlots: ["material-terrazzo", "material-walnut", "material-brass"],
    palette: [
      { name: "Beige", hex: "#E1CCB1" },
      { name: "Terracotta", hex: "#B06A45" },
      { name: "Walnut", hex: "#6B4F35" },
      { name: "Gold", hex: "#B88538" },
    ],
  },
] as const;
