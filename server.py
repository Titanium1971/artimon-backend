from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone

# Import blog API
from blog_api import blog_router, admin_router, reviews_router, set_database

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Try to import resend for email sending
try:
    import resend
    resend.api_key = os.environ.get('RESEND_API_KEY', '')
    RESEND_ENABLED = bool(resend.api_key)
except ImportError:
    RESEND_ENABLED = False
    logging.warning("Resend not installed. Email sending disabled.")

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

# Route to download the backend files for Railway deployment
@api_router.get("/download-backend")
async def download_backend_zip():
    file_path = ROOT_DIR / "static" / "artimon-backend-railway.zip"
    if not file_path.exists():
        return {"error": "File not found"}
    return FileResponse(
        path=str(file_path),
        filename="artimon-backend-railway.zip",
        media_type="application/zip"
    )

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

# Route to download backend update files for Render
@api_router.get("/download-render-update")
async def download_render_update():
    file_path = ROOT_DIR / "static" / "render-backend-update.zip"
    if file_path.exists():
        return FileResponse(
            path=str(file_path),
            filename="render-backend-update.zip",
            media_type="application/zip"
        )
    return {"error": "File not found"}

# ==================== CONTACT FORM EMAIL ====================

class ContactFormRequest(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    subject: str
    message: str

@api_router.post("/contact")
async def send_contact_email(request: ContactFormRequest):
    """Send contact form email via Resend"""
    
    RECIPIENT_EMAIL = "sebarilla@gmail.com"
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'contact@artimonbike.com')
    
    # Create HTML email content
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #f97316, #ea580c); padding: 20px; text-align: center;">
            <h1 style="color: white; margin: 0;">Nouveau message - Artimon Bike</h1>
        </div>
        <div style="padding: 30px; background: #f9fafb;">
            <h2 style="color: #111827; border-bottom: 2px solid #f97316; padding-bottom: 10px;">
                {request.subject}
            </h2>
            
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <tr>
                    <td style="padding: 10px; background: #fff; border: 1px solid #e5e7eb;"><strong>Nom:</strong></td>
                    <td style="padding: 10px; background: #fff; border: 1px solid #e5e7eb;">{request.name}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; background: #fff; border: 1px solid #e5e7eb;"><strong>Email:</strong></td>
                    <td style="padding: 10px; background: #fff; border: 1px solid #e5e7eb;">
                        <a href="mailto:{request.email}" style="color: #f97316;">{request.email}</a>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px; background: #fff; border: 1px solid #e5e7eb;"><strong>Téléphone:</strong></td>
                    <td style="padding: 10px; background: #fff; border: 1px solid #e5e7eb;">
                        {request.phone if request.phone else 'Non renseigné'}
                    </td>
                </tr>
            </table>
            
            <div style="background: white; padding: 20px; border-radius: 8px; border: 1px solid #e5e7eb;">
                <h3 style="color: #374151; margin-top: 0;">Message:</h3>
                <p style="color: #4b5563; line-height: 1.6; white-space: pre-wrap;">{request.message}</p>
            </div>
            
            <div style="margin-top: 20px; padding: 15px; background: #fef3c7; border-radius: 8px;">
                <p style="margin: 0; color: #92400e; font-size: 14px;">
                    💡 Répondez directement à cet email pour contacter {request.name}
                </p>
            </div>
        </div>
        <div style="background: #1f2937; padding: 15px; text-align: center;">
            <p style="color: #9ca3af; margin: 0; font-size: 12px;">
                Message envoyé depuis artimonbike.com
            </p>
        </div>
    </div>
    """
    
    if not RESEND_ENABLED:
        # Fallback: save to database if Resend not configured
        await db.contact_messages.insert_one({
            "name": request.name,
            "email": request.email,
            "phone": request.phone,
            "subject": request.subject,
            "message": request.message,
            "created_at": datetime.now(timezone.utc),
            "status": "pending"
        })
        return {
            "status": "saved",
            "message": "Message enregistré (email non configuré)"
        }
    
    try:
        params = {
            "from": SENDER_EMAIL,
            "to": [RECIPIENT_EMAIL],
            "reply_to": request.email,
            "subject": f"[Artimon Bike] {request.subject} - de {request.name}",
            "html": html_content
        }
        
        # Run sync SDK in thread to keep FastAPI non-blocking
        email_result = await asyncio.to_thread(resend.Emails.send, params)
        
        # Save to database for records
        await db.contact_messages.insert_one({
            "name": request.name,
            "email": request.email,
            "phone": request.phone,
            "subject": request.subject,
            "message": request.message,
            "created_at": datetime.now(timezone.utc),
            "status": "sent",
            "email_id": email_result.get("id")
        })
        
        return {
            "status": "success",
            "message": "Email envoyé avec succès"
        }
        
    except Exception as e:
        logging.error(f"Failed to send email: {str(e)}")
        # Save to database even if email fails
        await db.contact_messages.insert_one({
            "name": request.name,
            "email": request.email,
            "phone": request.phone,
            "subject": request.subject,
            "message": request.message,
            "created_at": datetime.now(timezone.utc),
            "status": "error",
            "error": str(e)
        })
        raise HTTPException(status_code=500, detail=f"Erreur d'envoi: {str(e)}")

# ==================== SECURE API KEYS ENDPOINT ====================
@api_router.get("/config/google-api-key")
async def get_google_api_key():
    """
    Secure endpoint to provide Google API key to frontend.
    This prevents the key from being exposed in client-side code.
    """
    api_key = os.environ.get('GOOGLE_API_KEY', '')
    if not api_key:
        raise HTTPException(status_code=500, detail="Google API key not configured")
    return {"key": api_key}

# ==================== ANALYTICS DASHBOARD ====================
@api_router.get("/analytics/stats")
async def get_analytics_stats():
    """Get analytics statistics for the admin dashboard"""
    from datetime import timedelta
    
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)
    
    # Contact messages stats
    total_contacts = await db.contact_messages.count_documents({})
    contacts_today = await db.contact_messages.count_documents({
        "created_at": {"$gte": today_start}
    })
    contacts_week = await db.contact_messages.count_documents({
        "created_at": {"$gte": week_start}
    })
    contacts_month = await db.contact_messages.count_documents({
        "created_at": {"$gte": month_start}
    })
    
    # Contact messages by status
    contacts_sent = await db.contact_messages.count_documents({"status": "sent"})
    contacts_pending = await db.contact_messages.count_documents({"status": "pending"})
    contacts_error = await db.contact_messages.count_documents({"status": "error"})
    
    # Blog articles stats
    total_articles = await db.articles.count_documents({})
    published_articles = await db.articles.count_documents({"status": "published"})
    draft_articles = await db.articles.count_documents({"status": "draft"})
    
    # Recent contact messages
    recent_contacts = await db.contact_messages.find(
        {}, 
        {"_id": 0, "name": 1, "email": 1, "subject": 1, "status": 1, "created_at": 1}
    ).sort("created_at", -1).limit(10).to_list(10)
    
    # Convert datetime to ISO string for JSON serialization
    for contact in recent_contacts:
        if contact.get("created_at"):
            contact["created_at"] = contact["created_at"].isoformat()
    
    # Contact messages by subject
    pipeline = [
        {"$group": {"_id": "$subject", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    subjects_stats = await db.contact_messages.aggregate(pipeline).to_list(10)
    
    return {
        "contacts": {
            "total": total_contacts,
            "today": contacts_today,
            "week": contacts_week,
            "month": contacts_month,
            "by_status": {
                "sent": contacts_sent,
                "pending": contacts_pending,
                "error": contacts_error
            },
            "by_subject": [{"subject": s["_id"], "count": s["count"]} for s in subjects_stats]
        },
        "articles": {
            "total": total_articles,
            "published": published_articles,
            "draft": draft_articles
        },
        "recent_contacts": recent_contacts
    }

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
app.include_router(reviews_router)

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
    
    # Initialize default reviews if they don't exist
    existing_reviews = await db.reviews.count_documents({})
    if existing_reviews == 0:
        default_reviews = [
            {
                "author_name": "Bernard T.",
                "rating": 5,
                "text": "Très bon accueil, équipe sympathique et prévenante. Les vélos sont en excellent état et bien entretenus. Sébastien nous a donné de super conseils pour notre balade autour de l'étang de Thau. Je recommande vivement !",
                "date": "Décembre 2024",
                "language": "fr",
                "source": "google",
                "highlight": "Accueil chaleureux et conseils personnalisés",
                "status": "published",
                "created_at": datetime.now(timezone.utc)
            },
            {
                "author_name": "Irene Lenherr",
                "rating": 5,
                "text": "Amazing service and the guy was super friendly and easy to communicate with. The bikes are in great condition. Highly recommend for exploring the area!",
                "date": "January 2025",
                "language": "en",
                "source": "lokki",
                "highlight": "Friendly service and great communication",
                "status": "published",
                "created_at": datetime.now(timezone.utc)
            },
            {
                "author_name": "Patrice H.",
                "rating": 5,
                "text": "Accueil au top ! Tout le matériel est fourni avec des conseils judicieux pour les balades. Les VTT sont en très bon état. Nous avons fait Marseillan-Plage jusqu'à Bouzigues, magnifique parcours. Merci pour cette belle expérience !",
                "date": "Novembre 2024",
                "language": "fr",
                "source": "google",
                "highlight": "Matériel de qualité et parcours conseillés",
                "status": "published",
                "created_at": datetime.now(timezone.utc)
            },
            {
                "author_name": "Chris Martin",
                "rating": 5,
                "text": "Fantastic place to hire a bike. Extremely flexible and great prices. Sebastian speaks very good English and gave us excellent route recommendations for the Canal du Midi.",
                "date": "December 2024",
                "language": "en",
                "source": "lokki",
                "highlight": "Flexible service and great prices",
                "status": "published",
                "created_at": datetime.now(timezone.utc)
            },
            {
                "author_name": "Marie-Claire D.",
                "rating": 5,
                "text": "Service impeccable ! Sébastien est un vrai professionnel, il a réparé ma crevaison en quelques minutes. Les tarifs sont raisonnables et le rapport qualité-prix est excellent. Une adresse incontournable à Marseillan !",
                "date": "Octobre 2024",
                "language": "fr",
                "source": "google",
                "highlight": "Réparation rapide et prix justes",
                "status": "published",
                "created_at": datetime.now(timezone.utc)
            },
            {
                "author_name": "Denis Desrosiers",
                "rating": 5,
                "text": "Excellent service when buying my bike. They let me test ride it all afternoon, cleaned it spotless after, and even added a free bottle holder. Can't ask for better service!",
                "date": "November 2024",
                "language": "en",
                "source": "lokki",
                "highlight": "Excellent after-sales service",
                "status": "published",
                "created_at": datetime.now(timezone.utc)
            }
        ]
        await db.reviews.insert_many(default_reviews)
        logger.info("Default reviews initialized")

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