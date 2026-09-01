import { useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import useApi from "../hooks/useApi.js";
import { getAssets, getNewsDetail } from "../api/endpoints.js";
import Thumbnail from "../components/Thumbnail.jsx";
import SentimentPill from "../components/SentimentPill.jsx";
import AssetTag from "../components/AssetTag.jsx";
import ClassificationCard from "../components/ClassificationCard.jsx";
import ErrorState from "../components/ErrorState.jsx";
import { formatNewsTimestamp } from "../utils/formatDate.js";

export default function NewsDetail() {
  const { newsId } = useParams();

  const fetchArticle = useCallback(async () => {
    const [article, assets] = await Promise.all([getNewsDetail(newsId), getAssets()]);
    const tickerByAssetId = Object.fromEntries(assets.map((a) => [a.asset_id, a.ticker]));
    return { article, tickerByAssetId };
  }, [newsId]);

  const { data, loading, error, refetch } = useApi(fetchArticle, [fetchArticle]);

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-16">
        <div className="skeleton h-72 rounded-2xl border border-border" />
      </div>
    );
  }

  if (error || !data?.article) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-16">
        <ErrorState message="Couldn't load this article." onRetry={refetch} />
      </div>
    );
  }

  const { article, tickerByAssetId } = data;
  const assetTickers = (article.extracted_assets || []).map(
    (entity) => tickerByAssetId[entity.asset_id] || entity.matched_text
  );

  return (
    <div className="mx-auto max-w-5xl px-6 pb-20 pt-8 sm:pt-12">
      <Link to="/news" className="text-sm text-text-muted transition-colors duration-200 hover:text-accent">
        ← Back to news
      </Link>

      <Thumbnail sentiment={article.sentiment} className="mt-6 h-72 w-full rounded-2xl border border-border" />

      <h1 className="mt-6 text-3xl font-bold leading-tight text-text sm:text-4xl">{article.title}</h1>
      <p className="mt-2 text-sm font-medium text-accent">{formatNewsTimestamp(article.created_at)}</p>

      <SentimentPill sentiment={article.sentiment} className="mt-3" />

      {assetTickers.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {assetTickers.map((ticker, i) => (
            <AssetTag key={`${ticker}-${i}`}>{ticker}</AssetTag>
          ))}
        </div>
      )}

      <div className="mt-8 grid grid-cols-1 gap-10 border-t border-border pt-8 lg:grid-cols-2">
        <p className="whitespace-pre-line text-base leading-relaxed text-text-muted">
          {article.summary || article.description || "No summary available."}
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ClassificationCard label="Category" value={article.category} />
          <ClassificationCard label="Impact" value={article.impact} />
          <ClassificationCard label="Sentiment" value={article.sentiment} />
          <ClassificationCard label="Target" value={article.target_investor} />
        </div>
      </div>
    </div>
  );
}
