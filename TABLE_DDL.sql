-- 1. Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create the news_articles table
CREATE TABLE news_articles (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    url TEXT,
    is_redundant BOOLEAN DEFAULT FALSE,
    novelty_label VARCHAR(10) DEFAULT 'High',
    -- 384 dimensions matches the output size of all-MiniLM-L6-v2
    embedding VECTOR(384), 
    extracted_assets JSONB,
    category VARCHAR(50),
    impact VARCHAR(20),
    sentiment VARCHAR(20),
    target_investor VARCHAR(50),
    summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Create an HNSW index for ultra-fast Cosine Distance searches
CREATE INDEX idx_news_embedding_hnsw 
ON news_articles 
USING hnsw (embedding vector_cosine_ops);

SELECT id, title, description, url, is_redundant, novelty_label, embedding, created_at
FROM public.news_articles;

SELECT *
FROM public.news_articles;

truncate table public.news_articles restart identity