"use client";

import { RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AdminHeader from "@/components/AdminHeader";
import CoverArt from "@/components/CoverArt";
import EpisodePlayer from "@/components/EpisodePlayer";
import { ApiError, getAdminEpisode, publishEpisode, updateEpisode } from "@/lib/api";
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
  const token = getStoredToken();

  const [episode, setEpisode] = useState<Episode | null>(null);
  // Initial state already reflects the "can't fetch yet" cases (no admin
  // key, no id) so the effect never needs to call setState synchronously
  // in those branches (see react-hooks/set-state-in-effect).
  const [loading, setLoading] = useState(!!(token && id));
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);

  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !id) return;
    getAdminEpisode(id, token)
      .then((data) => {
        setEpisode(data);
        setTitle(data.title);
        setDescription(data.description);
        setResources(data.resources);
      })
      .catch(() => setError("Failed to load episode."))
      .finally(() => setLoading(false));
  }, [id, token]);

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
  if (loading) return <p className="p-8 text-sm text-text-muted">Loading…</p>;
  if (error || !episode) {
    return <p className="p-8 text-sm text-danger">{error ?? "Not found."}</p>;
  }

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

  return (
    <div className="min-h-screen">
      <AdminHeader />
      <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-8">
        <Link href="/admin" className="text-sm text-text-muted hover:underline">
          &larr; Admin
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
            disabled={!isReview}
            className="rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text disabled:opacity-60"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-text">Description</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={!isReview}
            rows={4}
            className="rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text disabled:opacity-60"
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
                disabled={!isReview}
                className="w-1/3 rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text disabled:opacity-60"
              />
              <input
                value={resource.url}
                onChange={(e) => updateResource(index, "url", e.target.value)}
                placeholder="https://..."
                disabled={!isReview}
                className="flex-1 rounded-lg border border-border-strong bg-surface-2 px-3 py-2 text-sm text-text disabled:opacity-60"
              />
              {isReview && (
                <button
                  type="button"
                  onClick={() => removeResource(index)}
                  aria-label={`Remove resource ${resource.label || index + 1}`}
                  className="text-text-muted transition hover:text-danger"
                >
                  <X size={16} />
                </button>
              )}
            </div>
          ))}
          {isReview && (
            <button
              type="button"
              onClick={addResource}
              className="self-start text-sm text-accent hover:underline"
            >
              + Add resource
            </button>
          )}
        </div>

        <EpisodePlayer episode={episode} />

        {isReview && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-text transition hover:border-accent disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
            <button
              type="button"
              onClick={handlePublish}
              disabled={publishing}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg transition hover:bg-accent-strong disabled:opacity-50"
            >
              {publishing ? "Publishing…" : "Publish"}
            </button>
            {saveMessage && <span className="text-sm text-text-muted">{saveMessage}</span>}
          </div>
        )}
        {publishError && <p className="text-sm text-danger">{publishError}</p>}
      </div>
    </div>
  );
}
