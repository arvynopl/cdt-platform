/**
 * Skeleton — content-shaped loading placeholders (shimmer defined in
 * globals.css, reduced-motion safe). `Skeleton` is a single bar; the named
 * helpers assemble the common page shapes so loaders mirror the real layout
 * instead of a bare spinner.
 */

export function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden />;
}

/** A titled card block with a few text lines — the app's default surface. */
export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <Skeleton className="h-4 w-40" />
      <div className="mt-3 space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton
            key={i}
            className={`h-3 ${i === lines - 1 ? "w-2/3" : "w-full"}`}
          />
        ))}
      </div>
    </div>
  );
}

/** A chart-shaped block: heading + a tall area. */
export function SkeletonChart({ height = 300 }: { height?: number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <Skeleton className="mb-3 h-4 w-32" />
      <Skeleton className="w-full" style={{ height }} />
    </div>
  );
}
