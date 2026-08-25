import { generateCoverArt } from "@/lib/coverArt";

export default function CoverArt({
  seed,
  className = "",
}: {
  seed: string;
  className?: string;
}) {
  const { gradient, waveform } = generateCoverArt(seed);

  return (
    <div
      aria-hidden="true"
      className={`relative flex items-end overflow-hidden rounded-xl ${className}`}
      style={{ background: gradient }}
    >
      <div className="flex h-1/2 w-full items-end gap-[2px] px-2 pb-2 opacity-60">
        {waveform.map((height, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm bg-black/30"
            style={{ height: `${Math.round(height * 100)}%` }}
          />
        ))}
      </div>
    </div>
  );
}
