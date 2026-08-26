import { ExternalLink, FileText, Mic2, NotebookText } from "lucide-react";
import type { Resource } from "@/lib/types";

function iconFor(label: string) {
  const lower = label.toLowerCase();
  if (lower.includes("transcript")) return FileText;
  if (lower.includes("note")) return NotebookText;
  if (lower.includes("guest")) return Mic2;
  return ExternalLink;
}

export default function ResourceList({ resources }: { resources: Resource[] }) {
  if (resources.length === 0) return null;

  return (
    <div>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
        Resources
      </h2>
      <ul className="mt-2 flex flex-col divide-y divide-border overflow-hidden rounded-xl border border-border">
        {resources.map((resource) => {
          const Icon = iconFor(resource.label);
          return (
            <li key={resource.url}>
              <a
                href={resource.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 px-3 py-2 text-sm text-text transition hover:bg-surface-2"
              >
                <Icon size={14} className="shrink-0 text-accent" />
                <span className="flex-1 truncate">{resource.label}</span>
                <span className="truncate text-xs text-text-muted">{resource.url}</span>
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
