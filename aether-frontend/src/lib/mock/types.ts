/**
 * Mock data types — docs/02-mock-data-spec.md.
 *
 * Everything the demo renders is typed here and imported through
 * `@/lib/mock`. That single boundary is deliberate: it is the seam a real
 * backend would replace later without touching a component.
 */

/* ── Roles ─────────────────────────────────────────────────────────────── */

export type Role = "homeowner" | "designer" | "builder" | "vendor";

/** The three roles with a built portal. Vendor is reserved (PRD §3). */
export type PortalRole = Exclude<Role, "vendor">;

/* ── Geography ─────────────────────────────────────────────────────────── */

export type City = "Patna" | "Indore" | "Bhubaneswar" | "Jaipur" | "Lucknow";

export type Region =
  | "North India"
  | "East India"
  | "West India"
  | "Central India"
  | "South India";

export interface CityRecord {
  city: City;
  region: Region;
  localities: readonly string[];
  /** Patna and Indore are the primary markets and carry visual emphasis. */
  primary: boolean;
  /**
   * Real coordinates, decimal degrees. The onboarding map projects these
   * itself rather than storing screen positions, so a pin cannot end up in
   * the Bay of Bengal because someone adjusted the artwork.
   */
  coords: { lat: number; lon: number };
}

/* ── Property ──────────────────────────────────────────────────────────── */

export type PropertyType =
  | "Independent Villa"
  | "Penthouse Apartment"
  | "3-4 BHK Apartment"
  | "Farmhouse";

export type BudgetBand = "₹15L – ₹40L" | "₹40L – ₹1Cr" | "₹1Cr+";

export type ProjectStatus =
  | "Awaiting Client Approval"
  | "In Design"
  | "Quotation Sent"
  | "Revision Requested"
  | "In Execution"
  | "Delayed"
  | "Handover Complete";

export interface Property {
  id: string;
  name: string;
  type: PropertyType;
  locality: string;
  city: City;
  /** Carpet area in square feet. */
  carpetArea: number;
  /** Whole rupees. Never paise, never any other currency. */
  budget: number;
  budgetBand: BudgetBand;
  deployed: number;
  nextMilestone: number;
  /** 1–17, indexing into JOURNEY_PHASES. */
  currentPhase: number;
  status: ProjectStatus;
  /** ISO date. */
  startDate: string;
  /** ISO date. */
  targetHandover: string;
  heroImage: string;
  ownerId: string;
  designerId: string | null;
  builderId: string | null;
  /**
   * The last thing the client said, for the designer's project card.
   *
   * Null only where a project is genuinely new and no conversation has
   * started. prop-001 is the exception: it has a real collaboration feed, so
   * its card derives the latest message from there rather than duplicating it
   * here where the two could drift apart.
   */
  latestClientMessage: string | null;
}

/**
 * The extra figures the spec defines only for the hero record. Kept off
 * `Property` so the eight records stay exactly as specified rather than
 * carrying seven sets of invented revision counts.
 */
export interface PropertyDetail {
  propertyId: string;
  /** ISO date the next milestone falls due. */
  nextMilestoneDue: string;
  /** The amount the OTP modal releases from escrow. */
  escrowRelease: number;
  revisionsUsed: number;
  revisionsAllowed: number;
  designersInConversation: number;
  designersAllowed: number;
}

/* ── People ────────────────────────────────────────────────────────────── */

export interface Homeowner {
  id: string;
  name: string;
  city: City;
  propertyIds: readonly string[];
  avatar: string;
}

export type DesignStyle =
  | "Warm Minimalism"
  | "Contemporary Indian"
  | "Organic Modernism"
  | "Industrial Luxe"
  | "Heritage Revival"
  | "Scandinavian Fusion";

export type VettingStatus = "verified" | "pending";

export interface Designer {
  id: string;
  name: string;
  studio: string;
  style: DesignStyle;
  /** Percentage, 0–100. */
  winRate: number;
  activeBids: number;
  vetting: VettingStatus;
  city: City;
  avatar: string;
  /**
   * One line, first person, in the designer's own voice. The landing page's
   * editorial spread needs a designer to sound like a person rather than a
   * row in a table; the spec names the field but writes no copy, so these are
   * written from each designer's style and city.
   */
  philosophy: string;
}

export interface Builder {
  id: string;
  company: string;
  city: City;
  /** Percentage, 0–100. */
  onTimeRate: number;
  bonded: boolean;
  activeSites: number;
  avatar: string;
}

/** A ranked designer suggestion produced by the match step (phase 8). */
export interface DesignerMatch {
  designerId: string;
  propertyId: string;
  /** Percentage, 0–100. */
  score: number;
  reason: string;
}

/* ── Journey ───────────────────────────────────────────────────────────── */

export type PhaseGroup =
  | "Entry"
  | "Discovery"
  | "AI"
  | "Matching"
  | "Designer Interaction"
  | "Execution";

export type PhaseStatus = "complete" | "active" | "upcoming";

export interface JourneyPhase {
  /** 1–17. */
  number: number;
  name: string;
  group: PhaseGroup;
  /** The parenthetical qualifier the journey doc attaches to some phases. */
  note?: string;
}

export interface DesignerTab {
  id: string;
  label: string;
  /** Inclusive journey-phase range this tab collects. */
  phases: readonly [number, number];
}

/* ── Builder sites ─────────────────────────────────────────────────────── */

export type SiteStatus = "On Track" | "Blocker";

export interface SiteBlocker {
  title: string;
  detail: string;
  /** ISO date. */
  raised: string;
}

export interface SiteProgress {
  /** The builder's own cosmetic phase label, e.g. "Phase 4 · MEP Rough-In". */
  phaseLabel: string;
  /** Percentage complete within that phase, 0–100. */
  percent: number;
  /** Positive means behind schedule. */
  daysBehind: number;
}

export type MaterialStatus = "Delivered" | "In Transit" | "Delayed (On Hold)";

export interface SiteMaterial {
  name: string;
  status: MaterialStatus;
  /**
   * Null where the spec does not name one. Only the blocked material carries a
   * vendor, and it is the only one that needs the CALL VENDOR action.
   */
  vendor: string | null;
  /** ISO date. Null once the material is delivered. */
  eta: string | null;
}

export interface BuilderSite {
  id: string;
  propertyId: string;
  builderId: string;
  name: string;
  /** Builder phases run on their own cosmetic scale — see PRD §6. */
  constructionPhase: string;
  status: SiteStatus;
  blockerCount: number;
  blocker: SiteBlocker | null;
  progress: SiteProgress | null;
  materials: readonly SiteMaterial[];
}

/* ── Workspace ─────────────────────────────────────────────────────────── */

/** Feed entries are role-coloured; `system` is the OTP/approval audit line. */
export type FeedAuthorRole = PortalRole | "system";

export interface FeedEntry {
  id: string;
  propertyId: string;
  role: FeedAuthorRole;
  authorId: string | null;
  authorName: string;
  message: string;
  /** Display time as it appears in the feed, e.g. "9:14 AM". */
  time: string;
}

/* ── Homeowner dashboard ───────────────────────────────────────────────── */

export type ActionVariant = "primary" | "secondary" | "destructive";

export interface ActionButton {
  label: string;
  variant: ActionVariant;
}

export interface ActionCard {
  id: string;
  propertyId: string;
  overline: string;
  title: string;
  body: string;
  /**
   * Figures rendered under the body — a revised-against-original comparison,
   * a range, a single total. Rupee values, so render them with `tabular`.
   */
  figures?: readonly { label: string; amount: number }[];
  actions: readonly ActionButton[];
}

export interface FinancialSegment {
  id: string;
  label: string;
  amount: number;
  /** Percentage of total budget, 0–100. */
  share: number;
  /** Which chart series token paints this segment. */
  tone: "deployed" | "milestone" | "remaining";
}

export type DocumentKind = "PDF" | "DWG" | "IMG";

export interface DocumentTile {
  id: string;
  propertyId: string;
  fileName: string;
  kind: DocumentKind;
}

/* ── Quotations ────────────────────────────────────────────────────────── */

export interface QuotationLine {
  label: string;
  amount: number;
}

export interface Quotation {
  id: string;
  propertyId: string;
  designerId: string;
  total: number;
  timelineWeeks: number;
  warrantyYears: number;
  lines: readonly QuotationLine[];
}

/* ── Bids ──────────────────────────────────────────────────────────────── */

export type BidStatus = "Submitted" | "Under Review" | "Shortlisted";

/**
 * A designer's open pipeline — what backs the "Active Bids" stat card and the
 * Bid Management page. Distinct from a Quotation, which is a priced proposal
 * on a project the designer is already engaged on.
 */
export interface Bid {
  id: string;
  designerId: string;
  propertyId: string;
  /** ISO date. */
  submitted: string;
  amount: number;
  timelineWeeks: number;
  status: BidStatus;
  /** Other designers bidding on the same project. */
  competingBids: number;
}

/* ── Onboarding ────────────────────────────────────────────────────────── */

export interface OnboardingStep {
  step: number;
  title: string;
  question: string;
  kind: "single-select" | "multi-select" | "map";
  options: readonly string[];
}

/* ── Landing page ──────────────────────────────────────────────────────── */

export interface CorridorCheckpoint {
  number: number;
  title: string;
  body: string;
}

export interface FaqItem {
  id: string;
  question: string;
  answer: string;
}

export interface CaseStudy {
  propertyId: string;
  homeownerId: string;
  scope: string;
  projectedWeeks: number;
  actualWeeks: number;
  projectedBudget: number;
  actualBudget: number;
  quote: string;
  attribution: string;
}
