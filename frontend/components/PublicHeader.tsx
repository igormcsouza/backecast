"use client";

import { Mic, Search } from "lucide-react";
import Link from "next/link";

interface PublicHeaderProps {
  // Optional: only the home page (app/page.tsx) wires these up to actually
  // filter the list. Pages that render PublicHeader without them (e.g.
  // app/episode/page.tsx) get the pre-#6 disabled/"coming soon" input back,
  // rather than a search box that silently does nothing when typed into.
  searchValue?: string;
  onSearchChange?: (value: string) => void;
}

export default function PublicHeader({
  searchValue = "",
  onSearchChange,
}: PublicHeaderProps) {
  const searchEnabled = onSearchChange !== undefined;
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
            value={searchValue}
            onChange={
              searchEnabled
                ? (event) => onSearchChange!(event.target.value)
                : undefined
            }
            disabled={!searchEnabled}
            placeholder="Search episodes…"
            title={searchEnabled ? undefined : "Episode search is coming soon"}
            aria-label={
              searchEnabled ? "Search episodes" : "Search episodes (coming soon)"
            }
            className={
              searchEnabled
                ? "w-full rounded-full border border-border bg-surface py-1.5 pl-9 pr-3 text-sm text-text placeholder:text-text-muted focus:outline-none focus:border-accent"
                : "w-full cursor-not-allowed rounded-full border border-border bg-surface py-1.5 pl-9 pr-3 text-sm text-text-muted placeholder:text-text-muted focus:outline-none"
            }
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
