"use client";

import { Mic } from "lucide-react";
import Link from "next/link";

export default function AdminHeader({ onSignOut }: { onSignOut?: () => void }) {
  return (
    <header className="border-b border-border bg-bg">
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3">
        <Link href="/admin" className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-soft text-accent">
            <Mic size={16} />
          </span>
          <span className="text-base font-semibold tracking-tight text-text">
            Backecast
          </span>
          <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Admin
          </span>
        </Link>
        <div className="flex-1" />
        {onSignOut && (
          <button
            type="button"
            onClick={onSignOut}
            className="text-sm text-text-muted transition hover:text-text"
          >
            Sign out
          </button>
        )}
      </div>
    </header>
  );
}
