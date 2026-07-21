"use client";

/**
 * CoachTour — lightweight spotlight tour without external dependencies.
 *
 * Each step targets an element by its `data-tour` attribute. The target gets
 * a highlight ring (huge box-shadow cutout) and a tooltip card positioned
 * near it. Steps may declare `before` side effects (e.g. expanding a stock
 * card) which the host page provides via `onBeforeStep`.
 */

import { useCallback, useEffect, useLayoutEffect, useState } from "react";

export interface TourStep {
  target: string; // value of data-tour on the target element
  title: string;
  body: string;
}

interface Props {
  steps: TourStep[];
  onBeforeStep?: (target: string) => void;
  onFinish: () => void;
  onSkip: () => void;
}

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export default function CoachTour({ steps, onBeforeStep, onFinish, onSkip }: Props) {
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const step = steps[idx];

  const measure = useCallback(() => {
    const el = document.querySelector<HTMLElement>(
      `[data-tour="${step.target}"]`,
    );
    if (!el) {
      setRect(null);
      return;
    }
    el.scrollIntoView({ block: "center", behavior: "instant" as ScrollBehavior });
    const r = el.getBoundingClientRect();
    setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
  }, [step.target]);

  useLayoutEffect(() => {
    onBeforeStep?.(step.target);
    // Allow the host to expand/render the target before measuring.
    const t = setTimeout(measure, 120);
    return () => clearTimeout(t);
  }, [step.target, measure, onBeforeStep]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure]);

  if (!step) return null;

  const last = idx === steps.length - 1;
  const below =
    rect !== null && rect.top + rect.height + 190 < window.innerHeight;
  const cardTop = rect
    ? below
      ? rect.top + rect.height + 12
      : Math.max(rect.top - 196, 12)
    : window.innerHeight / 2 - 90;

  return (
    <div className="fixed inset-0 z-[60]">
      {/* Spotlight: darken everything except the target */}
      {rect ? (
        <div
          className="absolute rounded-xl transition-all duration-200"
          style={{
            top: rect.top - 6,
            left: rect.left - 6,
            width: rect.width + 12,
            height: rect.height + 12,
            boxShadow: "0 0 0 9999px rgba(15, 23, 42, 0.55)",
            border: "2px solid #2563EB",
            pointerEvents: "none",
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-slate-900/55" />
      )}

      {/* Tooltip card */}
      <div
        className="absolute left-1/2 w-[calc(100%-2rem)] max-w-sm -translate-x-1/2
                   rounded-xl bg-card p-5 shadow-2xl"
        style={{ top: cardTop }}
        role="dialog"
        aria-label={step.title}
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-brand">
          Panduan {idx + 1} dari {steps.length}
        </p>
        <h3 className="mt-1 text-sm font-semibold">{step.title}</h3>
        <p className="mt-1.5 text-sm leading-relaxed text-bodytext">
          {step.body}
        </p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button
            onClick={onSkip}
            className="text-xs text-muted hover:text-strong"
          >
            Lewati panduan
          </button>
          <div className="flex gap-2">
            {idx > 0 && (
              <button
                onClick={() => setIdx(idx - 1)}
                className="rounded-lg border border-edge2 px-3.5 py-2 text-sm"
              >
                Kembali
              </button>
            )}
            <button
              onClick={() => (last ? onFinish() : setIdx(idx + 1))}
              className="rounded-lg bg-brand px-3.5 py-2 text-sm font-semibold text-white"
            >
              {last ? "Selesai" : "Lanjut"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
