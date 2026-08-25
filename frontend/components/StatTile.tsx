import type { ComponentType } from "react";

export default function StatTile({
  icon: Icon,
  label,
  value,
}: {
  icon: ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: string | number;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">{label}</span>
        <Icon size={14} className="text-text-muted" />
      </div>
      <span className="text-2xl font-semibold text-text">{value}</span>
    </div>
  );
}
