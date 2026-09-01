const STYLES = {
  Bullish: { dot: "bg-bullish", text: "text-bullish" },
  Bearish: { dot: "bg-bearish", text: "text-bearish" },
  Neutral: { dot: "bg-neutral", text: "text-neutral" },
};

export default function SentimentPill({ sentiment, className = "" }) {
  const style = STYLES[sentiment] || { dot: "bg-text-faint", text: "text-text-muted" };

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${style.text} ${className}`}>
      <span className={`h-1.5 w-4 rounded-full ${style.dot}`} />
      {sentiment || "Unknown"}
    </span>
  );
}
