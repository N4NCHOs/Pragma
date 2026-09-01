import { useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import useApi from "../hooks/useApi.js";
import { getAssets, getAssetNews } from "../api/endpoints.js";
import { getAssetVisual } from "../constants/assetVisuals.js";
import NewsCard from "../components/NewsCard.jsx";
import LoadingState from "../components/LoadingState.jsx";
import ErrorState from "../components/ErrorState.jsx";

export default function CoinDetail() {
  const { assetId } = useParams();

  const fetchCoin = useCallback(async () => {
    const [assets, news] = await Promise.all([getAssets(), getAssetNews(assetId)]);
    const asset = assets.find((a) => a.asset_id === assetId);
    return { asset, news };
  }, [assetId]);

  const { data, loading, error, refetch } = useApi(fetchCoin, [fetchCoin]);

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-16">
        <div className="skeleton h-24 rounded-2xl border border-border" />
        <div className="mt-10">
          <LoadingState count={6} variant="card" />
        </div>
      </div>
    );
  }

  if (error || !data?.asset) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-16">
        <ErrorState message="Couldn't load this coin." onRetry={refetch} />
      </div>
    );
  }

  const { asset, news } = data;
  const { glyph, color, description } = getAssetVisual(asset.asset_id);

  return (
    <div className="mx-auto max-w-6xl px-6 pb-20 pt-12 sm:pt-16">
      <Link to="/" className="text-sm text-text-muted transition-colors duration-200 hover:text-accent">
        ← Back
      </Link>

      <div className="mt-6 flex flex-col items-start gap-6 border-b border-border pb-8 sm:flex-row sm:items-center">
        <span
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-2xl font-bold text-white shadow-sm"
          style={{ backgroundColor: color }}
        >
          {glyph}
        </span>
        <div className="flex items-center gap-6">
          <div>
            <p className="text-2xl font-bold">{asset.ticker}</p>
            <p className="text-accent">{asset.name.toLowerCase()}</p>
          </div>
          <div className="hidden h-12 w-px bg-border sm:block" />
          <p className="max-w-2xl text-sm leading-relaxed text-text-muted">{description}</p>
        </div>
      </div>

      <div className="mt-10">
        {news.length > 0 ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {news.map((article) => (
              <NewsCard key={article.id} article={article} />
            ))}
          </div>
        ) : (
          <p className="text-center text-text-muted">No news for {asset.ticker} yet.</p>
        )}
      </div>
    </div>
  );
}
