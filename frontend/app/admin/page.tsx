"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  createEpisode,
  getAdminEpisode,
  listAdminEpisodes,
  uploadToPresignedPost,
} from "@/lib/api";
import { clearStoredToken, getStoredToken, setStoredToken, login } from "@/lib/auth";
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

  // On mount, validate a previously-issued token from localStorage against
  // the admin list route (cheap, side-effect-free) so an expired/revoked
  // token doesn't silently look "logged in" until the first real action
  // fails.
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
    return <p className="text-sm text-zinc-500">Checking admin session…</p>;
  }

  if (!token) {
    return (
      <div className="mx-auto flex max-w-sm flex-col gap-4">
        <h1 className="text-xl font-semibold">Admin sign in</h1>
        <form onSubmit={handleLogin} className="flex flex-col gap-3">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoComplete="username"
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            autoFocus
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="submit"
            className="rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
          >
            Sign in
          </button>
        </form>
        {loginError && <p className="text-sm text-red-600 dark:text-red-400">{loginError}</p>}
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
  const [reviewQueue, setReviewQueue] = useState<Episode[]>([]);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [activeUploadId, setActiveUploadId] = useState<string | null>(null);

  const refreshQueue = () => {
    listAdminEpisodes(token, "review")
      .then((items) => {
        setReviewQueue(items);
        setQueueError(null);
      })
      .catch(() => setQueueError("Failed to load the review queue."));
  };

  useEffect(refreshQueue, [token]);

  return (
    <div className="flex flex-col gap-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
        <button
          type="button"
          onClick={onLogout}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-50"
        >
          Sign out
        </button>
      </div>

      <UploadForm token={token} onUploadStarted={setActiveUploadId} />

      {activeUploadId && (
        <UploadStatus
          token={token}
          episodeId={activeUploadId}
          onDone={() => {
            setActiveUploadId(null);
            refreshQueue();
          }}
        />
      )}

      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Review queue</h2>
        {queueError && <p className="text-sm text-red-600 dark:text-red-400">{queueError}</p>}
        {reviewQueue.length === 0 && !queueError && (
          <p className="text-sm text-zinc-500">Nothing waiting for review.</p>
        )}
        <ul className="flex flex-col gap-3">
          {reviewQueue.map((episode) => (
            <li
              key={episode.id}
              className="flex items-center justify-between rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800"
            >
              <span className="text-sm">{episode.title || "(untitled)"}</span>
              <Link
                href={`/admin/review?id=${encodeURIComponent(episode.id)}`}
                className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Review
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
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
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Upload an episode</h2>
      <input
        ref={fileInputRef}
        type="file"
        accept=".mp3,.m4a,.mp4,audio/mpeg,audio/mp4,audio/x-m4a"
        onChange={handleFileChange}
        className="text-sm"
      />
      {progress !== null && (
        <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
          <div
            className="h-full rounded-full bg-zinc-900 transition-all dark:bg-zinc-100"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
      )}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
    </section>
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
    <section className="rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <p className="text-sm">
        {STATUS_LABELS[status]}
        {IN_FLIGHT_STATUSES.includes(status) && "…"}
      </p>
      {error && <p className="mt-1 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {status === "review" && (
        <Link
          href={`/admin/review?id=${encodeURIComponent(episodeId)}`}
          className="mt-2 inline-block text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
        >
          Review now
        </Link>
      )}
    </section>
  );
}
