import apiClient from "./client.js";

/** GET /assets — top-10 asset list with today's unique-article counts. */
export async function getAssets() {
  const { data } = await apiClient.get("/assets");
  return data;
}

/** GET /assets/{assetId}/news — unique articles mentioning one asset. */
export async function getAssetNews(assetId) {
  const { data } = await apiClient.get(`/assets/${assetId}/news`);
  return data;
}

/** GET /news — paginated recent unique articles. */
export async function getNews({ skip = 0, limit = 30 } = {}) {
  const { data } = await apiClient.get("/news", { params: { skip, limit } });
  return data;
}

/** GET /news/{newsId} — full detail for one article. */
export async function getNewsDetail(newsId) {
  const { data } = await apiClient.get(`/news/${newsId}`);
  return data;
}
