from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from typing import List
from sqlalchemy.orm import Session
from .email_database import SessionLocal, engine
from .email_models import Base, Email
from .email_schema import EmailCreate, EmailOut
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import random
import os
from dotenv import load_dotenv


app = FastAPI(title="Email Simulation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_THIS_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _THIS_DIR / "templates"
_REPO_ROOT = _THIS_DIR.parent
_STATIC_CANDIDATES = [
    _THIS_DIR / "static",
    _REPO_ROOT / "static",
]

for _static_dir in _STATIC_CANDIDATES:
    if _static_dir.exists() and _static_dir.is_dir():
        app.mount(
            "/static",
            StaticFiles(directory=str(_static_dir)),
            name="static"
        )
        break

_UI_CANDIDATES = [
    _REPO_ROOT / "ui_all.html",
    _THIS_DIR / "templates" / "ui_all.html",
]

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    load_dotenv()

    ui_email_server = os.getenv(
        "EMAIL_SERVER_API_URL",
        "http://127.0.0.1:8000"
    )

    ui_llm_server = os.getenv("LLM_SERVER", "http://127.0.0.1:8001")

    return templates.TemplateResponse(
        request=request,
        name="ui_all.html",
        context={
            "UI_EMAIL_SERVER": ui_email_server,
            "UI_LLM_SERVER": ui_llm_server,
        },
    )


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/send", response_model=EmailOut)
def send_email(email: EmailCreate, db: Session = Depends(get_db)):
    """Send a new email"""
    new_email = Email(
        recipient=email.recipient,
        subject=email.subject,
        body=email.body,
        sender="you@mail.com",
    )
    db.add(new_email)
    db.commit()
    db.refresh(new_email)
    return new_email


@app.get("/emails", response_model=List[EmailOut])
def list_emails(db: Session = Depends(get_db)):
    """Get all emails ordered by timestamp (newest first)"""
    return db.query(Email).order_by(Email.timestamp.desc()).all()


@app.get("/emails/search", response_model=List[EmailOut])
def search_emails(
    q: str = Query(..., description="Keyword to search in subject/body/sender"),
    db: Session = Depends(get_db),
):
    """Search emails by keyword in subject, body, or sender"""
    return db.query(Email).filter(
        (Email.subject.ilike(f"%{q}%")) |
        (Email.body.ilike(f"%{q}%")) |
        (Email.sender.ilike(f"%{q}%"))
    ).order_by(Email.timestamp.desc()).all()


@app.get("/emails/filter", response_model=List[EmailOut])
def filter_emails(
    recipient: str | None = Query(None, description="Recipient email address (optional)"),
    date_from: str | None = Query(None, description="Start date YYYY-MM-DD (optional)"),
    date_to: str | None = Query(None, description="End date YYYY-MM-DD (optional)"),
    db: Session = Depends(get_db),
):
    """Filter emails by recipient and/or date range"""
    query = db.query(Email)

    if recipient:
        query = query.filter(Email.recipient == recipient)

    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Email.timestamp >= date_from_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD")

    if date_to:
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            query = query.filter(Email.timestamp <= date_to_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use YYYY-MM-DD")

    return query.order_by(Email.timestamp.desc()).all()


@app.get("/emails/unread", response_model=List[EmailOut])
def get_unread_emails(db: Session = Depends(get_db)):
    """Get all unread emails"""
    return db.query(Email).filter(Email.read == False).order_by(Email.timestamp.desc()).all()


@app.get("/emails/{email_id}", response_model=EmailOut)
def get_email(email_id: int, db: Session = Depends(get_db)):
    """Get a specific email by ID"""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email


@app.patch("/emails/{email_id}/read", response_model=EmailOut)
def mark_email_as_read(email_id: int, db: Session = Depends(get_db)):
    """Mark an email as read"""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email.read = True
    db.commit()
    db.refresh(email)
    return email


@app.patch("/emails/{email_id}/unread", response_model=EmailOut)
def mark_email_as_unread(email_id: int, db: Session = Depends(get_db)):
    """Mark an email as unread"""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email.read = False
    db.commit()
    db.refresh(email)
    return email


@app.delete("/emails/{email_id}")
def delete_email(email_id: int, db: Session = Depends(get_db)):
    """Delete an email by ID"""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    db.delete(email)
    db.commit()
    return {"message": "Email deleted"}


@app.get("/reset_database")
def reset_database():
    """Reset database by clearing all emails and reloading sample data"""
    db = SessionLocal()
    try:
        # Delete all existing emails
        db.execute(delete(Email))
        db.commit()
        
        # Reload sample emails
        now = datetime.utcnow()
        samples = [
            Email(sender="manager@company.ir", recipient="you@email.com",
                  subject="Quarterly Report", body="Please finalize the report ASAP.",
                  timestamp=now, read=False),
            Email(sender="alice@work.com", recipient="you@email.com",
                  subject="Lunch?", body="Free for lunch today?",
                  timestamp=now, read=False),
            Email(sender="bob@work.com", recipient="you@email.com",
                  subject="Code Review", body="I left some comments on your PR.",
                  timestamp=now, read=False),
            Email(sender="charlie@work.com", recipient="you@email.com",
                  subject="Meeting", body="Can we reschedule?",
                  timestamp=now, read=False),
            Email(sender="eric@work.com", recipient="you@email.com",
                  subject="Happy Hour", body="We're planning drinks this Friday!",
                  timestamp=now, read=False),
            Email(sender="you@mail.com", recipient="manager@company.ir",
                  subject="Days off", body="Can I get some days off the coming week?",
                  timestamp=now, read=False),
        ]
        random.shuffle(samples)
        db.add_all(samples)
        db.commit()
    finally:
        db.close()
    
    return {"message": "Database reset and emails reloaded"}


@app.get("/health")
def health():
    """Simple health check endpoint"""
    return {"status": "ok"}
