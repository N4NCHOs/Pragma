from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from database import NewsArticle

# ==========================================
# 2. Load Model & Threshold Constants
# ==========================================
print("Loading all-MiniLM-L6-v2 model...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

# Threshold: Similarity > 0.8  ===>  Distance < 0.2
SIMILARITY_THRESHOLD_DISTANCE = 0.2

# ==========================================
# 3. Novelty Detection Core Function
# ==========================================
def process_incoming_news(news_data: dict, db_session):
    """
    Converts incoming news to vector, checks for redundancy, 
    and saves to DB with appropriate flags.
    """
    title = news_data.get("title", "")
    # Fallback order: full_body -> rss_summary -> description
    body = news_data.get("full_body") or news_data.get("rss_summary") or news_data.get("description") or ""
    full_text = f"{title}. {body}"

    
    # Generate 384-dim dense vector
    vector_list = embedding_model.encode(full_text).tolist()
    
    # Query database using pgvector's cosine_distance (<=>)
    # Checks if any existing article has a distance < 0.2
    query = select(NewsArticle).where(
        NewsArticle.embedding.cosine_distance(vector_list) < SIMILARITY_THRESHOLD_DISTANCE
    ).limit(1)
    
    existing_match = db_session.execute(query).scalar_one_or_none()
    
    if existing_match:
        print(f" [REDUNDANT] Similar to Article ID {existing_match.id}: '{existing_match.title[:40]}...'")
        is_redundant = True
        novelty_label = "Low"
    else:
        print(" [UNIQUE] High Novelty article detected! Ready for DeBERTa & FLAN-T5.")
        is_redundant = False
        novelty_label = "High"
        
    # Create DB entry
    new_article = NewsArticle(
        title=title,
        description=body,
        url=news_data.get("url"),
        is_redundant=is_redundant,
        novelty_label=novelty_label,
        embedding=vector_list
    )
    
    db_session.add(new_article)
    db_session.commit()
    db_session.refresh(new_article)
    
    return new_article