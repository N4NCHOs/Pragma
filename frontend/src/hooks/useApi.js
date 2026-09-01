import { useEffect, useState, useCallback } from "react";

/**
 * Runs `fetchFn` whenever `deps` change and exposes {data, loading, error}.
 * `fetchFn` must be stable/memoized by the caller (e.g. via useCallback) so
 * this hook doesn't re-run on every render.
 */
export default function useApi(fetchFn, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const run = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchFn()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => run(), [run]);

  return { data, loading, error, refetch: run };
}
