/**
 * Badge — a compact status pill. Severity uses the neutral/warn scale rather
 * than green-red, so bias severity is never confused with money direction.
 */

import type { ReactNode } from "react";

type Tone = "neutral" | "brand" | "warn" | "gain" | "loss";

const TONE: Record<Tone, string> = {
  neutral: "bg-panel text-bodytext",
  brand: "bg-brand-soft text-brand",
  warn: "bg-warn/15 text-warn",
  gain: "bg-gain/15 text-gain",
  loss: "bg-loss/15 text-loss",
};

export default function Badge({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px]
                  font-medium leading-4 ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}
