"""FastAPI read layer for the crypto news pipeline's Postgres database.

Read-only: nothing here writes to news_articles. main_pipeline.py remains the
only writer. Reuses the engine/session/ORM model defined in database.py rather
than opening a second connection.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from database import NewsArticle, SessionLocal

# ==========================================
# Fixed top-10 asset catalog
# ==========================================
# Display metadata for the same top-10 assets ai_models/crypto_ner.py links
# entities to (ASSET_DICTIONARY there maps name/ticker variants -> asset_id;
# this is the one canonical display record per asset_id).
ASSET_CATALOG = [
    {"asset_id": "asset_btc", "name": "Bitcoin", "ticker": "BTC"},
    {"asset_id": "asset_eth", "name": "Ethereum", "ticker": "ETH"},
    {"asset_id": "asset_usdt", "name": "Tether", "ticker": "USDT"},
    {"asset_id": "asset_bnb", "name": "BNB", "ticker": "BNB"},
    {"asset_id": "asset_xrp", "name": "XRP", "ticker": "XRP"},
    {"asset_id": "asset_usdc", "name": "USD Coin", "ticker": "USDC"},
    {"asset_id": "asset_sol", "name": "Solana", "ticker": "SOL"},
    {"asset_id": "asset_trx", "name": "TRON", "ticker": "TRX"},
    {"asset_id": "asset_doge", "name": "Dogecoin", "ticker": "DOGE"},
    {"asset_id": "asset_hype", "name": "Hyperliquid", "ticker": "HYPE"},
]
ASSET_CATALOG_IDS = {asset["asset_id"] for asset in ASSET_CATALOG}

# Vite's default dev server port.
CORS_ORIGINS = [
    "http://localhost:5173",
]

app = FastAPI(title="Crypto News API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    """Per-request DB session, closed after the response is built."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================
# Response schemas
# ==========================================
class AssetSummary(BaseModel):
    asset_id: str
    name: str
    ticker: str
    today_unique_count: int


class NewsListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: Optional[str] = None
    sentiment: Optional[str] = None
    impact: Optional[str] = None
    novelty_label: Optional[str] = None
    created_at: Optional[datetime] = None


class NewsDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    impact: Optional[str] = None
    sentiment: Optional[str] = None
    target_investor: Optional[list] = None
    extracted_assets: Optional[list] = None
    novelty_label: Optional[str] = None
    created_at: Optional[datetime] = None


class PaginatedNews(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[NewsListItem]


def _today_start_utc() -> datetime:
    return datetime.combine(date.today(), time.min, tzinfo=timezone.utc)


# ==========================================
# Endpoints
# ==========================================
@app.get("/assets", response_model=list[AssetSummary])
def list_assets(db: Session = Depends(get_db)):
    """Fixed top-10 asset list, each with a count of today's unique articles."""

    today_start = _today_start_utc()
    summaries = []
    for asset in ASSET_CATALOG:
        count = (
            db.query(NewsArticle)
            .filter(
                NewsArticle.is_redundant.is_(False),
                NewsArticle.created_at >= today_start,
                NewsArticle.extracted_assets.contains([{"asset_id": asset["asset_id"]}]),
            )
            .count()
        )
        summaries.append(AssetSummary(**asset, today_unique_count=count))
    return summaries


@app.get("/assets/{asset_id}/news", response_model=list[NewsListItem])
def asset_news(asset_id: str, db: Session = Depends(get_db)):
    """All unique articles whose extracted_assets includes this asset_id."""

    if asset_id not in ASSET_CATALOG_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown asset_id '{asset_id}'")

    articles = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.is_redundant.is_(False),
            NewsArticle.extracted_assets.contains([{"asset_id": asset_id}]),
        )
        .order_by(NewsArticle.created_at.desc())
        .all()
    )
    return articles


@app.get("/news", response_model=PaginatedNews)
def list_news(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Most recent unique articles, paginated."""

    base_query = db.query(NewsArticle).filter(NewsArticle.is_redundant.is_(False))
    total = base_query.count()
    items = (
        base_query.order_by(NewsArticle.created_at.desc()).offset(skip).limit(limit).all()
    )
    return PaginatedNews(total=total, skip=skip, limit=limit, items=items)


@app.get("/news/{news_id}", response_model=NewsDetail)
def news_detail(news_id: int, db: Session = Depends(get_db)):
    """Full detail for one unique article. 404s on redundant articles too,
    for consistency with the list endpoints above, which only ever surface
    unique ones."""

    article = (
        db.query(NewsArticle)
        .filter(NewsArticle.id == news_id, NewsArticle.is_redundant.is_(False))
        .first()
    )
    if article is None:
        raise HTTPException(status_code=404, detail=f"No unique article with id {news_id}")
    return article
