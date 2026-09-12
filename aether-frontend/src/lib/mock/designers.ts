import type { Designer, DesignerMatch } from "./types";

/**
 * Designers — docs/02-mock-data-spec.md.
 *
 * des-004 at a 45% win rate and des-006 awaiting vetting are deliberate. A
 * roster where everyone is excellent reads as invented. Do not raise either.
 *
 * The spec fixes name, studio, style, win rate, active bids and vetting. City
 * is stated only for Ananya (Patna presence) and Divya (Indore-based); the
 * other four are assigned here across the two primary markets.
 *
 * `philosophy` is unspecified copy, written here from each designer's style and
 * city. It exists because the landing page's editorial spread (§7) needs a
 * designer to sound like a person; a studio name and a win rate do not carry a
 * section built to read like a magazine. All six carry one so the field is not
 * a landing-page special case — the portfolio pages will want it too.
 */
export const DESIGNERS: readonly Designer[] = [
  {
    id: "des-001",
    name: "Ananya Sharma",
    studio: "Studio Verve",
    style: "Warm Minimalism",
    winRate: 68,
    // Two, not three — bid-3 was reassigned to des-002. See bids.ts.
    activeBids: 2,
    vetting: "verified",
    city: "Patna",
    avatar: "/avatars/43.jpg",
    philosophy:
      "Restraint is not emptiness. A room should hold one idea clearly rather than six of them politely.",
  },
  {
    id: "des-002",
    name: "Vikram Nair",
    studio: "Nair & Co.",
    style: "Contemporary Indian",
    winRate: 74,
    activeBids: 5,
    vetting: "verified",
    city: "Indore",
    avatar: "/avatars/59.jpg",
    philosophy:
      "An Indian home is not a museum. I design for how three generations actually use the same room on a Sunday afternoon.",
  },
  {
    id: "des-003",
    name: "Divya Rathore",
    studio: "Atelier Rathore",
    style: "Organic Modernism",
    winRate: 61,
    activeBids: 2,
    vetting: "verified",
    city: "Indore",
    avatar: "/avatars/16.jpg",
    philosophy:
      "I start with how the light crosses a plan through the day, and let the materials answer it.",
  },
  {
    id: "des-004",
    name: "Arjun Menon",
    studio: "Form Studio",
    style: "Industrial Luxe",
    // Deliberate. The roster needs someone who loses more than they win.
    winRate: 45,
    activeBids: 1,
    vetting: "verified",
    city: "Patna",
    avatar: "/avatars/56.jpg",
    philosophy:
      "Structure is the ornament. If the frame is honest, it does not need dressing up afterwards.",
  },
  {
    id: "des-005",
    name: "Ishita Bose",
    studio: "Bose Interiors",
    style: "Heritage Revival",
    winRate: 70,
    activeBids: 4,
    vetting: "verified",
    city: "Bhubaneswar",
    avatar: "/avatars/23.jpg",
    philosophy:
      "Old craft is not nostalgia. A jaali screen still solves heat and privacy better than most things invented since.",
  },
  {
    id: "des-006",
    name: "Nikhil Gupta",
    studio: "Grid Design Co.",
    style: "Scandinavian Fusion",
    winRate: 52,
    activeBids: 2,
    // Deliberate. One designer still in the vetting queue.
    vetting: "pending",
    city: "Indore",
    avatar: "/avatars/67.jpg",
    philosophy:
      "Warm woods, cool discipline. The two only fight each other if you get the proportions wrong.",
  },
];

/** The designer portal is signed in as Ananya Sharma. */
export const CURRENT_DESIGNER_ID = "des-001";

export const designerById = (id: string): Designer | undefined =>
  DESIGNERS.find((designer) => designer.id === id);

/**
 * AI match scores for prop-001 — exactly five, matching the "Top 5" rule from
 * the journey. Surfaced in onboarding and on the homeowner dashboard.
 */
export const DESIGNER_MATCHES: readonly DesignerMatch[] = [
  {
    designerId: "des-001",
    propertyId: "prop-001",
    score: 93,
    reason: "Style + budget band + Patna presence",
  },
  {
    designerId: "des-002",
    propertyId: "prop-001",
    score: 87,
    reason: "Style match, higher budget band",
  },
  {
    designerId: "des-003",
    propertyId: "prop-001",
    score: 81,
    reason: "Style match, Indore-based",
  },
  {
    designerId: "des-005",
    propertyId: "prop-001",
    score: 74,
    reason: "Adjacent style",
  },
  {
    designerId: "des-006",
    propertyId: "prop-001",
    score: 68,
    reason: "Budget match only",
  },
];

export const matchesForProperty = (propertyId: string): DesignerMatch[] =>
  DESIGNER_MATCHES.filter((match) => match.propertyId === propertyId);
