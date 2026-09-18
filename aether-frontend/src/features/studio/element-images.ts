import type { ElementImageSetDto } from "./types";

/**
 * Element-first, stage 1: the pieces the room will hold, each with its
 * canonical picture, shown BEFORE any room is painted.
 *
 * Joins backend records by id. Counts come from `definitions`, pictures from
 * `images`; nothing is inferred here. A piece with no picture is shown as
 * such, with the backend's reason, never hidden.
 */

export type PictureState = "painted" | "failed" | "pending";

export interface ElementCard {
  element_id: string;
  label: string;
  room_id: string;
  semantic_type: string;
  material: string;
  instance_count: number;
  /** "photo" when a crop of the client's own piece conditioned the render. */
  source: "photo" | "brief";
  picture: PictureState;
  image_url: string;
  reference_url: string;
  seed: number;
  error: string;
}

export interface ElementImagesView {
  cards: ElementCard[];
  canonical_count: number;
  instance_count: number;
  painted: number;
  failed: number;
  pending: number;
  warnings: string[];
}

export function humanType(semanticType: string): string {
  return semanticType.split("_").filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
}

export function buildElementImages(data: ElementImageSetDto): ElementImagesView {
  const images = new Map((data.images ?? []).map((im) => [im.element_id, im] as const));
  const cards: ElementCard[] = (data.definitions ?? []).map((d) => {
    const im = images.get(d.element_id);
    const picture: PictureState = !im ? "pending" : im.error ? "failed" : "painted";
    return {
      element_id: d.element_id,
      label: d.canonical_name || humanType(d.semantic_type),
      room_id: d.room_id,
      semantic_type: d.semantic_type,
      material: d.material,
      instance_count: d.instance_count,
      source: im?.reference_ref ? "photo" : "brief",
      picture,
      image_url: im?.image_url ?? "",
      reference_url: im?.reference_url ?? "",
      seed: im?.seed ?? 0,
      error: im?.error ?? "",
    };
  });
  return {
    cards,
    canonical_count: cards.length,
    instance_count: (data.instances ?? []).length,
    painted: cards.filter((c) => c.picture === "painted").length,
    failed: cards.filter((c) => c.picture === "failed").length,
    pending: cards.filter((c) => c.picture === "pending").length,
    warnings: data.warnings ?? [],
  };
}
