/**
 * Formatting helpers — docs/02-mock-data-spec.md.
 *
 * Every monetary value in the product goes through formatINR or formatShort.
 * Indian digit grouping and lakh/crore notation throughout; there is no other
 * currency in this product.
 */

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

/** ₹52,00,000 — full figure, Indian digit grouping. */
export const formatINR = (n: number): string => inr.format(n);

/** ₹52L / ₹1.15Cr — compact figure for stat cards and chips. */
export const formatShort = (n: number): string =>
  n >= 1_00_00_000
    ? `₹${(n / 1_00_00_000).toFixed(2)}Cr`
    : n >= 1_00_000
      ? `₹${(n / 1_00_000).toFixed(0)}L`
      : `₹${n.toLocaleString("en-IN")}`;

export type DateStyle = "short" | "long" | "monthYear";

const DATE_OPTIONS: Record<DateStyle, Intl.DateTimeFormatOptions> = {
  /** 14 Jun 2026 */
  short: { day: "numeric", month: "short", year: "numeric" },
  /** 14 June 2026 */
  long: { day: "numeric", month: "long", year: "numeric" },
  /** Jun 2026 */
  monthYear: { month: "short", year: "numeric" },
};

/**
 * Formats an ISO date string (or Date) in the Indian convention.
 * Always render alongside the `tabular` class so columns of dates align.
 */
export const formatDate = (value: string | Date, style: DateStyle = "short"): string => {
  const date = typeof value === "string" ? new Date(value) : value;
  return new Intl.DateTimeFormat("en-IN", DATE_OPTIONS[style]).format(date);
};

/**
 * percent(68)                  → "68%"
 * percent(12_00_000, { of: 52_00_000 })  → "23%"
 * percent(2.7, { digits: 1 })  → "2.7%"
 *
 * Pass `of` when the value is a part of a whole; omit it when the value is
 * already a percentage.
 */
export const percent = (
  value: number,
  options: { of?: number; digits?: number } = {},
): string => {
  const { of, digits = 0 } = options;
  const ratio = of === undefined ? value : of === 0 ? 0 : (value / of) * 100;
  return `${ratio.toFixed(digits)}%`;
};
