"use client";

/**
 * HelpMenu — the floating help button (bottom-right) that opens a small menu
 * to replay the on-screen coach tour or the practice rounds. Purely a UI
 * affordance; the parent owns what "replay" does.
 */

export default function HelpMenu(props: {
  open: boolean;
  onToggle: () => void;
  onReplayTour: () => void;
  onReplayPractice: () => void;
}) {
  return (
    <div className="fixed bottom-20 right-4 z-40 flex flex-col items-end gap-2">
      {props.open && (
        <div className="w-56 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
          <button
            onClick={props.onReplayTour}
            className="block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-brand-soft"
          >
            Putar ulang panduan halaman
            <span className="block text-xs text-slate-500">
              Tur singkat mengenal setiap bagian layar
            </span>
          </button>
          <button
            onClick={props.onReplayPractice}
            className="block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-brand-soft"
          >
            Ulangi mode latihan
            <span className="block text-xs text-slate-500">
              Tiga putaran percobaan; sesi Anda tetap aman
            </span>
          </button>
        </div>
      )}
      <button
        onClick={props.onToggle}
        aria-label="Bantuan"
        aria-expanded={props.open}
        className="h-10 w-10 rounded-full border border-slate-300 bg-white
                   text-lg font-semibold text-brand shadow-md hover:bg-brand-soft"
      >
        ?
      </button>
    </div>
  );
}
