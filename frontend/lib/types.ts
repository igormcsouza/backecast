// Hand-written mirror of backend/app/episodes/schemas.py — no codegen, kept
// in sync by hand (small, slow-moving schema; not worth a build step for
// this MVP). If you touch schemas.py, check here too.

export type EpisodeStatus =
  | "uploading"
  | "processing"
  | "transcribing"
  | "generating"
  | "review"
  | "published"
  | "rejected"
  | "failed";

export interface Resource {
  label: string;
  url: string;
}

// Mirrors GetEpisodeSchema.
export interface Episode {
  id: string;
  title: string;
  description: string;
  status: EpisodeStatus;
  duration: number;
  release_date: string;
  audio_url: string | null;
  image_url: string | null;
  created_at: string;
  updated_at: string;
  resources: Resource[];
}

// Mirrors worker/transcription.py's Transcript/TranscriptSegment/
// TranscriptWord TypedDicts — the JSON stored at transcripts/{id}.json and
// served (as a presigned URL) via GET /episodes/{id}/transcript[/admin].
export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
}

export interface TranscriptSegment {
  text: string;
  start: number;
  end: number;
  words: TranscriptWord[];
}

export interface Transcript {
  text: string;
  segments: TranscriptSegment[];
}

// Mirrors PaginatedEpisodesResponse.
export interface PaginatedEpisodes {
  items: Episode[];
  cursor: string | null;
}

// Mirrors PresignedPostSchema — boto3's generate_presigned_post() shape.
export interface PresignedPost {
  url: string;
  fields: Record<string, string>;
}

// Mirrors CreateEpisodeResponse.
export interface CreateEpisodeResponse {
  id: string;
  status: EpisodeStatus;
  upload: PresignedPost;
}

// Mirrors UpdateEpisodeRequest — every field optional, only send what changed.
export interface UpdateEpisodeRequest {
  title?: string;
  description?: string;
  resources?: Resource[];
}
