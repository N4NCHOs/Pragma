export default function AssetTag({ children, className = "" }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border border-border px-3 py-1 text-xs font-semibold tracking-wide text-text-muted ${className}`}
    >
      {children}
    </span>
  );
}
