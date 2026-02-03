"""
Blog API - Complete blog system with admin dashboard
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId
import uuid
import os
import re
import hashlib
import secrets
from pathlib import Path

# Create router
blog_router = APIRouter(prefix="/api/blog", tags=["blog"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

# Security
security = HTTPBearer(auto_error=False)

# Admin credentials (in production, use environment variables)
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@artimonbike.com")
ADMIN_PASSWORD_HASH = hashlib.sha256(os.environ.get("ADMIN_PASSWORD", "ArtimonBike2025!").encode()).hexdigest()

# Token storage (in production, use Redis or database)
valid_tokens = {}

# Database reference (will be set by server.py)
db = None

def set_database(database):
    global db
    db = database

# ==================== MODELS ====================

class ArticleBase(BaseModel):
    title: str
    content: str
    excerpt: str
    image_url: Optional[str] = None
    category: str
    tags: List[str] = []
    meta_description: Optional[str] = None
    status: str = "draft"  # draft or published

class ArticleCreate(ArticleBase):
    pass

class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    excerpt: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    meta_description: Optional[str] = None
    status: Optional[str] = None

class ArticleResponse(ArticleBase):
    id: str
    slug: str
    created_at: datetime
    updated_at: datetime
    
class CategoryBase(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    message: str

# ==================== HELPERS ====================

def generate_slug(title: str) -> str:
    """Generate URL-friendly slug from title"""
    slug = title.lower()
    slug = re.sub(r'[àáâãäå]', 'a', slug)
    slug = re.sub(r'[èéêë]', 'e', slug)
    slug = re.sub(r'[ìíîï]', 'i', slug)
    slug = re.sub(r'[òóôõö]', 'o', slug)
    slug = re.sub(r'[ùúûü]', 'u', slug)
    slug = re.sub(r'[ç]', 'c', slug)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug

def serialize_article(article: dict) -> dict:
    """Convert MongoDB document to response format"""
    return {
        "id": str(article["_id"]),
        "title": article["title"],
        "slug": article["slug"],
        "content": article["content"],
        "excerpt": article["excerpt"],
        "image_url": article.get("image_url"),
        "category": article["category"],
        "tags": article.get("tags", []),
        "meta_description": article.get("meta_description"),
        "status": article["status"],
        "created_at": article["created_at"],
        "updated_at": article["updated_at"]
    }

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify admin token"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Token manquant")
    
    token = credentials.credentials
    if token not in valid_tokens:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")
    
    # Check token expiration (24 hours)
    token_data = valid_tokens[token]
    if (datetime.now(timezone.utc) - token_data["created_at"]).total_seconds() > 86400:
        del valid_tokens[token]
        raise HTTPException(status_code=401, detail="Token expiré")
    
    return token_data

# ==================== PUBLIC BLOG ROUTES ====================

@blog_router.get("/articles")
async def get_published_articles(
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
):
    """Get all published articles"""
    query = {"status": "published"}
    if category:
        query["category"] = category
    
    cursor = db.articles.find(query).sort("created_at", -1).skip(offset).limit(limit)
    articles = await cursor.to_list(length=limit)
    
    total = await db.articles.count_documents(query)
    
    return {
        "articles": [serialize_article(a) for a in articles],
        "total": total,
        "limit": limit,
        "offset": offset
    }

@blog_router.get("/articles/{slug}")
async def get_article_by_slug(slug: str):
    """Get single article by slug"""
    article = await db.articles.find_one({"slug": slug, "status": "published"})
    if not article:
        raise HTTPException(status_code=404, detail="Article non trouvé")
    
    return serialize_article(article)

@blog_router.get("/categories")
async def get_categories():
    """Get all categories"""
    cursor = db.categories.find({})
    categories = await cursor.to_list(length=100)
    
    # Count articles per category
    result = []
    for cat in categories:
        count = await db.articles.count_documents({"category": cat["slug"], "status": "published"})
        result.append({
            "id": str(cat["_id"]),
            "name": cat["name"],
            "slug": cat["slug"],
            "description": cat.get("description"),
            "article_count": count
        })
    
    return result

@blog_router.get("/recent")
async def get_recent_articles(limit: int = 5):
    """Get most recent published articles"""
    cursor = db.articles.find({"status": "published"}).sort("created_at", -1).limit(limit)
    articles = await cursor.to_list(length=limit)
    return [serialize_article(a) for a in articles]

# ==================== ADMIN ROUTES ====================

@admin_router.post("/login", response_model=LoginResponse)
async def admin_login(request: LoginRequest):
    """Admin login"""
    password_hash = hashlib.sha256(request.password.encode()).hexdigest()
    
    if request.email != ADMIN_EMAIL or password_hash != ADMIN_PASSWORD_HASH:
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    # Generate token
    token = secrets.token_urlsafe(32)
    valid_tokens[token] = {
        "email": request.email,
        "created_at": datetime.now(timezone.utc)
    }
    
    return LoginResponse(token=token, message="Connexion réussie")

@admin_router.get("/verify")
async def verify_admin(token_data: dict = Depends(verify_token)):
    """Verify admin token is valid"""
    return {"valid": True, "email": token_data["email"]}

@admin_router.get("/articles")
async def admin_get_all_articles(
    status: Optional[str] = None,
    token_data: dict = Depends(verify_token)
):
    """Get all articles (including drafts) for admin"""
    query = {}
    if status:
        query["status"] = status
    
    cursor = db.articles.find(query).sort("updated_at", -1)
    articles = await cursor.to_list(length=1000)
    
    return [serialize_article(a) for a in articles]

@admin_router.get("/articles/{article_id}")
async def admin_get_article(article_id: str, token_data: dict = Depends(verify_token)):
    """Get single article by ID for editing"""
    try:
        article = await db.articles.find_one({"_id": ObjectId(article_id)})
    except:
        raise HTTPException(status_code=400, detail="ID invalide")
    
    if not article:
        raise HTTPException(status_code=404, detail="Article non trouvé")
    
    return serialize_article(article)

@admin_router.post("/articles")
async def create_article(article: ArticleCreate, token_data: dict = Depends(verify_token)):
    """Create new article"""
    slug = generate_slug(article.title)
    
    # Check if slug already exists
    existing = await db.articles.find_one({"slug": slug})
    if existing:
        slug = f"{slug}-{str(uuid.uuid4())[:8]}"
    
    now = datetime.now(timezone.utc)
    article_doc = {
        **article.model_dump(),
        "slug": slug,
        "created_at": now,
        "updated_at": now
    }
    
    result = await db.articles.insert_one(article_doc)
    article_doc["_id"] = result.inserted_id
    
    return serialize_article(article_doc)

@admin_router.put("/articles/{article_id}")
async def update_article(
    article_id: str,
    article: ArticleUpdate,
    token_data: dict = Depends(verify_token)
):
    """Update existing article"""
    try:
        existing = await db.articles.find_one({"_id": ObjectId(article_id)})
    except:
        raise HTTPException(status_code=400, detail="ID invalide")
    
    if not existing:
        raise HTTPException(status_code=404, detail="Article non trouvé")
    
    update_data = {k: v for k, v in article.model_dump().items() if v is not None}
    
    # Update slug if title changed
    if "title" in update_data:
        update_data["slug"] = generate_slug(update_data["title"])
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await db.articles.update_one(
        {"_id": ObjectId(article_id)},
        {"$set": update_data}
    )
    
    updated = await db.articles.find_one({"_id": ObjectId(article_id)})
    return serialize_article(updated)

@admin_router.delete("/articles/{article_id}")
async def delete_article(article_id: str, token_data: dict = Depends(verify_token)):
    """Delete article"""
    try:
        result = await db.articles.delete_one({"_id": ObjectId(article_id)})
    except:
        raise HTTPException(status_code=400, detail="ID invalide")
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Article non trouvé")
    
    return {"message": "Article supprimé"}

@admin_router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    token_data: dict = Depends(verify_token)
):
    """Upload image for article"""
    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Type de fichier non autorisé")
    
    # Generate unique filename
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    
    # Save file
    upload_dir = Path(__file__).parent / "static" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / filename
    content = await file.read()
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Return URL (relative path)
    return {"url": f"/api/uploads/{filename}", "filename": filename}

# ==================== CATEGORY MANAGEMENT ====================

@admin_router.get("/categories")
async def admin_get_categories(token_data: dict = Depends(verify_token)):
    """Get all categories for admin"""
    cursor = db.categories.find({})
    categories = await cursor.to_list(length=100)
    return [{
        "id": str(cat["_id"]),
        "name": cat["name"],
        "slug": cat["slug"],
        "description": cat.get("description")
    } for cat in categories]

@admin_router.post("/categories")
async def create_category(category: CategoryBase, token_data: dict = Depends(verify_token)):
    """Create new category"""
    existing = await db.categories.find_one({"slug": category.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Cette catégorie existe déjà")
    
    result = await db.categories.insert_one(category.model_dump())
    return {"id": str(result.inserted_id), **category.model_dump()}

@admin_router.delete("/categories/{category_id}")
async def delete_category(category_id: str, token_data: dict = Depends(verify_token)):
    """Delete category"""
    try:
        result = await db.categories.delete_one({"_id": ObjectId(category_id)})
    except:
        raise HTTPException(status_code=400, detail="ID invalide")
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Catégorie non trouvée")
    
    return {"message": "Catégorie supprimée"}

# ==================== STATS ====================

@admin_router.get("/stats")
async def get_stats(token_data: dict = Depends(verify_token)):
    """Get blog statistics"""
    total_articles = await db.articles.count_documents({})
    published = await db.articles.count_documents({"status": "published"})
    drafts = await db.articles.count_documents({"status": "draft"})
    categories = await db.categories.count_documents({})
    
    return {
        "total_articles": total_articles,
        "published": published,
        "drafts": drafts,
        "categories": categories
    }
