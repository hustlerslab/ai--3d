import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * The button variants from docs/03-design-system.md §8.
 *
 * Primary is a gold fill with **dark** text — white on gold is 2.4:1 and
 * unreadable. Every variant is pill-shaped, matching the nav and the status
 * pills, so the whole product speaks one shape language.
 *
 * Interaction states are the part the spec leaves open: 150ms ease-out on
 * colour, a 1px lift on hover for the two filled variants, and the lift
 * removed on :active so a press reads as a press. Focus is a visible ring in
 * every case, never a colour change alone.
 */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";

const VARIANT: Record<ButtonVariant, string> = {
  primary: cn(
    "bg-gold text-ink shadow-sm",
    "hover:-translate-y-px hover:bg-gold-light hover:shadow-md",
    "active:translate-y-0 active:shadow-sm",
  ),
  secondary: cn(
    "border border-tan bg-transparent text-ink-soft",
    "hover:-translate-y-px hover:border-ink-muted hover:bg-sand/40",
    "active:translate-y-0",
  ),
  ghost: "bg-transparent text-ink-muted hover:bg-sand/50 hover:text-ink-soft",
  destructive: cn(
    "border border-danger bg-transparent text-danger",
    "hover:bg-danger/10",
  ),
};

const SIZE = {
  sm: "px-3.5 py-1.5 text-xs",
  md: "px-5 py-2.5 body-sm",
} as const;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: keyof typeof SIZE;
}

export function Button({
  variant = "secondary",
  size = "md",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "pressable inline-flex items-center justify-center gap-2 rounded-pill font-medium whitespace-nowrap",
        "transition-all duration-150 ease-out",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-surface-raised focus-visible:outline-none",
        // Disabled is a sand fill with muted text — a state, not a ghost.
        "disabled:pointer-events-none disabled:border-transparent disabled:bg-sand disabled:text-ink-muted/50 disabled:shadow-none",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...props}
    />
  );
}
