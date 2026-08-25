"use client";

// `GET /episodes` only ever returns newest-created-first, cursor-paginated
// (see backend/app/episodes/repository.py's list_published_page) — there's
// no server-side "oldest" or "longest" ordering to switch to, and sorting
// only the already-fetched page client-side would silently break as soon
// as "Load more" pages in more items. So those two stay visible (per the
// design guide) but disabled, rather than wired to a fake client-only
// sort.
const OPTIONS = ["Newest", "Oldest", "Longest"] as const;

export default function SortChips() {
  return (
    <div className="flex items-center gap-2">
      {OPTIONS.map((option) => {
        const isActive = option === "Newest";
        return (
          <button
            key={option}
            type="button"
            disabled={!isActive}
            title={isActive ? undefined : `Sort by ${option.toLowerCase()} is coming soon`}
            aria-pressed={isActive}
            className={
              isActive
                ? "rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent-strong"
                : "cursor-not-allowed rounded-full px-3 py-1 text-xs font-medium text-text-muted opacity-50"
            }
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}
