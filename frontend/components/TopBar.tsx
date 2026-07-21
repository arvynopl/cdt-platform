"use client";

/**
 * TopBar — the compact application bar: brand mark, primary navigation, and
 * an account menu. Secondary reading (Metodologi, Umpan Balik) lives in the
 * footer, so the bar only carries what people use during a session.
 *
 * Renders the nav only once /api/auth/me resolves, so it never flashes a
 * signed-in state to a signed-out visitor. The theme toggle always shows.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import ThemeToggle from "@/components/ThemeToggle";
import { api, type Me } from "@/lib/api";

const NAV = [
  { href: "/simulasi", label: "Simulasi" },
  { href: "/profil", label: "Profil" },
];

export default function TopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    api
      .get<Me>("/api/auth/me")
      .then((m) => live && setMe(m))
      .catch(() => live && setMe(null));
    return () => {
      live = false;
    };
  }, [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  async function logout() {
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* cookie may already be stale; go to the start page anyway */
    }
    setMe(null);
    setMenuOpen(false);
    router.push("/");
    router.refresh();
  }

  return (
    <header className="sticky top-0 z-40 border-b border-edge bg-card/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4">
        <Link href={me ? "/simulasi" : "/"} className="flex items-center gap-2">
          <span
            aria-hidden
            className="grid h-7 w-7 place-items-center rounded-md bg-brand text-[13px] font-bold text-white"
          >
            C
          </span>
          <span className="text-sm font-bold tracking-tight text-strong">
            CDT
          </span>
        </Link>

        {me && (
          <nav aria-label="Navigasi utama" className="ml-2 flex items-center gap-1">
            {NAV.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors ${
                    active
                      ? "bg-brand-soft text-brand"
                      : "text-bodytext hover:bg-panel hover:text-strong"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        )}

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {me && (
            <div ref={menuRef} className="relative">
              <button
                onClick={() => setMenuOpen((v) => !v)}
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                aria-label="Menu akun"
                className="flex items-center gap-2 rounded-md border border-edge px-2 py-1.5
                           text-sm text-bodytext hover:bg-panel hover:text-strong"
              >
                <span
                  aria-hidden
                  className="grid h-5 w-5 place-items-center rounded-full bg-brand-soft text-[11px] font-bold text-brand"
                >
                  {me.username.slice(0, 1).toUpperCase()}
                </span>
                <span className="hidden max-w-[10rem] truncate sm:inline">
                  {me.username}
                </span>
              </button>
              {menuOpen && (
                <div
                  role="menu"
                  className="absolute right-0 top-full z-50 mt-1 w-52 overflow-hidden rounded-lg
                             border border-edge bg-card py-1 shadow-xl"
                >
                  <Link
                    role="menuitem"
                    href="/akun"
                    onClick={() => setMenuOpen(false)}
                    className="block px-3 py-2 text-sm text-bodytext hover:bg-panel hover:text-strong"
                  >
                    Manajemen Akun
                  </Link>
                  <button
                    role="menuitem"
                    onClick={logout}
                    className="block w-full px-3 py-2 text-left text-sm text-bodytext hover:bg-panel hover:text-strong"
                  >
                    Keluar
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
