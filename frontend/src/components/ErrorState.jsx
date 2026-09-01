export default function ErrorState({ message = "Something went wrong.", onRetry }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-surface-solid px-6 py-12 text-center">
      <p className="text-sm text-text-muted">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded-full border border-border px-4 py-1.5 text-sm text-text transition-colors duration-200 hover:border-accent/40 hover:text-accent"
        >
          Try again
        </button>
      )}
    </div>
  );
}
