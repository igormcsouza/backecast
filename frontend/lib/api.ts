// Thin fetch wrapper against the FastAPI backend. Everything here is
// client-side fetching — no Next.js API routes, no server components doing
// data fetching — required by static export (`output: 'export'` produces
// plain HTML/JS with no Node.js server to run route handlers on).

import type {
  CreateEpisodeResponse,
  Episode,
  PaginatedEpisodes,
  UpdateEpisodeRequest,
} from "./types";

// Read at *module load* time in the browser bundle — Next.js inlines
// NEXT_PUBLIC_* vars into the client JS at build time, so this really is a
// build-time constant despite living in a "runtime" module. Falls back to
// docker-compose's host-mapped port (see docker-compose.yml's `api.ports:
// 8989:8000`) so local dev works with zero setup beyond `docker compose up`.
const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8989"
).replace(/\/+$/, "");
const API_V1 = `${API_BASE_URL}/api/v1`;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  token?: string
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_V1}${path}`, { ...init, headers });

  if (!response.ok) {
    let message = response.statusText || `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.error === "string") message = body.error;
    } catch {
      // not a JSON error body — keep the status text
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// --- Public routes (no admin key) --------------------------------------

export function listPublicEpisodes(
  limit = 10,
  cursor?: string | null,
  sort: "newest" | "oldest" | "longest" = "newest",
  q?: string
): Promise<PaginatedEpisodes> {
  const params = new URLSearchParams({ limit: String(limit), sort });
  if (cursor) params.set("cursor", cursor);
  if (q) params.set("q", q);
  return request<PaginatedEpisodes>(`/episodes?${params.toString()}`);
}

export function getPublicEpisode(id: string): Promise<Episode> {
  return request<Episode>(`/episodes/${encodeURIComponent(id)}`);
}

// --- Admin routes (all require a Cognito bearer token) ------------------

export function createEpisode(
  payload: { filename: string; content_type: string },
  token: string
): Promise<CreateEpisodeResponse> {
  return request<CreateEpisodeResponse>(
    "/episodes",
    { method: "POST", body: JSON.stringify(payload) },
    token
  );
}

export function listAdminEpisodes(
  token: string,
  status?: string
): Promise<Episode[]> {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<Episode[]>(`/episodes/admin${suffix}`, {}, token);
}

export function getAdminEpisode(id: string, token: string): Promise<Episode> {
  return request<Episode>(
    `/episodes/${encodeURIComponent(id)}/admin`,
    {},
    token
  );
}

export function updateEpisode(
  id: string,
  payload: UpdateEpisodeRequest,
  token: string
): Promise<Episode> {
  return request<Episode>(
    `/episodes/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(payload) },
    token
  );
}

export function publishEpisode(id: string, token: string): Promise<Episode> {
  return request<Episode>(
    `/episodes/${encodeURIComponent(id)}/publish`,
    { method: "POST" },
    token
  );
}

export function getPublicTranscriptUrl(id: string): Promise<{ url: string }> {
  return request<{ url: string }>(
    `/episodes/${encodeURIComponent(id)}/transcript`
  );
}

export function getAdminTranscriptUrl(
  id: string,
  token: string
): Promise<{ url: string }> {
  return request<{ url: string }>(
    `/episodes/${encodeURIComponent(id)}/transcript/admin`,
    {},
    token
  );
}

// Direct-to-S3 upload using the presigned POST's fields. Deliberately XHR,
// not fetch: fetch's upload-progress story (ReadableStream request bodies)
// isn't reliably supported across browsers yet, while
// XMLHttpRequest.upload.onprogress has worked everywhere for over a
// decade — the pragmatic choice for a progress bar, not a stylistic one.
export function uploadToPresignedPost(
  upload: { url: string; fields: Record<string, string> },
  file: File,
  onProgress?: (fraction: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    // S3's presigned POST policy checks these fields (and their order
    // relative to the file part doesn't matter, but they must precede a
    // multipart boundary the browser handles for us) — `file` must be
    // appended last per S3's documented presigned-POST contract.
    for (const [key, value] of Object.entries(upload.fields)) {
      formData.append(key, value);
    }
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", upload.url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(event.loaded / event.total);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed with status ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed (network error)"));
    xhr.send(formData);
  });
}
