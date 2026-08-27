"use client";

import { ChevronLeft, FileText, RefreshCw, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AdminHeader from "@/components/AdminHeader";
import CoverArt from "@/components/CoverArt";
import EpisodePlayer from "@/components/EpisodePlayer";
import {
  ApiError,
  getAdminEpisode,
  getAdminTranscriptUrl,
  publishEpisode,
  updateEpisode,
} from "@/lib/api";
import { getStoredToken } from "@/lib/auth";
import type { Episode, Resource } from "@/lib/types";

// Same reasoning as app/episode/page.tsx: useSearchParams() needs a
// Suspense boundary under static export.
export default function ReviewPage() {
  return (
    <Suspense fallback={<p className="p-8 text-sm text-text-muted">Loading…</p>}>
      <ReviewEditor />
    </Suspense>
  );
}

function ReviewEditor() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");

  // `undefined` = "haven't checked localStorage yet" (true on both the
  // server, which has no `window` at all, and the client's first render,
  // before effects run — the two agree, so there's nothing to hydrate
  // mismatched). Reading localStorage directly during render instead (as
  // this used to) made the client's first render disagree with the
  // static export whenever a token was already stored, which is a real
  // hydration mismatch, not just a style preference.
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);

  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    // Deferred a tick (see react-hooks/set-state-in-effect) rather than
    // calling setToken() synchronously here.
    Promise.resolve().then(() => setToken(getStoredToken()));
  }, []);

  useEffect(() => {
    if (!token || !id) return;
    getAdminEpisode(id, token)
      .then((data) => {
        setEpisode(data);
        setTitle(data.title);
        setDescription(data.description);
        setResources(data.resources);
      })
      .catch(() => setError("Failed to load episode."));
  }, [id, token]);

  if (token === undefined) {
    return <p className="p-8 text-sm text-text-muted">Checking admin session…</p>;
  }

  if (!token) {
    return (
      <div className="flex flex-col gap-3 p-8">
        <p className="text-sm text-danger">Sign in as admin first.</p>
        <Link href="/admin" className="text-sm text-accent underline">
          Go to admin sign in
        </Link>
      </div>
    );
  }

  if (!id) return <p className="p-8 text-sm text-danger">No episode id given.</p>;
  if (error) return <p className="p-8 text-sm text-danger">{error}</p>;
  if (!episode) return <p className="p-8 text-sm text-text-muted">Loading…</p>;

  function updateResource(index: number, field: keyof Resource, value: string) {
    setResources((prev) =>
      prev.map((resource, i) => (i === index ? { ...resource, [field]: value } : resource))
    );
  }

  function removeResource(index: number) {
    setResources((prev) => prev.filter((_, i) => i !== index));
  }

  function addResource() {
    setResources((prev) => [...prev, { label: "", url: "https://" }]);
  }

  async function handleSave() {
    setSaving(true);
    setSaveMessage(null);
    try {
      const updated = await updateEpisode(
        id as string,
        { title, description, resources },
        token as string
      );
      setEpisode(updated);
      setSaveMessage("Saved.");
    } catch (err) {
      setSaveMessage(
        err instanceof ApiError ? `Failed to save: ${err.message}` : "Failed to save."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handlePublish() {
    setPublishing(true);
    setPublishError(null);
    try {
      const updated = await publishEpisode(id as string, token as string);
      setEpisode(updated);
    } catch (err) {
      setPublishError(
        err instanceof ApiError ? err.message : "Failed to publish."
      );
    } finally {
      setPublishing(false);
    }
  }

  const isReview = episode.status === "review";
  const isEditable = isReview || episode.status === "published";

  return (
    <div className="min-h-screen">
      <AdminHeader />
      <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-8">
        <Link
          href="/admin"
          className="inline-flex items-center gap-1 text-sm text-text-muted hover:text-text hover:underline"
        >
          <ChevronLeft size={16} /> Admin
        </Link>

        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-text">Review episode</h1>
          <span className="rounded-full bg-accent-soft px-3 py-1 text-xs font-semibold uppercase tracking-wide text-gold">
            {episode.status}
          </span>
        </div>

        {episode.status === "published" && (
          <p className="text-sm text-accent-strong">
            Published.{" "}
            <Link
              href={`/episode?id=${encodeURIComponent(episode.id)}`}
              className="underline"
            >
              View on the public page
            </Link>
            .
          </p>
        )}

        <div className="flex items-center gap-3">
          <CoverArt seed={episode.id} className="h-16 w-16 shrink-0" />
          <div>
            <p className="text-xs text-text-muted">Generated cover art — no upload needed.</p>
            <button
              type="button"
              disabled
              title="Regenerating cover art needs a stored seed on the episode — not supported by the API yet"
              className="mt-1 flex cursor-not-allowed items-center gap-1.5 text-xs font-medium text-text-muted opacity-60"
            >
              <RefreshCw size={12} /> Regenerate
            </button>
          </div>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-text">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-text">Description</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            className="rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text"
          />
        </label>

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-text">Resources</span>
          {resources.map((resource, index) => (
            <div key={index} className="flex gap-2">
              <input
                value={resource.label}
                onChange={(e) => updateResource(index, "label", e.target.value)}
                placeholder="Label"
                className="w-1/3 rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text"
              />
              <input
                value={resource.url}
                onChange={(e) => updateResource(index, "url", e.target.value)}
                placeholder="https://..."
                className="flex-1 rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text"
              />
              <button
                type="button"
                onClick={() => removeResource(index)}
                aria-label={`Remove resource ${resource.label || index + 1}`}
                className="text-text-muted transition hover:text-danger"
              >
                <X size={16} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addResource}
            className="self-start text-sm text-accent hover:underline"
          >
            + Add resource
          </button>
        </div>

        <TranscriptSection episodeId={episode.id} token={token as string} />

        <EpisodePlayer episode={episode} />

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !isEditable}
            title={
              isEditable
                ? undefined
                : "Editing is unavailable while this episode is still processing."
            }
            className="rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-text transition hover:border-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          {isReview && (
            <button
              type="button"
              onClick={handlePublish}
              disabled={publishing}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg transition hover:bg-accent-strong disabled:opacity-50"
            >
              {publishing ? "Publishing…" : "Publish"}
            </button>
          )}
          <button
            type="button"
            disabled
            title="Deleting an episode isn't wired up on the backend yet (the DELETE route is a stub) — see backecast#11"
            className="ml-auto flex cursor-not-allowed items-center gap-1.5 rounded-lg border border-danger/40 px-4 py-2 text-sm font-medium text-danger opacity-50"
          >
            <Trash2 size={14} /> Delete episode
          </button>
          {saveMessage && <span className="text-sm text-text-muted">{saveMessage}</span>}
        </div>
        {publishError && <p className="text-sm text-danger">{publishError}</p>}
      </div>
    </div>
  );
}

function TranscriptSection({
  episodeId,
  token,
}: {
  episodeId: string;
  token: string;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleView() {
    setLoading(true);
    setError(null);
    try {
      const { url } = await getAdminTranscriptUrl(episodeId, token);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load transcript."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium text-text">Transcript</span>
      <div className="flex items-center justify-between rounded-lg border border-dashed border-border-strong bg-surface-2 px-3 py-2.5">
        <span className="flex items-center gap-1.5 text-sm text-text-muted">
          <FileText size={14} /> The raw transcript the AI generated title/description from.
        </span>
        <button
          type="button"
          onClick={handleView}
          disabled={loading}
          className="shrink-0 rounded-md border border-border-strong px-2.5 py-1 text-xs font-medium text-text transition hover:border-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Loading…" : "View transcript"}
        </button>
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}
