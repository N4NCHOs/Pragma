import AssetTag from "./AssetTag.jsx";

const VALUE_COLORS = {
  High: "text-bearish",
  Bearish: "text-bearish",
  Medium: "text-neutral",
  Neutral: "text-neutral",
  Low: "text-bullish",
  Bullish: "text-bullish",
};

export default function ClassificationCard({ label, value }) {
  const isList = Array.isArray(value);
  const colorClass = !isList && VALUE_COLORS[value] ? VALUE_COLORS[value] : "text-accent";

  return (
    <div className="rounded-xl border border-border bg-surface-solid px-5 py-6 text-center transition-colors duration-200 hover:border-accent/40">
      <p className="text-xs font-semibold tracking-wider text-text-muted uppercase">{label}</p>

      {isList ? (
        <div className="mt-3 flex flex-wrap justify-center gap-1.5">
          {value.length > 0 ? (
            value.map((item) => (
              <AssetTag key={item} className="border-accent/30 text-accent">
                {item}
              </AssetTag>
            ))
          ) : (
            <span className="text-sm text-text-faint">—</span>
          )}
        </div>
      ) : (
        <p className={`mt-2 text-lg font-semibold ${colorClass}`}>{value || "—"}</p>
      )}
    </div>
  );
}
