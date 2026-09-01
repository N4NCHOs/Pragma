import { Link } from "react-router-dom";
import { getAssetVisual } from "../constants/assetVisuals.js";

export default function AssetCard({ asset }) {
  const { glyph, color } = getAssetVisual(asset.asset_id);
  const hasNews = asset.today_unique_count > 0;

  return (
    <Link
      to={`/coin/${asset.asset_id}`}
      className="animate-fade-in group flex flex-col justify-between rounded-2xl border border-border bg-surface p-5 backdrop-blur-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-accent/40 hover:bg-surface-hover"
    >
      <div className="flex items-center gap-3">
        <span
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-lg font-bold text-white shadow-sm transition-transform duration-200 group-hover:scale-105"
          style={{ backgroundColor: color }}
        >
          {glyph}
        </span>
        <div>
          <p className="text-base font-bold leading-tight">{asset.ticker}</p>
          <p className="text-sm text-accent">{asset.name.toLowerCase()}</p>
        </div>
      </div>

      <p className={`mt-6 text-right text-sm ${hasNews ? "text-text" : "text-text-faint"}`}>
        {hasNews ? `${asset.today_unique_count} news today` : "no news today"}
      </p>
    </Link>
  );
}
