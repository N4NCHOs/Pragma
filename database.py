import os
from sqlalchemy import create_engine, Column, Integer, Text, Boolean, String
from sqlalchemy.orm import declarative_base, sessionmaker
from pgvector.sqlalchemy import Vector

# ==========================================
# 1. Database Connection & ORM Setup
# ==========================================
# Format: postgresql://username:password@localhost:5432/database_name
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/crypto_news_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Define the SQLAlchemy Model matching our SQL schema
class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    url = Column(Text)
    is_redundant = Column(Boolean, default=False)
    novelty_label = Column(String(10), default="High")
    embedding = Column(Vector(384)) # 384-dimensional vector column

# Ensure tables are created
Base.metadata.create_all(bind=engine)