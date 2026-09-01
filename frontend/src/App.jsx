import { Routes, Route } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import AssetsGrid from "./pages/AssetsGrid.jsx";
import NewsGrid from "./pages/NewsGrid.jsx";
import NewsDetail from "./pages/NewsDetail.jsx";
import CoinDetail from "./pages/CoinDetail.jsx";

export default function App() {
  return (
    <div className="ambient-glow min-h-screen">
      <Routes>
        <Route path="/" element={<Dashboard />}>
          <Route index element={<AssetsGrid />} />
          <Route path="news" element={<NewsGrid />} />
        </Route>
        <Route path="/coin/:assetId" element={<CoinDetail />} />
        <Route path="/news/:newsId" element={<NewsDetail />} />
      </Routes>
    </div>
  );
}
