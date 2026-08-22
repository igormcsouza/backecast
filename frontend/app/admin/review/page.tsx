"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ApiError, getAdminEpisode, publishEpisode, updateEpisode } from "@/lib/api";
import { getStoredAdminKey } from "@/lib/admin-key";
import type { Episode, Resource } from "@/lib/types";

// Same reasoning as app/episode/page.tsx: useSearchParams() needs a
// Suspense boundary under static export.
export default function ReviewPage() {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
      <ReviewEditor />
    </Suspense>
  );
}

function ReviewEditor() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");
  const adminKey = getStoredAdminKey();

  const [episode, setEpisode] = useState<Episode | null>(null);
  // Initial state already reflects the "can't fetch yet" cases (no admin
  // key, no id) so the effect never needs to call setState synchronously
  // in those branches (see react-hooks/set-state-in-effect).
  const [loading, setLoading] = useState(!!(adminKey && id));
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);

  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    if (!adminKey || !id) return;
    getAdminEpisode(id, adminKey)
      .then((data) => {
        setEpisode(data);
        setTitle(data.title);
        setDescription(data.description);
        setResources(data.resources);
      })
      .catch(() => setError("Failed to load episode."))
      .finally(() => setLoading(false));
  }, [id, adminKey]);

  if (!adminKey) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-red-600 dark:text-red-400">
          Sign in as admin first.
        </p>
        <Link href="/admin" className="text-sm underline">
          Go to admin sign in
        </Link>
      </div>
    );
  }

  if (!id) return <p className="text-sm text-red-600 dark:text-red-400">No episode id given.</p>;
  if (loading) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (error || !episode) {
    return <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Not found."}</p>;
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
        adminKey as string
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
      const updated = await publishEpisode(id as string, adminKey as string);
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
    <div className="flex flex-col gap-6">
      <Link href="/admin" className="text-sm text-zinc-500 hover:underline">
        &larr; Admin
      </Link>

      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Review episode</h1>
        <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs font-medium uppercase tracking-wide text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
          {episode.status}
        </span>
      </div>

      {episode.status === "published" && (
        <p className="text-sm text-green-700 dark:text-green-400">
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

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Title</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          disabled={!isReview}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Description</span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={!isReview}
          rows={5}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>

      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Resources</span>
        {resources.map((resource, index) => (
          <div key={index} className="flex gap-2">
            <input
              value={resource.label}
              onChange={(e) => updateResource(index, "label", e.target.value)}
              placeholder="Label"
              disabled={!isReview}
              className="w-1/3 rounded-md border border-zinc-300 px-3 py-2 text-sm disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
            />
            <input
              value={resource.url}
              onChange={(e) => updateResource(index, "url", e.target.value)}
              placeholder="https://..."
              disabled={!isReview}
              className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
            />
            {isReview && (
              <button
                type="button"
                onClick={() => removeResource(index)}
                className="text-sm text-zinc-500 hover:text-red-600"
              >
                Remove
              </button>
            )}
          </div>
        ))}
        {isReview && (
          <button
            type="button"
            onClick={addResource}
            className="self-start text-sm text-blue-600 hover:underline dark:text-blue-400"
          >
            + Add resource
          </button>
        )}
      </div>

      {episode.audio_url && (
        <audio controls src={episode.audio_url} className="w-full" />
      )}

      {isReview && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          <button
            type="button"
            onClick={handlePublish}
            disabled={publishing}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {publishing ? "Publishing…" : "Publish"}
          </button>
          {saveMessage && <span className="text-sm text-zinc-500">{saveMessage}</span>}
        </div>
      )}
      {publishError && (
        <p className="text-sm text-red-600 dark:text-red-400">{publishError}</p>
      )}
    </div>
  );
}
