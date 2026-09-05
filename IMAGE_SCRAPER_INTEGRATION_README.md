# CoinDesk RSS Image URL Integration

This document explains the image-related changes made to the crypto news project. It is intended as a handoff guide so another developer can understand, run, test, and continue the implementation.

## 1. What changed

The pipeline now reads an article image URL from CoinDesk's RSS metadata, keeps it with the article throughout processing, stores it in PostgreSQL, returns it through FastAPI, and displays it in the React frontend.

Only the image URL is stored. The project does **not** download or store the image file itself.

```text
CoinDesk RSS media:content
          |
          v
rss_scrape_scheduler.py
          |
          v
output/scraped_news.json
          |
          v
novelty_detection.py creates NewsArticle
          |
          v
main_pipeline.py commits the article
          |
          v
PostgreSQL news_articles.image_url
          |
          v
FastAPI response: image_url
          |
          v
Thumbnail.jsx displays the image
```

This change does not alter FLAN-T5, cryptoNER, DeBERTa, asset filtering, or the novelty similarity calculation.

## 2. Files changed

| File | Change | Purpose |
| --- | --- | --- |
| `rss_scrape_scheduler.py` | Extracts and validates `media_content[].url`, then adds `image_url` to the article dictionary | Gets the image URL from the RSS feed |
| `TABLE_DDL.sql` | Adds `image_url TEXT` to the table definition | Keeps new database installations consistent |
| `database.py` | Adds `image_url = Column(Text, nullable=True)` to `NewsArticle` | Maps the Python ORM object to the PostgreSQL column |
| `ai_models/novelty_detection.py` | Copies `news_data["image_url"]` into the new `NewsArticle` object | Prevents the image URL from being lost before database insertion |
| `api.py` | Adds `image_url` to list and detail response models | Makes the URL available to the frontend |
| `frontend/src/components/Thumbnail.jsx` | Accepts `imageUrl` and renders an `<img>` when available | Displays the real article image and keeps the existing illustration as fallback |
| `frontend/src/components/NewsCard.jsx` | Passes `article.image_url` to `Thumbnail` | Displays images in news cards |
| `frontend/src/pages/NewsDetail.jsx` | Passes `article.image_url` to `Thumbnail` | Displays the image on the news detail page |

`main_pipeline.py` did not require an image-specific modification. Its existing database commit already persists every mapped field on the `NewsArticle` object.

No new Python dependency was required. The existing `feedparser` package already converts the RSS `<media:content>` element into `entry["media_content"]`.

## 3. RSS scraper changes

The scraper now contains this helper:

```python
def extract_rss_image_url(entry: dict[str, Any]) -> str | None:
    """Return the first valid image URL provided by the RSS entry."""

    for media_item in entry.get("media_content", []):
        image_url = str(media_item.get("url") or "").strip()
        parsed_url = urlsplit(image_url)

        if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
            return image_url

    return None
```

For every RSS entry, `fetch_latest_rss()` calls the helper and adds the result to the normalized article dictionary:

```python
image_url = extract_rss_image_url(entry)

article = {
    # existing fields...
    "image_url": image_url,
}
```

The URL is accepted only when it has an `http` or `https` scheme and a hostname. If CoinDesk does not provide an image, the value is `null` in JSON and later becomes `NULL` in PostgreSQL.

`scrape_article()` starts with a copy of the RSS article dictionary, so `image_url` automatically remains present after the full article body is scraped. It also remains present if body extraction fails.

Example normalized article data:

```json
{
  "guid": "example-guid",
  "title": "Example crypto news title",
  "url": "https://www.coindesk.com/example",
  "image_url": "https://cdn.sanity.io/images/example.jpg",
  "full_body": "The complete extracted article text...",
  "scrape_status": "success"
}
```

## 4. PostgreSQL changes

The `news_articles` table uses a nullable `TEXT` column:

```sql
image_url TEXT
```

It is nullable because:

- not every RSS item has an image;
- older rows were created before image support existed;
- a missing image should not prevent the article from being saved.

### Existing database migration

Editing `TABLE_DDL.sql` does not change a table that already exists. Run this migration once in DBeaver for an existing database:

```sql
ALTER TABLE public.news_articles
ADD COLUMN IF NOT EXISTS image_url TEXT;
```

Verify the column:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'news_articles'
  AND column_name = 'image_url';
```

Expected result:

| column_name | data_type | is_nullable |
| --- | --- | --- |
| image_url | text | YES |

Do not rerun the complete `TABLE_DDL.sql` against an important database without reviewing it first. The current file also contains a `TRUNCATE` statement that can remove table data.

### Docker

No Docker image rebuild or container replacement is needed. The PostgreSQL container stores the database; the `ALTER TABLE` command changes the database inside that existing container.

Initial container command used by this project:

```bash
docker run --name crypto_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=crypto_news_db \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

For later runs, start the existing container:

```bash
docker start crypto_db
```

## 5. SQLAlchemy and database insertion

`database.py` maps the PostgreSQL column to the Python `NewsArticle` model:

```python
image_url = Column(Text, nullable=True)
```

`ai_models/novelty_detection.py` creates the ORM object and copies the URL into it:

```python
new_article = NewsArticle(
    # existing fields...
    image_url=news_data.get("image_url"),
)
```

The image has no role in the novelty decision. Novelty detection still uses text embeddings. This file needs the image assignment only because it is the place where the scraped dictionary is converted into the database object.

`main_pipeline.py` then uses its existing transaction code:

```python
db.add(uncommitted_article)
db.commit()
db.refresh(uncommitted_article)
```

- `db.add(...)` attaches the new Python object to the active SQLAlchemy session.
- `db.commit()` sends the insert to PostgreSQL and permanently commits the transaction.
- `db.refresh(...)` reloads the row so generated database values such as `id` and `created_at` are available on the object.

Because `image_url` is already on the mapped object, it is included in the same insert. A separate image query is not needed.

## 6. Relationship with novelty detection

The image URL travels through novelty detection, but it is **not evaluated by novelty detection**.

```text
title + article body ---> embedding ---> unique/redundant decision

image_url -----------> copied unchanged ---> database record
```

Both unique and redundant articles can be stored with an image URL. The current public API only returns unique articles because its queries contain:

```python
NewsArticle.is_redundant.is_(False)
```

Therefore, an image belonging to a redundant record can exist in PostgreSQL without appearing in the frontend.

## 7. API changes

`api.py` now declares the field in both response types:

```python
class NewsListItem(BaseModel):
    image_url: Optional[str] = None

class NewsDetail(BaseModel):
    image_url: Optional[str] = None
```

The following endpoints can now include `image_url`:

- `GET /news`
- `GET /assets/{asset_id}/news`
- `GET /news/{news_id}`

The API does not scrape or save images. It reads the URL already stored in PostgreSQL and serializes it into JSON.

Example API response field:

```json
{
  "id": 1,
  "title": "Example article",
  "image_url": "https://cdn.sanity.io/images/example.jpg"
}
```

## 8. Frontend changes

The `Thumbnail` component accepts the new prop:

```jsx
<Thumbnail
  imageUrl={article.image_url}
  sentiment={article.sentiment}
/>
```

When the URL exists, `Thumbnail.jsx` renders the image with `object-cover`, which fills the thumbnail area without stretching its aspect ratio. `loading="lazy"` delays off-screen downloads.

If the field is missing or the remote image fails to load, the `<img>` is hidden and the existing sentiment-based illustration remains visible as a fallback. A broken image does not break the news card or detail page.

## 9. Recommended run sequence

### Run the complete pipeline

From the project root:

```bash
docker start crypto_db
source .venv/bin/activate
python main_pipeline.py
```

`main_pipeline.py` already calls the RSS scheduler, processes new articles, and saves them. For a normal complete run, do not run `rss_scrape_scheduler.py` immediately beforehand.

Why: the scraper advances `output/rss_history.json`. If the standalone scraper is run first and the pipeline is run immediately afterward, the second scrape may find zero new articles and replace `output/scraped_news.json` with `[]`.

### Run only the scraper for inspection

```bash
source .venv/bin/activate
python rss_scrape_scheduler.py
```

Then inspect:

- `output/rss_temp.json`: current RSS snapshot;
- `output/scraped_news.json`: only articles considered new in that run;
- `output/rss_history.json`: snapshot used by the next run.

### Run the API

```bash
source .venv/bin/activate
uvicorn api:app --reload
```

Open `http://localhost:8000/docs` to inspect and call the API endpoints.

Start the frontend using its normal development command once its package manifest and dependencies are available. The current shared repository does not contain a `package.json`, so this document does not assume a specific frontend command.

## 10. Verification checklist

### A. Check scraper output

Open `output/scraped_news.json` and confirm an article has:

```json
"image_url": "https://..."
```

`"image_url": null` is valid for a feed item without image metadata.

### B. Check PostgreSQL

After running the complete pipeline:

```sql
SELECT id, title, image_url, is_redundant
FROM public.news_articles
ORDER BY id DESC;
```

### C. Check FastAPI

Open `GET /news` in the Swagger page and confirm each returned item contains `image_url`, either as a URL or `null`.

### D. Check the frontend

- A valid `image_url` should display a CoinDesk article image.
- A missing or broken URL should display the existing fallback thumbnail.
- Check both a news card and the news detail page.

## 11. Error and fallback behavior

| Situation | Result |
| --- | --- |
| RSS entry contains a valid HTTP(S) image | URL is kept throughout the pipeline |
| RSS entry contains no `media_content` | `image_url` becomes `null` |
| RSS entry contains an invalid/non-HTTP URL | URL is rejected and the value becomes `null` |
| Full article body scraping fails | RSS image URL is still retained |
| Database column was not migrated | Database insertion/query can fail because the ORM expects `image_url` |
| Remote image later becomes unavailable | Frontend hides the failed image and shows its fallback |
| Article is classified as redundant | Record may be stored, but current API does not return it |

## 12. Current limitations

- The implementation uses only CoinDesk RSS `media:content`; it does not scrape Open Graph or Twitter image metadata from article pages.
- The system stores an external URL, not a local image. CoinDesk may change or remove that URL later.
- Existing database rows are not automatically backfilled.
- Image similarity is not part of novelty detection.
- `scraped_news.json` contains only the current batch and is reset on every scraper run.
- The project does not currently use a formal migration tool such as Alembic, so the one-time `ALTER TABLE` must be run manually on every existing database environment.
- When last checked, 23 of 25 current RSS entries provided an image URL. The number can change with the feed.

Before using external images in a public or production product, confirm that displaying the source's hosted images is permitted by its terms and preferred attribution policy.

## 13. Handoff checklist for another developer

1. Pull the updated source code.
2. Start the existing `crypto_db` Docker container.
3. Run the one-time `ALTER TABLE` migration in DBeaver.
4. Install the project's existing requirements if needed.
5. Run `python main_pipeline.py` when new RSS articles are available.
6. Verify `image_url` in PostgreSQL.
7. Start FastAPI and verify the field in `/docs`.
8. Start the frontend and check both card and detail thumbnails.

At the time of this handoff, RSS-to-JSON image extraction has been observed working, and the Python files pass syntax compilation. The database column exists, but a complete database-to-browser test still requires processing at least one new article because the current `news_articles` table is empty.
