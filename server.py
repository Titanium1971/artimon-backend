from fastapi import FastAPI, APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone

# Import blog API
from blog_api import blog_router, admin_router, set_database

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Set database for blog API
set_database(db)

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Route to download the ZIP file
@api_router.get("/download")
async def download_zip():
    file_path = ROOT_DIR / "static" / "artimon-deploy.zip"
    if file_path.exists():
        return FileResponse(
            path=str(file_path),
            filename="artimon-deploy.zip",
            media_type="application/zip"
        )
    return {"error": "File not found"}

# Route to download only the files to transfer
@api_router.get("/download-update")
async def download_update():
    file_path = ROOT_DIR / "static" / "transfer-files.zip"
    if file_path.exists():
        return FileResponse(
            path=str(file_path),
            filename="transfer-files.zip",
            media_type="application/zip"
        )
    return {"error": "File not found"}

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

# Include the router in the main app
app.include_router(api_router)

# Include blog routes
app.include_router(blog_router)
app.include_router(admin_router)

# Mount static files for uploads
uploads_dir = ROOT_DIR / "static" / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def init_blog_data():
    """Initialize default categories if they don't exist"""
    default_categories = [
        {"name": "Location", "slug": "location", "description": "Articles sur la location de vélos"},
        {"name": "Réparation", "slug": "reparation", "description": "Conseils de réparation et entretien"},
        {"name": "Parcours", "slug": "parcours", "description": "Itinéraires et balades à vélo"},
        {"name": "Conseils", "slug": "conseils", "description": "Conseils pratiques pour cyclistes"},
        {"name": "Actualités", "slug": "actualites", "description": "Actualités d'Artimon Bike"},
    ]
    
    for cat in default_categories:
        existing = await db.categories.find_one({"slug": cat["slug"]})
        if not existing:
            await db.categories.insert_one(cat)
    
    logger.info("Blog categories initialized")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

# Health check endpoint for Railway
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway deployment monitoring."""
    return {
        "status": "healthy",
        "service": "Artimon Bike Blog API",
        "version": "1.0.0"
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Artimon Bike Blog API",
        "version": "1.0.0",
        "docs": "/docs"
    }