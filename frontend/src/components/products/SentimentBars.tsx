import { useEffect, useState } from "react";
import type { Product } from "../../types";

const ASPECTS: { key: keyof Product; label: string }[] = [
  { key: "performance_sentiment", label: "Performance" },
  { key: "display_sentiment",     label: "Display" },
  { key: "build_quality_sentiment", label: "Build Quality" },
  { key: "battery_sentiment",     label: "Battery" },
  { key: "keyboard_sentiment",    label: "Keyboard" },
  { key: "thermal_sentiment",     label: "Thermals" },
  { key: "value_sentiment",       label: "Value" },
];

function scoreColor(score: number): string {
  if (score >= 4.0) return "bg-emerald-500";
  if (score >= 3.0) return "bg-indigo-500";
  if (score >= 2.0) return "bg-amber-500";
  return "bg-red-500";
}

interface SentimentBarsProps {
  product: Product;
}

export default function SentimentBars({ product }: SentimentBarsProps) {
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    // Trigger fill animation after mount
    const t = setTimeout(() => setAnimated(true), 80);
    return () => clearTimeout(t);
  }, []);

  const scoredAspects = ASPECTS.filter(
    (a) => product[a.key] != null
  ) as { key: keyof Product; label: string }[];

  if (!scoredAspects.length) {
    return (
      <p className="text-sm text-gray-500">
        Sentiment analysis not yet available for this product.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {scoredAspects.map(({ key, label }) => {
        const raw = product[key] as number;
        const pct = Math.round((raw / 5) * 100);
        return (
          <div key={key} className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-sm text-gray-400">{label}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#2a2d36]">
              <div
                className={`h-full rounded-full transition-all duration-700 ease-out ${scoreColor(raw)}`}
                style={{ width: animated ? `${pct}%` : "0%" }}
              />
            </div>
            <span className="w-8 shrink-0 text-right text-sm font-medium text-white">
              {raw.toFixed(1)}
            </span>
          </div>
        );
      })}

      {/* Praise / complaint quotes */}
      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {product.top_praise && (
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-emerald-400">
              Top Praise
            </p>
            <p className="text-sm text-gray-300">"{product.top_praise}"</p>
          </div>
        )}
        {product.top_complaint && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-amber-400">
              Top Complaint
            </p>
            <p className="text-sm text-gray-300">"{product.top_complaint}"</p>
          </div>
        )}
      </div>
    </div>
  );
}
