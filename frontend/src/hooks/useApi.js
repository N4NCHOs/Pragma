import { useEffect, useState, useCallback, useRef } from "react";

/**
 * Runs `fetchFn` whenever `deps` change and exposes {data, loading, error, refetch}.
 * If `pollIntervalMs` is supplied, it automatically refetches on that timer.
 */
export default function useApi(fetchFn, deps = [], pollIntervalMs = null) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Keep a ref to the latest fetch function
  const fetchFnRef = useRef(fetchFn);
  useEffect(() => {
    fetchFnRef.current = fetchFn;
  }, [fetchFn]);

  const run = useCallback((isBackground = false) => {
    let cancelled = false;
    
    // Only show full loading state on initial load or manual retry
    if (!isBackground) {
      setLoading(true);
      setError(null);
    }

    fetchFnRef.current()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled && !isBackground) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Initial load when dependencies change
  useEffect(() => {
    return run();
  }, [run]);

  // Periodic polling interval
  useEffect(() => {
    if (!pollIntervalMs || pollIntervalMs <= 0) return;

    const intervalId = setInterval(() => {
      run(true); // pass true for background silent refresh
    }, pollIntervalMs);

    return () => clearInterval(intervalId);
  }, [run, pollIntervalMs]);

  return { data, loading, error, refetch: () => run(false) };
}