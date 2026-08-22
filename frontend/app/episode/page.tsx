"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ApiError, getPublicEpisode } from "@/lib/api";
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
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
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

  if (loading) return <p className="text-sm text-zinc-500">Loading…</p>;

  if (error || !episode) {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-red-600 dark:text-red-400">
          {error ?? "Episode not found."}
        </p>
        <Link href="/" className="text-sm underline">
          Back to episodes
        </Link>
      </div>
    );
  }

  return (
    <article className="flex flex-col gap-6">
      <Link href="/" className="text-sm text-zinc-500 hover:underline">
        &larr; All episodes
      </Link>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{episode.title}</h1>
        <p className="mt-2 whitespace-pre-line text-sm text-zinc-600 dark:text-zinc-400">
          {episode.description}
        </p>
      </div>

      {episode.audio_url && (
        <audio controls src={episode.audio_url} className="w-full" />
      )}

      {episode.resources.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Resources
          </h2>
          <ul className="mt-2 flex flex-col gap-1">
            {episode.resources.map((resource) => (
              <li key={resource.url}>
                <a
                  href={resource.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                >
                  {resource.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
