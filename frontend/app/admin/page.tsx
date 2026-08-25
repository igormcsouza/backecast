"use client";

import { Clock, FileAudio, Mic, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import AdminHeader from "@/components/AdminHeader";
import StatTile from "@/components/StatTile";
import {
  ApiError,
  createEpisode,
  getAdminEpisode,
  listAdminEpisodes,
  uploadToPresignedPost,
} from "@/lib/api";
import { computeAdminStats } from "@/lib/adminStats";
import { clearStoredToken, getStoredToken, setStoredToken, login } from "@/lib/auth";
import { formatDurationHours, formatRelativeTime } from "@/lib/format";
import type { Episode, EpisodeStatus } from "@/lib/types";

const ALLOWED_CONTENT_TYPES: Record<string, string> = {
  mp3: "audio/mpeg",
  m4a: "audio/x-m4a",
  mp4: "audio/mp4",
};

const POLL_INTERVAL_MS = 2000;
// A generous ceiling, not a tight SLA: real transcription + metadata
// generation can take a couple of minutes for a full-length episode. This
// just stops the browser from polling forever if something is stuck.
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

const IN_FLIGHT_STATUSES: EpisodeStatus[] = [
  "uploading",
  "processing",
  "transcribing",
  "generating",
];

function guessContentType(filename: string): string | null {
  const extension = filename.split(".").pop()?.toLowerCase();
  return extension ? (ALLOWED_CONTENT_TYPES[extension] ?? null) : null;
}

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // Lazy initializer (runs once, at first render, not inside the effect
  // below) — true only when there's a stored token that still needs
  // validating, so the effect never has to flip it synchronously for the
  // "nothing stored" case (see react-hooks/set-state-in-effect).
  const [checkingToken, setCheckingToken] = useState(() => !!getStoredToken());
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    const stored = getStoredToken();
    if (!stored) return;
    listAdminEpisodes(stored)
      .then(() => setToken(stored))
      .catch(() => {
        clearStoredToken();
        setLoginError("Your session expired — please sign in again.");
      })
      .finally(() => setCheckingToken(false));
  }, []);

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault();
    setLoginError(null);
    try {
      const accessToken = await login(username, password);
      setStoredToken(accessToken);
      setToken(accessToken);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Sign in failed.");
    }
  }

  function handleLogout() {
    clearStoredToken();
    setToken(null);
    setUsername("");
    setPassword("");
  }

  if (checkingToken) {
    return <p className="p-8 text-sm text-text-muted">Checking admin session…</p>;
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm rounded-2xl border border-border bg-surface p-6">
          <div className="flex flex-col items-center gap-2 text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent-soft text-accent">
              <Mic size={20} />
            </span>
            <h1 className="text-lg font-semibold text-text">Admin sign in</h1>
            <p className="text-xs text-text-muted">
              Upload, review, and publish Backecast episodes.
            </p>
          </div>

          <form onSubmit={handleLogin} className="mt-5 flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-text-muted">Username</span>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Username"
                autoComplete="username"
                className="rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                autoFocus
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-text-muted">Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                autoComplete="current-password"
                className="rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
              />
            </label>
            <button
              type="submit"
              className="mt-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-bg transition hover:bg-accent-strong"
            >
              Sign in
            </button>
          </form>
          {loginError && <p className="mt-3 text-sm text-danger">{loginError}</p>}
          <p className="mt-4 text-center text-[11px] text-text-muted">
            Single admin account — managed in Cognito.
          </p>
        </div>
      </div>
    );
  }

  return <AdminDashboard token={token} onLogout={handleLogout} />;
}

function AdminDashboard({
  token,
  onLogout,
}: {
  token: string;
  onLogout: () => void;
}) {
  const [allEpisodes, setAllEpisodes] = useState<Episode[]>([]);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [activeUploadId, setActiveUploadId] = useState<string | null>(null);
  const [tab, setTab] = useState<"review" | "published">("review");

  const refreshEpisodes = () => {
    listAdminEpisodes(token)
      .then((items) => {
        setAllEpisodes(items);
        setQueueError(null);
      })
      .catch(() => setQueueError("Failed to load episodes."));
  };

  useEffect(refreshEpisodes, [token]);

  const stats = useMemo(() => computeAdminStats(allEpisodes), [allEpisodes]);
  const reviewQueue = allEpisodes.filter((e) => e.status === "review");
  const published = allEpisodes.filter((e) => e.status === "published");
  const inFlight = allEpisodes.filter((e) => IN_FLIGHT_STATUSES.includes(e.status));
  const visible = tab === "review" ? [...inFlight, ...reviewQueue] : published;

  return (
    <div className="min-h-screen">
      <AdminHeader onSignOut={onLogout} />
      <div className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text">Admin overview</h1>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile icon={Mic} label="Published episodes" value={stats.publishedCount} />
          <StatTile
            icon={Clock}
            label="Hours of content"
            value={formatDurationHours(stats.totalContentSeconds)}
          />
          <StatTile icon={FileAudio} label="Waiting on review" value={stats.reviewCount} />
          <StatTile icon={Upload} label="Uploaded this month" value={stats.uploadedThisMonth} />
        </div>

        <UploadForm token={token} onUploadStarted={setActiveUploadId} />

        {activeUploadId && (
          <UploadStatus
            token={token}
            episodeId={activeUploadId}
            onDone={() => {
              setActiveUploadId(null);
              refreshEpisodes();
            }}
          />
        )}

        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-4 border-b border-border">
            <button
              type="button"
              onClick={() => setTab("review")}
              className={`border-b-2 px-1 pb-2 text-sm font-medium ${
                tab === "review"
                  ? "border-accent text-text"
                  : "border-transparent text-text-muted hover:text-text"
              }`}
            >
              Review queue · {reviewQueue.length + inFlight.length}
            </button>
            <button
              type="button"
              onClick={() => setTab("published")}
              className={`border-b-2 px-1 pb-2 text-sm font-medium ${
                tab === "published"
                  ? "border-accent text-text"
                  : "border-transparent text-text-muted hover:text-text"
              }`}
            >
              Published · {published.length}
            </button>
          </div>

          {queueError && <p className="text-sm text-danger">{queueError}</p>}
          {visible.length === 0 && !queueError && (
            <p className="text-sm text-text-muted">Nothing here yet.</p>
          )}
          <ul className="flex flex-col gap-2">
            {visible.map((episode) => (
              <EpisodeRow key={episode.id} episode={episode} />
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

const STATUS_LABELS: Record<EpisodeStatus, string> = {
  uploading: "Uploading",
  processing: "Preprocessing audio",
  transcribing: "Transcribing",
  generating: "Generating metadata",
  review: "Ready for review",
  published: "Published",
  rejected: "Rejected (too long)",
  failed: "Failed",
};

const STATUS_BADGE_CLASS: Record<EpisodeStatus, string> = {
  uploading: "bg-surface-3 text-text-muted",
  processing: "bg-surface-3 text-text-muted",
  transcribing: "bg-surface-3 text-text-muted",
  generating: "bg-surface-3 text-text-muted",
  review: "bg-accent-soft text-gold",
  published: "bg-accent-soft text-accent-strong",
  rejected: "bg-surface-3 text-danger",
  failed: "bg-surface-3 text-danger",
};

function EpisodeRow({ episode }: { episode: Episode }) {
  const isReviewReady = episode.status === "review";

  return (
    <li className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-text">
          {episode.title || "(untitled)"}
        </p>
        <p className="text-xs text-text-muted">
          Uploaded {formatRelativeTime(episode.created_at)}
        </p>
      </div>
      <span
        className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_BADGE_CLASS[episode.status]}`}
      >
        {STATUS_LABELS[episode.status]}
        {IN_FLIGHT_STATUSES.includes(episode.status) && "…"}
      </span>
      {isReviewReady && (
        <Link
          href={`/admin/review?id=${encodeURIComponent(episode.id)}`}
          className="shrink-0 rounded-full bg-accent px-3 py-1.5 text-xs font-medium text-bg transition hover:bg-accent-strong"
        >
          Review
        </Link>
      )}
    </li>
  );
}

function UploadForm({
  token,
  onUploadStarted,
}: {
  token: string;
  onUploadStarted: (episodeId: string) => void;
}) {
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(null);

    const contentType = guessContentType(file.name);
    if (!contentType) {
      setError("Unsupported file type — use .mp3, .m4a, or .mp4.");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    try {
      const created = await createEpisode(
        { filename: file.name, content_type: contentType },
        token
      );
      setProgress(0);
      await uploadToPresignedPost(created.upload, file, setProgress);
      setProgress(null);
      onUploadStarted(created.id);
    } catch (err) {
      setProgress(null);
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold text-text">Upload an episode</h2>
      <label className="relative flex cursor-pointer flex-col items-center gap-2 rounded-2xl border border-dashed border-border-strong bg-surface px-4 py-8 text-center transition hover:border-accent">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-soft text-accent">
          <Upload size={16} />
        </span>
        <span className="text-sm text-text">
          Drag an episode here, or <span className="text-accent underline">browse files</span>
        </span>
        <span className="text-xs text-text-muted">
          MP3, M4A, or MP4 — title, description, and resources are generated automatically.
        </span>
        <input
          ref={fileInputRef}
          type="file"
          accept=".mp3,.m4a,.mp4,audio/mpeg,audio/mp4,audio/x-m4a"
          onChange={handleFileChange}
          className="absolute inset-0 cursor-pointer opacity-0"
        />
      </label>
      {progress !== null && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}

function UploadStatus({
  token,
  episodeId,
  onDone,
}: {
  token: string;
  episodeId: string;
  onDone: () => void;
}) {
  const [status, setStatus] = useState<EpisodeStatus>("uploading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    // Polling-with-timeout — the same pattern the backend's own
    // integration tests use to assert on this same async pipeline (S3 ->
    // SQS -> worker -> DynamoDB), just driven from the browser instead of
    // pytest. There's no webhook/SSE from the worker, so polling is the
    // simplest way for the UI to observe an eventual status change.
    async function poll() {
      try {
        const episode = await getAdminEpisode(episodeId, token);
        if (cancelled) return;
        setStatus(episode.status);
        if (!IN_FLIGHT_STATUSES.includes(episode.status)) {
          onDone();
          return;
        }
        if (Date.now() > deadline) {
          setError("Timed out waiting for processing to finish.");
          return;
        }
        setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) setError("Lost track of the episode while polling.");
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episodeId, token]);

  return (
    <section className="rounded-xl border border-border bg-surface px-4 py-3">
      <p className="text-sm text-text">
        {STATUS_LABELS[status]}
        {IN_FLIGHT_STATUSES.includes(status) && "…"}
      </p>
      {error && <p className="mt-1 text-sm text-danger">{error}</p>}
      {status === "review" && (
        <Link
          href={`/admin/review?id=${encodeURIComponent(episodeId)}`}
          className="mt-2 inline-block text-sm font-medium text-accent hover:underline"
        >
          Review now
        </Link>
      )}
    </section>
  );
}
