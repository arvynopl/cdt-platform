/**
 * Panel — the standard surface. `title` renders a compact header row with an
 * optional right-hand slot for actions, which is what keeps a dense tool
 * layout readable without every block shouting at the same volume.
 */

import type { ReactNode } from "react";

export default function Panel({
  title,
  action,
  subtitle,
  children,
  className = "",
  padded = true,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section
      className={`rounded-xl border border-edge bg-card ${className}`}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-edge px-4 py-2.5">
          <div className="min-w-0">
            {title && (
              <h3 className="truncate text-sm font-semibold text-strong">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="mt-0.5 text-xs text-muted">{subtitle}</p>
            )}
          </div>
          {action && <div className="flex-none">{action}</div>}
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}
