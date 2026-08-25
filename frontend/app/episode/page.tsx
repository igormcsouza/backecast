"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import CoverArt from "@/components/CoverArt";
import EpisodePlayer from "@/components/EpisodePlayer";
import PublicHeader from "@/components/PublicHeader";
import ResourceList from "@/components/ResourceList";
import { ApiError, getPublicEpisode, listPublicEpisodes } from "@/lib/api";
import { formatDuration, formatLongDate } from "@/lib/format";
import type { Episode } from "@/lib/types";

// `useSearchParams()` requires a <Suspense> boundary even in a fully
// client-rendered, statically-exported page — Next.js enforces this so a
// static shell can still be pre-rendered without knowing query params
// ahead of time. There are no real "server" params to wait on here (this
// route has no matching Next.js dynamic segment on purpose, see
// next.config.ts's docstring / SESSIONS.md: `output: 'export'` can't
// generateStaticParams for episode ids it doesn't know at build time, so
// the id travels as `?id=...` instead of a route segment).
export default function EpisodePage() {
  return (
    <Suspense fallback={<p className="text-sm text-text-muted">Loading…</p>}>
      <EpisodeDetail />
    </Suspense>
  );
}

function EpisodeDetail() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");

  const [episode, setEpisode] = useState<Episode | null>(null);
  // Initial state already reflects the "no id" case so the effect never
  // needs to call setState synchronously in that branch (see
  // eslint-plugin-react-hooks's react-hooks/set-state-in-effect rule).
  const [loading, setLoading] = useState(!!id);
  const [error, setError] = useState<string | null>(
    id ? null : "No episode id given."
  );

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getPublicEpisode(id)
      .then((data) => {
        if (!cancelled) {
          setEpisode(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError && err.status === 404
            ? "Episode not found."
            : "Failed to load episode."
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <>
      <PublicHeader />
      <div className="mx-auto max-w-3xl px-4 py-8 pb-28">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-text-muted hover:text-text"
        >
          <ChevronLeft size={16} /> All episodes
        </Link>

        {loading && <p className="mt-6 text-sm text-text-muted">Loading…</p>}

        {!loading && (error || !episode) && (
          <p className="mt-6 text-sm text-danger">{error ?? "Episode not found."}</p>
        )}

        {!loading && episode && <EpisodeBody episode={episode} />}
      </div>
    </>
  );
}

function EpisodeBody({ episode }: { episode: Episode }) {
  return (
    <article className="mt-6 flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row">
        <CoverArt seed={episode.id} className="aspect-square w-28 shrink-0" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text sm:text-2xl">
            {episode.title}
          </h1>
          <p className="mt-1 text-xs text-text-muted">
            {formatDuration(episode.duration)} · Released {formatLongDate(episode.release_date)}
          </p>
          <p className="mt-3 whitespace-pre-line text-sm text-text-muted">
            {episode.description}
          </p>
        </div>
      </div>

      <EpisodePlayer episode={episode} />

      <ResourceList resources={episode.resources} />

      <MoreEpisodes excludeId={episode.id} />
    </article>
  );
}

function MoreEpisodes({ excludeId }: { excludeId: string }) {
  const [episodes, setEpisodes] = useState<Episode[]>([]);

  useEffect(() => {
    let cancelled = false;
    listPublicEpisodes(6)
      .then((page) => {
        if (!cancelled) setEpisodes(page.items.filter((e) => e.id !== excludeId).slice(0, 3));
      })
      .catch(() => {
        // The main episode already loaded fine — a failed "more episodes"
        // fetch just means an empty section, not a page-level error.
      });
    return () => {
      cancelled = true;
    };
  }, [excludeId]);

  if (episodes.length === 0) return null;

  return (
    <div>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
        More episodes
      </h2>
      <ul className="mt-2 flex flex-col divide-y divide-border rounded-xl border border-border">
        {episodes.map((episode) => (
          <li key={episode.id}>
            <Link
              href={`/episode?id=${encodeURIComponent(episode.id)}`}
              className="flex items-center gap-3 px-3 py-2.5 transition hover:bg-surface-2"
            >
              <CoverArt seed={episode.id} className="h-10 w-10 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-text">
                  {episode.title}
                </span>
                <span className="block text-xs text-text-muted">
                  {formatDuration(episode.duration)}
                </span>
              </span>
              <ChevronLeft size={16} className="rotate-180 shrink-0 text-text-muted" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
