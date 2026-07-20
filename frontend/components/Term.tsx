"use client";

/**
 * <Term id="disposition">Efek Disposisi</Term>
 *
 * Renders inline text followed by a small “ⓘ” button that toggles an
 * accessible popover with the plain-language definition from lib/glossary.
 * Keyboard-friendly: the trigger is a real <button> (Enter/Space), Escape
 * closes it, and a click outside dismisses it. Falls back to rendering just
 * the children if the id is unknown, so a typo never throws.
 */

import { useEffect, useId, useRef, useState } from "react";
import { GLOSSARY } from "@/lib/glossary";

export default function Term({
  id,
  children,
}: {
  id: keyof typeof GLOSSARY | string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const panelId = useId();
  const entry = GLOSSARY[id];

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  if (!entry) return <>{children}</>;

  return (
    <span ref={wrapRef} className="relative inline-flex items-center gap-1">
      {children}
      <button
        type="button"
        aria-label={`Penjelasan: ${entry.label}`}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full
                   border border-slate-300 text-[10px] font-semibold leading-none
                   text-slate-500 hover:bg-slate-100 focus:outline-none
                   focus:ring-2 focus:ring-brand"
      >
        i
      </button>
      {open && (
        <span
          id={panelId}
          role="tooltip"
          className="absolute left-0 top-6 z-10 w-64 rounded-lg border border-slate-200
                     bg-white p-3 text-left text-xs font-normal leading-relaxed
                     text-slate-600 shadow-lg"
        >
          <span className="mb-0.5 block font-semibold text-slate-800">
            {entry.label}
          </span>
          {entry.short}
        </span>
      )}
    </span>
  );
}
