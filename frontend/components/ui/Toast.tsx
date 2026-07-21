"use client";

/**
 * Toast — transient feedback that replaces the inline red/amber banners the
 * app used to grow inline. Messages are announced politely to screen readers
 * and auto-dismiss; errors stay until dismissed so nothing important vanishes.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Tone = "info" | "success" | "error";
interface Toast {
  id: number;
  tone: Tone;
  message: string;
}

const ToastCtx = createContext<(message: string, tone?: Tone) => void>(() => {});

export function useToast() {
  return useContext(ToastCtx);
}

const TONE_STYLE: Record<Tone, string> = {
  info: "border-edge2 bg-card text-strong",
  success: "border-gain/40 bg-card text-strong",
  error: "border-loss/50 bg-card text-strong",
};

const TONE_DOT: Record<Tone, string> = {
  info: "bg-brand",
  success: "bg-gain",
  error: "bg-loss",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((list) => list.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: Tone = "info") => {
      const id = Date.now() + Math.random();
      setItems((list) => [...list, { id, tone, message }]);
      if (tone !== "error") {
        setTimeout(() => dismiss(id), 4000);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => push, [push]);

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col
                   items-center gap-2 px-4 sm:bottom-auto sm:right-4 sm:top-4 sm:items-end"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={`animate-fade-in pointer-events-auto flex w-full max-w-sm items-start gap-2.5
                        rounded-lg border px-3 py-2.5 shadow-lg ${TONE_STYLE[t.tone]}`}
          >
            <span
              aria-hidden
              className={`mt-1.5 h-1.5 w-1.5 flex-none rounded-full ${TONE_DOT[t.tone]}`}
            />
            <p className="flex-1 text-sm leading-snug">{t.message}</p>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Tutup pemberitahuan"
              className="-mr-1 flex-none rounded px-1 text-muted hover:text-strong"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
