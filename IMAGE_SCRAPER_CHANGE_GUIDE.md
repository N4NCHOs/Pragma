# Image Scraper Change Guide

Use these steps in order. The project stores an external image URL, not the image file.

## 1. `rss_scrape_scheduler.py`

Ensure these imports already include `Any` and `urlsplit`:

```python
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
```

### A. Add the image helper

Initial:

```python
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def utc_now() -> str:
```

Change to:

```python
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def extract_rss_image_url(entry: dict[str, Any]) -> str | None:
    """Return the first valid image URL provided by the RSS entry."""

    for media_item in entry.get("media_content", []):
        image_url = str(media_item.get("url") or "").strip()
        parsed_url = urlsplit(image_url)

        if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
            return image_url

    return None


def utc_now() -> str:
```

### B. Add the URL to every RSS article

Initial:

```python
for entry in feed.entries[:limit]:
    url = entry.get("link", "").strip()
    guid = str(entry.get("id") or url).strip()
    if not guid and not url:
        continue
```

Change to:

```python
for entry in feed.entries[:limit]:
    url = entry.get("link", "").strip()
    guid = str(entry.get("id") or url).strip()
    image_url = extract_rss_image_url(entry)
    if not guid and not url:
        continue
```

Initial article dictionary:

```python
"rss_summary": entry.get("summary", "").strip(),
"url": url,
"published_at": entry.get("published", ""),
```

Final article dictionary:

```python
"rss_summary": entry.get("summary", "").strip(),
"url": url,
"image_url": image_url,
"published_at": entry.get("published", ""),
```

## 2. `TABLE_DDL.sql`

Initial:

```sql
description TEXT,
url TEXT,
is_redundant BOOLEAN DEFAULT FALSE,
```

Change to:

```sql
description TEXT,
url TEXT,
image_url TEXT,
is_redundant BOOLEAN DEFAULT FALSE,
```

This updates the definition used when creating a new database.

## 3. Existing PostgreSQL database

For a table that already exists, run this once in DBeaver:

```sql
ALTER TABLE public.news_articles
ADD COLUMN IF NOT EXISTS image_url TEXT;
```

Check the result:

```sql
SELECT id, title, image_url
FROM public.news_articles;
```

You do not need to rebuild the Docker container.

## 4. `database.py`

Initial:

```python
description = Column(Text)
url = Column(Text)
is_redundant = Column(Boolean, default=False)
```

Change to:

```python
description = Column(Text)
url = Column(Text)
image_url = Column(Text, nullable=True)
is_redundant = Column(Boolean, default=False)
```

This maps `NewsArticle.image_url` to the PostgreSQL column.

## 5. `ai_models/novelty_detection.py`

Initial:

```python
new_article = NewsArticle(
    title=title,
    description=body,
    url=news_data.get("url"),
    is_redundant=is_redundant,
```

Change to:

```python
new_article = NewsArticle(
    title=title,
    description=body,
    url=news_data.get("url"),
    image_url=news_data.get("image_url"),
    is_redundant=is_redundant,
```

This only carries the URL into the database object. The image is not used to calculate novelty.

## 6. `api.py`

### `NewsListItem`

Initial:

```python
id: int
title: str
summary: Optional[str] = None
```

Change to:

```python
id: int
title: str
image_url: Optional[str] = None
summary: Optional[str] = None
```

### `NewsDetail`

Initial:

```python
description: Optional[str] = None
url: Optional[str] = None
summary: Optional[str] = None
```

Change to:

```python
description: Optional[str] = None
url: Optional[str] = None
image_url: Optional[str] = None
summary: Optional[str] = None
```

The existing API queries will now include `image_url` automatically.

## 7. `frontend/src/components/Thumbnail.jsx`

Initial function:

```jsx
export default function Thumbnail({ sentiment, className = "" }) {
```

Change to:

```jsx
export default function Thumbnail({ imageUrl, sentiment, className = "" }) {
```

Inside the main `<div>`, place this block immediately before the existing `<svg>`:

```jsx
{imageUrl && (
  <img
    src={imageUrl}
    alt=""
    loading="lazy"
    className="absolute inset-0 h-full w-full object-cover"
    onError={(event) => {
      event.currentTarget.style.display = "none";
    }}
  />
)}
```

Final structure:

```jsx
export default function Thumbnail({ imageUrl, sentiment, className = "" }) {
  const tint = SENTIMENT_TINTS[sentiment] || "#6b718233";

  return (
    <div
      className={`relative overflow-hidden bg-surface-solid ${className}`}
      style={{
        backgroundImage: `linear-gradient(135deg, ${tint}, transparent 65%)`,
      }}
    >
      {imageUrl && (
        <img
          src={imageUrl}
          alt=""
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
          onError={(event) => {
            event.currentTarget.style.display = "none";
          }}
        />
      )}

      {/* Keep the existing SVG here as the fallback. */}
    </div>
  );
}
```

## 8. `frontend/src/components/NewsCard.jsx`

Initial:

```jsx
<Thumbnail sentiment={article.sentiment} className="h-40 w-full" />
```

Change to:

```jsx
<Thumbnail
  imageUrl={article.image_url}
  sentiment={article.sentiment}
  className="h-40 w-full"
/>
```

## 9. `frontend/src/pages/NewsDetail.jsx`

Initial:

```jsx
<Thumbnail
  sentiment={article.sentiment}
  className="mt-6 h-72 w-full rounded-2xl border border-border"
/>
```

Change to:

```jsx
<Thumbnail
  imageUrl={article.image_url}
  sentiment={article.sentiment}
  className="mt-6 h-72 w-full rounded-2xl border border-border"
/>
```

## 10. `main_pipeline.py`

No image-specific code change is required. Keep the existing save code:

```python
db.add(uncommitted_article)
db.commit()
db.refresh(uncommitted_article)
```

Because `image_url` is already inside `uncommitted_article`, the normal commit saves it.

## 11. Quick test

Run the complete pipeline:

```bash
docker start crypto_db
source .venv/bin/activate
python main_pipeline.py
```

Then check PostgreSQL:

```sql
SELECT id, title, image_url
FROM public.news_articles
ORDER BY id DESC;
```

Run the API:

```bash
uvicorn api:app --reload
```

Open `http://localhost:8000/docs`, call `GET /news`, and confirm that `image_url` appears in the response.
