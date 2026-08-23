from database import SessionLocal, NewsArticle
from sqlalchemy import select

db = SessionLocal()
articles = db.execute(select(NewsArticle).order_by(NewsArticle.id)).scalars().all()

print(f"Total articles in DB: {len(articles)}")
print("\n--- HIGH NOVELTY (Unique) ---")
for a in articles:
    if not a.is_redundant:
        print(f"ID {a.id}: {a.title}")

print("\n--- LOW NOVELTY (Redundant) ---")
for a in articles:
    if a.is_redundant:
        print(f"ID {a.id}: {a.title}")
        
db.close()
