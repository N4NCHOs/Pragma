import { Link } from "react-router-dom";
import Thumbnail from "./Thumbnail.jsx";
import SentimentPill from "./SentimentPill.jsx";
import { formatNewsDate } from "../utils/formatDate.js";

export default function NewsCard({ article }) {
  return (
    <Link
      to={`/news/${article.id}`}
      className="animate-fade-in group flex flex-col overflow-hidden rounded-2xl border border-border bg-surface-solid transition-all duration-200 hover:-translate-y-0.5 hover:border-accent/40"
    >
      <Thumbnail sentiment={article.sentiment} className="h-40 w-full" />
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-text transition-colors duration-200 group-hover:text-accent">
          {article.title}
        </h3>
        <p className="text-xs font-medium text-accent">{formatNewsDate(article.created_at)}</p>
        <SentimentPill sentiment={article.sentiment} className="mt-auto" />
      </div>
    </Link>
  );
}
