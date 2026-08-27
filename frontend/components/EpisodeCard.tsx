"use client";

import { Pause, Play } from "lucide-react";
import Link from "next/link";
import CoverArt from "@/components/CoverArt";
import { usePlayer } from "@/components/AudioProvider";
import { formatDuration, formatShortDate } from "@/lib/format";
import type { Episode } from "@/lib/types";

function PlayButton({ episode }: { episode: Episode }) {
  const { episode: current, isPlaying, loadEpisode, toggle } = usePlayer();
  const isCurrent = current?.id === episode.id;
  const showPause = isCurrent && isPlaying;

  function handleClick(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!episode.audio_url) return;
    if (isCurrent) {
      toggle();
    } else {
      loadEpisode(
        { id: episode.id, title: episode.title, audioUrl: episode.audio_url },
        true
      );
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={!episode.audio_url}
      aria-label={showPause ? "Pause" : `Play ${episode.title}`}
      className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-bg shadow-lg transition hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
    >
      {showPause ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" className="ml-0.5" />}
    </button>
  );
}

export function EpisodeGridCard({ episode }: { episode: Episode }) {
  const { episode: current, isPlaying } = usePlayer();
  const isCurrent = current?.id === episode.id;
  const href = `/episode?id=${encodeURIComponent(episode.id)}`;

  return (
    <div className="group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-surface transition hover:border-border-strong">
      {/* Stretched-link pattern: the real navigable <a> covers the whole
          card (so the accessible name a test looks up by title still
          resolves), while the play button sits in a positioned layer above
          it so its own click doesn't also trigger the card's navigation. */}
      <Link href={href} className="absolute inset-0 z-0" aria-label={episode.title} />

      <div className="relative aspect-square">
        <CoverArt seed={episode.id} className="absolute inset-0" />
        <div className="absolute bottom-2 right-2 z-10">
          <PlayButton episode={episode} />
        </div>
        {isCurrent && isPlaying && (
          <span className="absolute left-2 top-2 z-10 rounded-full bg-black/50 px-2 py-0.5 text-[11px] font-medium text-white">
            Now playing
          </span>
        )}
      </div>
      <div className="pointer-events-none flex flex-1 flex-col gap-1 p-3">
        <h3 className="line-clamp-1 text-sm font-semibold text-text">{episode.title}</h3>
        <p className="line-clamp-2 text-xs text-text-muted">{episode.description}</p>
        <p className="mt-auto pt-2 text-[11px] text-text-muted">
          {episode.duration > 0 && `${formatDuration(episode.duration)} · `}{formatShortDate(episode.release_date)}
        </p>
      </div>
    </div>
  );
}

export function LatestEpisodeHero({ episode }: { episode: Episode }) {
  const { episode: current, isPlaying, loadEpisode, toggle } = usePlayer();
  const isCurrent = current?.id === episode.id;
  const showPause = isCurrent && isPlaying;

  function handlePlay() {
    if (!episode.audio_url) return;
    if (isCurrent) {
      toggle();
    } else {
      loadEpisode(
        { id: episode.id, title: episode.title, audioUrl: episode.audio_url },
        true
      );
    }
  }

  return (
    <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface p-5 sm:flex-row sm:items-center sm:gap-8">
      <div className="flex-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-accent">
          Latest episode
        </p>
        <Link
          href={`/episode?id=${encodeURIComponent(episode.id)}`}
          className="mt-1 block text-xl font-semibold tracking-tight text-text hover:underline sm:text-2xl"
        >
          {episode.title}
        </Link>
        <p className="mt-2 line-clamp-2 text-sm text-text-muted">{episode.description}</p>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={handlePlay}
            disabled={!episode.audio_url}
            className="flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-medium text-bg transition hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
          >
            {showPause ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
            {showPause ? "Playing" : "Play"}
          </button>
          <span className="text-xs text-text-muted">
            {episode.duration > 0 && `${formatDuration(episode.duration)} · `}{formatShortDate(episode.release_date)}
          </span>
        </div>
      </div>

      <CoverArt seed={episode.id} className="aspect-square w-full shrink-0 sm:w-40" />
    </div>
  );
}
