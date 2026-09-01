import { useCallback, useEffect, useState } from "react";
import { getNews } from "../api/endpoints.js";
import NewsCard from "../components/NewsCard.jsx";
import LoadingState from "../components/LoadingState.jsx";
import ErrorState from "../components/ErrorState.jsx";

const PAGE_SIZE = 30;

export default function NewsGrid() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const loadPage = useCallback((skip) => {
    return getNews({ skip, limit: PAGE_SIZE });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    loadPage(0)
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
      })
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [loadPage]);

  const handleLoadMore = () => {
    setLoadingMore(true);
    loadPage(items.length)
      .then((page) => {
        setItems((prev) => [...prev, ...page.items]);
        setTotal(page.total);
      })
      .catch((err) => setError(err))
      .finally(() => setLoadingMore(false));
  };

  if (loading) return <LoadingState count={9} variant="card" />;
  if (error) {
    return (
      <ErrorState
        message="Couldn't load the latest news."
        onRetry={() => loadPage(0).then((page) => {
          setItems(page.items);
          setTotal(page.total);
          setError(null);
        })}
      />
    );
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((article) => (
          <NewsCard key={article.id} article={article} />
        ))}
      </div>

      {items.length < total && (
        <div className="mt-10 flex justify-center">
          <button
            onClick={handleLoadMore}
            disabled={loadingMore}
            className="rounded-full border border-border px-6 py-2 text-sm font-medium text-text-muted transition-colors duration-200 hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
