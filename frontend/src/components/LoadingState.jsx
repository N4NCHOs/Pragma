const VARIANTS = {
  asset: { grid: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5", height: "h-32" },
  card: { grid: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3", height: "h-64" },
};

export default function LoadingState({ count = 6, variant = "card" }) {
  const { grid, height } = VARIANTS[variant] || VARIANTS.card;

  return (
    <div className={`grid gap-5 ${grid}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={`skeleton rounded-2xl border border-border ${height}`} />
      ))}
    </div>
  );
}
