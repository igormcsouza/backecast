"use client";

import { useEffect, useState } from "react";
import PublicHeader from "@/components/PublicHeader";
import SortChips from "@/components/SortChips";
import { EpisodeGridCard, LatestEpisodeHero } from "@/components/EpisodeCard";
import { ApiError, listPublicEpisodes } from "@/lib/api";
import type { Episode } from "@/lib/types";

const PAGE_SIZE = 10;

export default function HomePage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPublicEpisodes(PAGE_SIZE)
      .then((page) => {
        if (cancelled) return;
        setEpisodes(page.items);
        setCursor(page.cursor);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load episodes.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await listPublicEpisodes(PAGE_SIZE, cursor);
      setEpisodes((prev) => [...prev, ...page.items]);
      setCursor(page.cursor);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load more episodes.");
    } finally {
      setLoadingMore(false);
    }
  }

  // The latest episode gets its own hero panel (per the design guide); the
  // grid below shows the rest, so the same episode never appears twice on
  // the page.
  const [latest, ...rest] = episodes;

  return (
    <>
      <PublicHeader />
      <div className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-8 pb-28">
        {loading && <p className="text-sm text-text-muted">Loading episodes…</p>}
        {error && <p className="text-sm text-danger">{error}</p>}

        {!loading && !error && episodes.length === 0 && !cursor && (
          <p className="text-sm text-text-muted">
            No episodes published yet — check back soon.
          </p>
        )}

        {latest && <LatestEpisodeHero episode={latest} />}

        {episodes.length > 0 && (
          <section className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">
                All episodes
              </h2>
              <SortChips />
            </div>

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {rest.map((episode) => (
                <EpisodeGridCard key={episode.id} episode={episode} />
              ))}
            </div>
          </section>
        )}

        {cursor && (
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="self-center rounded-full border border-border-strong px-5 py-2 text-sm font-medium text-text transition hover:border-accent disabled:opacity-50"
          >
            {loadingMore ? "Loading…" : "Load more episodes"}
          </button>
        )}
      </div>
    </>
  );
}
