"use client";

/**
 * Header identity cluster: shows the signed-in username and a logout action.
 * Renders nothing until /api/auth/me resolves, so the header never flashes
 * a wrong state.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, type Me } from "@/lib/api";

const NAV = [
  { href: "/simulasi", label: "Simulasi" },
  { href: "/profil", label: "Profil Saya" },
  { href: "/metodologi", label: "Metodologi" },
  { href: "/umpan-balik", label: "Umpan Balik" },
  { href: "/akun", label: "Akun" },
];

export default function HeaderBar() {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);

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

  if (!me) return null;

  async function logout() {
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* cookie may already be stale; proceed to the start page anyway */
    }
    setMe(null);
    router.push("/");
    router.refresh();
  }

  return (
    <div className="flex w-full flex-col gap-2 sm:w-auto sm:items-end">
      <div className="flex items-center gap-3 text-sm">
        <span className="text-slate-500">
          Masuk sebagai <b className="text-slate-800">{me.username}</b>
        </span>
        <button
          onClick={logout}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs
                     font-medium text-slate-600 hover:bg-slate-100"
        >
          Keluar
        </button>
      </div>
      <nav aria-label="Navigasi utama" className="flex gap-1">
        {NAV.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-brand text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
