"use client";

/**
 * Button — the single source of truth for actions.
 *
 * Variants map to intent, not colour: `primary` is the brand violet,
 * `danger` is destructive. Money colours (gain/loss) are deliberately NOT
 * available here, so green and red only ever mean money in this app.
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-brand text-white hover:brightness-110 active:brightness-95 disabled:opacity-45",
  secondary:
    "border border-edge2 text-strong hover:bg-panel disabled:opacity-45",
  ghost: "text-bodytext hover:bg-panel hover:text-strong disabled:opacity-45",
  danger:
    "bg-loss text-white hover:brightness-110 active:brightness-95 disabled:opacity-45",
};

const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-10 px-4 text-sm",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
  children: ReactNode;
}

export default function Button({
  variant = "primary",
  size = "md",
  block = false,
  className = "",
  children,
  ...rest
}: Props) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-semibold
                  transition-[filter,background-color,color] disabled:cursor-not-allowed
                  ${VARIANT[variant]} ${SIZE[size]} ${block ? "w-full" : ""} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
