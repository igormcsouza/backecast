import { isSameMonth } from "@/lib/format";
import type { Episode } from "@/lib/types";

export interface AdminStats {
  publishedCount: number;
  reviewCount: number;
  totalContentSeconds: number;
  uploadedThisMonth: number;
}

// Every number here comes straight out of `GET /episodes/admin` (no
// status filter returns every episode, any status — see
// backend/app/episodes/service.py's list_admin_episodes) — nothing
// fabricated, just aggregated client-side since there's no dedicated
// stats endpoint.
export function computeAdminStats(allEpisodes: Episode[]): AdminStats {
  const now = new Date();
  const published = allEpisodes.filter((e) => e.status === "published");
  const review = allEpisodes.filter((e) => e.status === "review");
  const uploadedThisMonth = allEpisodes.filter((e) => isSameMonth(e.created_at, now));

  return {
    publishedCount: published.length,
    reviewCount: review.length,
    totalContentSeconds: published.reduce((sum, e) => sum + (e.duration || 0), 0),
    uploadedThisMonth: uploadedThisMonth.length,
  };
}
