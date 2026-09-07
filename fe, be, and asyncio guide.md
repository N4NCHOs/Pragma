## 3. Running the ingestion pipeline
 
Make sure the database container is running first (`docker start crypto_db`), then:
 
```bash
python main_pipeline.py --mode sequential
```
 
or, for concurrent AI inference (FLAN-T5 + DeBERTa run in parallel via `asyncio.gather` + `asyncio.to_thread`):
 
```bash
python main_pipeline.py --mode concurrent
```
 
Mode can also be set via environment variable (CLI flag takes precedence):
 
```bash
PIPELINE_INFERENCE_MODE=concurrent python main_pipeline.py
```
 
Default mode is `sequential` if nothing is specified.
 
Each run:
1. Scrapes the latest RSS articles (deduplicated against `output/rss_history.json`)
2. Filters for top-10 asset relevance
3. Runs novelty detection against existing DB rows
4. For unique articles: runs entity extraction, summarization, and classification
5. Persists every article (redundant or not) to PostgreSQL
To force a fresh scrape of currently-live RSS items (e.g. for testing), clear the scraper's local dedup history — **this does not touch the database**:
 
```bash
rm -f output/rss_history.json output/rss_temp.json output/scraped_news.json
```
 
To reset the database itself:
 
```sql
TRUNCATE TABLE news_articles RESTART IDENTITY;
```
 
---
 
## 4. Running the backend API
 
With the database container running:
 
```bash
uvicorn api:app --reload --port 8000
```
 
Interactive API docs (Swagger UI) are available at:
 
```
http://localhost:8000/docs
```
 
### Endpoints
 
| Method | Path | Description |
|---|---|---|
| GET | `/assets` | Fixed top-10 asset list with today's unique article count per asset |
| GET | `/assets/{asset_id}/news` | Unique articles mentioning a specific asset |
| GET | `/news` | Paginated list of latest unique articles |
| GET | `/news/{news_id}` | Full detail for one article (404s if redundant or not found) |
 
---
 
## 5. Running the frontend
 
```bash
cd frontend
npm install
npm run dev
```
 
Open:
 
```
http://localhost:5173
```
 
The frontend reads the API base URL from `frontend/.env`:
 
```
VITE_API_BASE_URL=http://localhost:8000
```
 
Both the backend (`:8000`) and frontend (`:5173`) need to be running simultaneously for the UI to load real data.
 
---
 
## 6. Full local run checklist
 
```bash
# 1. Database
docker start crypto_db
 
# 2. Ingestion pipeline (run whenever you want fresh data)
source venv/bin/activate
python main_pipeline.py --mode sequential
 
# 3. Backend (separate terminal)
source venv/bin/activate
uvicorn api:app --reload --port 8000
 
# 4. Frontend (separate terminal)
cd frontend
npm run dev
```
 
---
 
## Troubleshooting
 
**`ModuleNotFoundError` for any package** — confirm you're inside the activated venv (`which python` should point into `venv/`), then `pip install -r requirements.txt`.
 
**`psycopg2.OperationalError: connection to server ... failed`** — the Docker container isn't running. Run `docker start crypto_db`.
 
**Pipeline finds "0 articles to process"** — either the RSS feed has nothing new since your last run (nothing to fix, just wait or clear `output/rss_history.json` to force a re-fetch), or every fetched article was flagged as a novelty duplicate against existing DB rows.
 
**Frontend shows "couldn't load" / blank data** — check, in order: (1) `docker ps` shows `crypto_db` running, (2) `http://localhost:8000/docs` loads in a browser, (3) `curl http://localhost:8000/assets` returns JSON, (4) browser DevTools console/network tab for the actual fetch error, (5) `frontend/.env` has the correct `VITE_API_BASE_URL`.
 
**Torch install fails / wrong version resolved** — check your Python architecture (see Prerequisites note above). Intel (`x86_64`) macOS builds are limited to older PyTorch wheels; Apple Silicon (`arm64`) gets current releases.
 
---