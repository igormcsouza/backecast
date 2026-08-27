"use client";

export type SortOption = "newest" | "oldest" | "longest";

const OPTIONS: { label: string; value: SortOption }[] = [
  { label: "Newest", value: "newest" },
  { label: "Oldest", value: "oldest" },
  { label: "Longest", value: "longest" },
];

export default function SortChips({
  value,
  onChange,
}: {
  value: SortOption;
  onChange: (value: SortOption) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      {OPTIONS.map((option) => {
        const isActive = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            aria-pressed={isActive}
            className={
              isActive
                ? "rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent-strong"
                : "rounded-full px-3 py-1 text-xs font-medium text-text-muted transition hover:bg-surface-muted"
            }
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
