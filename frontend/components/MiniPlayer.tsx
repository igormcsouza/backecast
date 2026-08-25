"use client";

import { Pause, Play } from "lucide-react";
import { usePathname } from "next/navigation";
import { nextPlaybackRate, usePlayer } from "@/components/AudioProvider";
import CoverArt from "@/components/CoverArt";
import { formatDuration } from "@/lib/format";

// The sticky bar from the design guide's Home artboard: "browse, search,
// play. Sticky mini-player with the speed control always in reach." Shown
// on the public surface only (not admin) — see the design pages, where the
// admin dashboard/review artboards never carry it.
export default function MiniPlayer() {
  const pathname = usePathname();
  const { episode, isPlaying, currentTime, duration, playbackRate, toggle, seek, setPlaybackRate } =
    usePlayer();

  const isPublicRoute = pathname === "/" || pathname.startsWith("/episode");
  if (!isPublicRoute || !episode) return null;

  const progress = duration > 0 ? currentTime / duration : 0;

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/95 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2.5 sm:gap-4">
        <CoverArt seed={episode.id} className="h-10 w-10 shrink-0" />
        <div className="min-w-0 flex-1 sm:flex-none sm:w-40">
          <p className="truncate text-sm font-medium text-text">{episode.title}</p>
        </div>

        <button
          type="button"
          onClick={toggle}
          aria-label={isPlaying ? "Pause" : "Play"}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-bg transition hover:bg-accent-strong"
        >
          {isPlaying ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
        </button>

        <div className="hidden flex-1 items-center gap-2 sm:flex">
          <span className="w-10 text-right text-xs tabular-nums text-text-muted">
            {formatDuration(currentTime)}
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.001}
            value={Number.isFinite(progress) ? progress : 0}
            onChange={(e) => seek(Number(e.target.value) * duration)}
            className="h-1 flex-1 cursor-pointer accent-[var(--color-accent)]"
          />
          <span className="w-10 text-xs tabular-nums text-text-muted">
            {formatDuration(duration)}
          </span>
        </div>

        <button
          type="button"
          onClick={() => setPlaybackRate(nextPlaybackRate(playbackRate))}
          className="shrink-0 rounded-full border border-border-strong px-2.5 py-1 text-xs font-medium text-text-muted hover:text-text"
        >
          {playbackRate}x
        </button>
      </div>
    </div>
  );
}
