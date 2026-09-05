const SENTIMENT_TINTS = {
  Bullish: "#4ade8033",
  Bearish: "#f8717133",
  Neutral: "#fbbf2433",
};

/**
 * Deterministic placeholder art for an article — the API has no image field,
 * so this stands in for a real thumbnail: a soft diagonal tint (by sentiment)
 * over the card surface, plus a faint line-chart glyph. Same article always
 * renders the same way; no network fetch, no stock-photo service.
 */

/**ADDITION
 * Displays the article image when available.
 * The sentiment illustration remains as a fallback.
 */
export default function Thumbnail({ imageUrl, sentiment, className = "" }) {
  const tint = SENTIMENT_TINTS[sentiment] || "#6b718233";

  return (
    <div
      className={`relative overflow-hidden bg-surface-solid ${className}`}
      style={{
        backgroundImage: `linear-gradient(135deg, ${tint}, transparent 65%)`,
      }}
    >
      {imageUrl && (
        <img
          src={imageUrl}
          alt=""
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
          onError={(event) => {
            event.currentTarget.style.display = "none";
          }}
        />
      )}

      <svg
        viewBox="0 0 100 40"
        className="absolute inset-0 h-full w-full opacity-20"
        preserveAspectRatio="none"
      >
        <polyline
          points="0,30 18,22 34,26 50,12 68,18 84,6 100,14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-text-muted"
        />
      </svg>
    </div>
  );
}
