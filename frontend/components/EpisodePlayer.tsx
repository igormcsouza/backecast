"use client";

import { Pause, Play, Share2, SkipBack, SkipForward, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { nextPlaybackRate, usePlayer } from "@/components/AudioProvider";
import { formatDuration } from "@/lib/format";
import type { Episode } from "@/lib/types";

const SKIP_SECONDS = 15;

export default function EpisodePlayer({ episode }: { episode: Episode }) {
  const {
    episode: current,
    isPlaying,
    currentTime,
    duration,
    playbackRate,
    volume,
    loadEpisode,
    toggle,
    seek,
    setPlaybackRate,
    setVolume,
  } = usePlayer();
  const [copied, setCopied] = useState(false);

  const isCurrent = current?.id === episode.id;

  // Loading the episode into the shared player as soon as its page opens
  // (not on first play) is what makes the scrubber/duration readable and
  // seekable immediately, matching the design guide's episode artboard —
  // which shows the player already mid-episode, not in an empty state.
  useEffect(() => {
    if (!episode.audio_url) return;
    if (current?.id === episode.id) return;
    loadEpisode({ id: episode.id, title: episode.title, audioUrl: episode.audio_url });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episode.id, episode.audio_url]);

  const time = isCurrent ? currentTime : 0;
  const dur = isCurrent ? duration : 0;
  const rate = isCurrent ? playbackRate : 1;
  const progress = dur > 0 ? time / dur : 0;

  function skip(delta: number) {
    if (!isCurrent) return;
    seek(Math.min(Math.max(time + delta, 0), dur || 0));
  }

  async function handleShare() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be blocked (permissions, insecure context) —
      // there's nothing else useful to fall back to here.
    }
  }

  if (!episode.audio_url) {
    return <p className="text-sm text-text-muted">Audio isn&apos;t available for this episode.</p>;
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-center gap-3">
        <span className="w-10 text-right text-xs tabular-nums text-text-muted">
          {formatDuration(time)}
        </span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.001}
          value={Number.isFinite(progress) ? progress : 0}
          onChange={(e) => seek(Number(e.target.value) * dur)}
          className="h-1 flex-1 cursor-pointer accent-[var(--color-accent)]"
        />
        <span className="w-10 text-xs tabular-nums text-text-muted">{formatDuration(dur)}</span>
      </div>

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => setPlaybackRate(nextPlaybackRate(rate))}
          className="rounded-full border border-border-strong px-2.5 py-1 text-xs font-medium text-text-muted hover:text-text"
        >
          {rate}x speed
        </button>

        <div className="flex items-center gap-3">
          <button
            type="button"
            aria-label="Back 15 seconds"
            onClick={() => skip(-SKIP_SECONDS)}
            className="text-text-muted transition hover:text-text"
          >
            <SkipBack size={18} />
          </button>
          <button
            type="button"
            onClick={toggle}
            aria-label={isCurrent && isPlaying ? "Pause" : "Play"}
            className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-bg transition hover:bg-accent-strong"
          >
            {isCurrent && isPlaying ? (
              <Pause size={18} fill="currentColor" />
            ) : (
              <Play size={18} fill="currentColor" className="ml-0.5" />
            )}
          </button>
          <button
            type="button"
            aria-label="Forward 15 seconds"
            onClick={() => skip(SKIP_SECONDS)}
            className="text-text-muted transition hover:text-text"
          >
            <SkipForward size={18} />
          </button>
        </div>

        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5">
            <Volume2 size={16} className="text-text-muted" />
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={isCurrent ? volume : 1}
              onChange={(e) => setVolume(Number(e.target.value))}
              className="h-1 w-16 cursor-pointer accent-[var(--color-accent)]"
              aria-label="Volume"
            />
          </label>
          <button
            type="button"
            onClick={handleShare}
            aria-label="Copy link to this episode"
            title={copied ? "Copied!" : "Share"}
            className="text-text-muted transition hover:text-text"
          >
            <Share2 size={16} />
          </button>
        </div>
      </div>
      {copied && <p className="text-right text-xs text-accent">Link copied.</p>}
    </div>
  );
}
