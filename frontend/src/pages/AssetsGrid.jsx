import { useCallback } from "react";
import useApi from "../hooks/useApi.js";
import { getAssets } from "../api/endpoints.js";
import AssetCard from "../components/AssetCard.jsx";
import LoadingState from "../components/LoadingState.jsx";
import ErrorState from "../components/ErrorState.jsx";

export default function AssetsGrid() {
  const fetchAssets = useCallback(() => getAssets(), []);
  const { data: assets, loading, error, refetch } = useApi(fetchAssets, [fetchAssets]);

  if (loading) return <LoadingState count={10} variant="asset" />;
  if (error) return <ErrorState message="Couldn't load assets." onRetry={refetch} />;

  return (
    <div className="grid grid-cols-2 gap-5 sm:grid-cols-3 lg:grid-cols-5">
      {assets.map((asset) => (
        <AssetCard key={asset.asset_id} asset={asset} />
      ))}
    </div>
  );
}
