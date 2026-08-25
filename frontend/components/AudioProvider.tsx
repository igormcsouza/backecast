"use client";

// One <audio> element for the whole app, owned by this provider and
// mounted once in RootLayout — every play button (episode cards, the
// episode page's inline player, the admin review preview, the sticky
// mini-player) is just a different view onto the same context/element.
// That's what makes the sticky mini-player possible at all in a static,
// multi-page-navigated app: the element itself never unmounts on
// client-side navigation because RootLayout doesn't.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export interface PlayableEpisode {
  id: string;
  title: string;
  audioUrl: string;
}

interface PlayerState {
  episode: PlayableEpisode | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  playbackRate: number;
  volume: number;
}

interface PlayerContextValue extends PlayerState {
  loadEpisode: (episode: PlayableEpisode, autoplay?: boolean) => void;
  toggle: () => void;
  play: () => void;
  pause: () => void;
  seek: (time: number) => void;
  setPlaybackRate: (rate: number) => void;
  setVolume: (volume: number) => void;
}

const PlayerContext = createContext<PlayerContextValue | null>(null);

const RATE_STEPS = [1, 1.25, 1.5, 2, 0.75];

export function AudioProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [state, setState] = useState<PlayerState>({
    episode: null,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    playbackRate: 1,
    volume: 1,
  });

  const loadEpisode = useCallback((episode: PlayableEpisode, autoplay = false) => {
    setState((prev) => ({
      ...prev,
      episode,
      currentTime: 0,
      duration: 0,
      isPlaying: false,
    }));
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.src !== episode.audioUrl) {
      audio.src = episode.audioUrl;
    }
    if (autoplay) {
      audio.play().catch(() => {
        // Autoplay can be blocked by the browser — the UI just falls back
        // to showing a paused state, which is already what `isPlaying`
        // defaults to above.
      });
    }
  }, []);

  const play = useCallback(() => {
    audioRef.current?.play().catch(() => {});
  }, []);

  const pause = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }, []);

  const seek = useCallback((time: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = time;
    setState((prev) => ({ ...prev, currentTime: time }));
  }, []);

  const setPlaybackRate = useCallback((rate: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = rate;
    setState((prev) => ({ ...prev, playbackRate: rate }));
  }, []);

  const setVolume = useCallback((volume: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = volume;
    setState((prev) => ({ ...prev, volume }));
  }, []);

  const value = useMemo<PlayerContextValue>(
    () => ({
      ...state,
      loadEpisode,
      toggle,
      play,
      pause,
      seek,
      setPlaybackRate,
      setVolume,
    }),
    [state, loadEpisode, toggle, play, pause, seek, setPlaybackRate, setVolume]
  );

  return (
    <PlayerContext.Provider value={value}>
      {children}
      <audio
        ref={audioRef}
        className="native-audio"
        preload="metadata"
        // Chromium's UA stylesheet forces `display: none !important` on
        // `audio:not([controls])` — no author CSS (not even `!important`)
        // can win against an `!important` UA rule, so this element must
        // keep `controls` to stay a real, non-`display:none` box at all.
        // The `.native-audio` class then clips that native chrome out of
        // view visually (see globals.css) — our own transport UI is what
        // people actually see and use.
        controls
        onPlay={() => setState((prev) => ({ ...prev, isPlaying: true }))}
        onPause={() => setState((prev) => ({ ...prev, isPlaying: false }))}
        onTimeUpdate={(e) => {
          // React nulls out `currentTarget` on the synthetic event once
          // the handler that received it returns, so it has to be read
          // eagerly here — reading it lazily inside the setState updater
          // below (which React can invoke after that point) throws.
          const currentTime = e.currentTarget.currentTime;
          setState((prev) => ({ ...prev, currentTime }));
        }}
        onLoadedMetadata={(e) => {
          const duration = e.currentTarget.duration;
          setState((prev) => ({ ...prev, duration }));
        }}
        onEnded={() => setState((prev) => ({ ...prev, isPlaying: false }))}
      />
    </PlayerContext.Provider>
  );
}

export function usePlayer(): PlayerContextValue {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("usePlayer must be used within AudioProvider");
  return ctx;
}

export function nextPlaybackRate(current: number): number {
  const index = RATE_STEPS.indexOf(current);
  return RATE_STEPS[(index + 1) % RATE_STEPS.length];
}
