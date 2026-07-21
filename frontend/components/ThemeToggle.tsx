"use client";

/**
 * ThemeToggle — flips the `.dark` class on <html> and remembers the choice in
 * localStorage. The initial class is set by an inline script in the layout
 * (before paint) to avoid a flash, so this only reflects and updates state.
 */

import { useEffect, useState } from "react";

const KEY = "cdt_theme";

export default function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem(KEY, next ? "dark" : "light");
    } catch {
      /* storage unavailable — the toggle still works for this session */
    }
  }

  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
      title={dark ? "Mode terang" : "Mode gelap"}
      className="flex h-8 w-8 items-center justify-center rounded-lg border border-edge
                 text-muted hover:bg-panel"
    >
      {dark ? (
        // sun
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
          <circle cx="12" cy="12" r="4" fill="currentColor" />
          <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
          </g>
        </svg>
      ) : (
        // moon
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"
            fill="currentColor"
          />
        </svg>
      )}
    </button>
  );
}
