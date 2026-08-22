"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
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

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Episodes</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Published episodes, newest first.
        </p>
      </div>

      {loading && <p className="text-sm text-zinc-500">Loading episodes…</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {!loading && !error && episodes.length === 0 && !cursor && (
        <p className="text-sm text-zinc-500">
          No episodes published yet — check back soon.
        </p>
      )}

      <ul className="flex flex-col gap-6">
        {episodes.map((episode) => (
          <li
            key={episode.id}
            className="rounded-lg border border-zinc-200 p-5 dark:border-zinc-800"
          >
            <Link
              href={`/episode?id=${encodeURIComponent(episode.id)}`}
              className="text-lg font-medium hover:underline"
            >
              {episode.title}
            </Link>
            <p className="mt-2 line-clamp-3 text-sm text-zinc-600 dark:text-zinc-400">
              {episode.description}
            </p>
            {episode.audio_url && (
              <audio
                controls
                preload="none"
                src={episode.audio_url}
                className="mt-4 w-full"
              />
            )}
          </li>
        ))}
      </ul>

      {cursor && (
        <button
          type="button"
          onClick={loadMore}
          disabled={loadingMore}
          className="self-center rounded-full border border-zinc-300 px-5 py-2 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
