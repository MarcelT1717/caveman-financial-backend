from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId
import os
import base64

router = APIRouter(prefix="/api/articles", tags=["articles"])

# Get MongoDB database from server
def get_db():
    from server import db
    return db

class ArticleResponse(BaseModel):
    id: str
    title: str
    description: str
    category: str
    date: str
    pdf_filename: str
    pdf_url: str
    cover_image: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True

class ArticleCreate(BaseModel):
    title: str
    description: str
    category: str
    date: str
    pdf_data: str  # Base64 encoded PDF
    pdf_filename: str
    cover_image: Optional[str] = None

# Categories for articles
CATEGORIES = [
    "Weekly Newsletter",
    "Market Analysis",
    "Sector Deep Dive",
    "Stock Research",
    "Economic Update",
    "Special Report"
]

@router.get("/categories")
async def get_categories():
    """Get list of available categories"""
    return {"categories": CATEGORIES}

@router.get("/", response_model=List[ArticleResponse])
async def get_articles(category: Optional[str] = None, limit: int = 50):
    """Get all articles, optionally filtered by category"""
    db = get_db()
    
    query = {}
    if category:
        query["category"] = category
    
    # Exclude pdf_data from listing queries for better performance
    articles = await db.articles.find(query, {"pdf_data": 0}).sort("date", -1).limit(limit).to_list(length=limit)
    
    result = []
    for article in articles:
        result.append(ArticleResponse(
            id=str(article["_id"]),
            title=article["title"],
            description=article["description"],
            category=article["category"],
            date=article["date"],
            pdf_filename=article["pdf_filename"],
            pdf_url=article.get("pdf_url", ""),
            cover_image=article.get("cover_image"),
            created_at=article["created_at"].isoformat() if isinstance(article["created_at"], datetime) else article["created_at"]
        ))
    
    return result

@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(article_id: str):
    """Get a single article by ID"""
    db = get_db()
    
    try:
        article = await db.articles.find_one({"_id": ObjectId(article_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid article ID")
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    return ArticleResponse(
        id=str(article["_id"]),
        title=article["title"],
        description=article["description"],
        category=article["category"],
        date=article["date"],
        pdf_filename=article["pdf_filename"],
        pdf_url=article.get("pdf_url", ""),
        cover_image=article.get("cover_image"),
        created_at=article["created_at"].isoformat() if isinstance(article["created_at"], datetime) else article["created_at"]
    )

@router.post("/", response_model=ArticleResponse)
async def create_article(article: ArticleCreate):
    """Create a new article with PDF upload"""
    db = get_db()
    
    # Store PDF data directly in MongoDB (for simplicity)
    # In production, you'd upload to S3/cloud storage
    
    article_doc = {
        "title": article.title,
        "description": article.description,
        "category": article.category,
        "date": article.date,
        "pdf_filename": article.pdf_filename,
        "pdf_data": article.pdf_data,  # Base64 encoded
        "pdf_url": "",  # Will be set to API endpoint
        "cover_image": article.cover_image,
        "created_at": datetime.now(timezone.utc)
    }
    
    result = await db.articles.insert_one(article_doc)
    article_id = str(result.inserted_id)
    
    # Set the PDF URL to our API endpoint
    pdf_url = f"/api/articles/{article_id}/pdf"
    await db.articles.update_one(
        {"_id": result.inserted_id},
        {"$set": {"pdf_url": pdf_url}}
    )
    
    return ArticleResponse(
        id=article_id,
        title=article.title,
        description=article.description,
        category=article.category,
        date=article.date,
        pdf_filename=article.pdf_filename,
        pdf_url=pdf_url,
        cover_image=article.cover_image,
        created_at=article_doc["created_at"].isoformat()
    )

@router.get("/{article_id}/pdf")
async def get_article_pdf(article_id: str, download: bool = False):
    """Get the PDF file for an article"""
    from fastapi.responses import Response
    
    db = get_db()
    
    try:
        article = await db.articles.find_one({"_id": ObjectId(article_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid article ID")
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    if "pdf_data" not in article:
        raise HTTPException(status_code=404, detail="PDF not found")
    
    # Decode base64 PDF data
    try:
        pdf_bytes = base64.b64decode(article["pdf_data"])
    except Exception:
        raise HTTPException(status_code=500, detail="Error decoding PDF")
    
    # Use attachment for download, inline for viewing
    disposition = "attachment" if download else "inline"
    filename = article["pdf_filename"]
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff"
        }
    )

@router.delete("/{article_id}")
async def delete_article(article_id: str):
    """Delete an article"""
    db = get_db()
    
    try:
        result = await db.articles.delete_one({"_id": ObjectId(article_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid article ID")
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Article not found")
    
    return {"message": "Article deleted successfully"}

@router.put("/{article_id}", response_model=ArticleResponse)
async def update_article(article_id: str, article: ArticleCreate):
    """Update an existing article"""
    db = get_db()
    
    try:
        existing = await db.articles.find_one({"_id": ObjectId(article_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid article ID")
    
    if not existing:
        raise HTTPException(status_code=404, detail="Article not found")
    
    update_doc = {
        "title": article.title,
        "description": article.description,
        "category": article.category,
        "date": article.date,
        "pdf_filename": article.pdf_filename,
        "pdf_data": article.pdf_data,
        "cover_image": article.cover_image
    }
    
    await db.articles.update_one(
        {"_id": ObjectId(article_id)},
        {"$set": update_doc}
    )
    
    return ArticleResponse(
        id=article_id,
        title=article.title,
        description=article.description,
        category=article.category,
        date=article.date,
        pdf_filename=article.pdf_filename,
        pdf_url=f"/api/articles/{article_id}/pdf",
        cover_image=article.cover_image,
        created_at=existing["created_at"].isoformat() if isinstance(existing["created_at"], datetime) else existing["created_at"]
    )
