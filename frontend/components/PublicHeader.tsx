"use client";

import { Mic, Search } from "lucide-react";
import Link from "next/link";

// The search input has no backend behind it yet — `GET /episodes` has no
// full-text query param (see backend/app/episodes/router.py). Left visible
// per the design guide but disabled with an explanatory title, rather than
// removed, so the redesign doesn't silently drop a documented affordance;
// tracked to wire up once the backend search endpoint exists.
export default function PublicHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-soft text-accent">
            <Mic size={16} />
          </span>
          <span className="text-base font-semibold tracking-tight text-text">
            Backecast
          </span>
        </Link>

        <div className="relative flex-1 max-w-sm">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            type="search"
            disabled
            placeholder="Search episodes…"
            title="Episode search is coming soon"
            aria-label="Search episodes (coming soon)"
            className="w-full cursor-not-allowed rounded-full border border-border bg-surface py-1.5 pl-9 pr-3 text-sm text-text-muted placeholder:text-text-muted focus:outline-none"
          />
        </div>

        <div className="flex-1" />

        <Link
          href="/admin"
          className="shrink-0 rounded-full border border-border-strong px-3 py-1.5 text-sm font-medium text-text-muted transition hover:border-accent hover:text-text"
        >
          Admin
        </Link>
      </div>
    </header>
  );
}
