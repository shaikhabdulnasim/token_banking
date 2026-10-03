import os
from fastapi.responses import HTMLResponse
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import date, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
from google import genai

from database import engine, get_db, SessionLocal, Base
import models

# Tables create karo
Base.metadata.create_all(bind=engine)

# Gemini Client setup (GEMINI_API_KEY environment variable se lega)
# Agar API key na ho toh fallback estimation logic chalega testing ke liye
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
ai_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

def execute_rollover():
    db: Session = SessionLocal()
    try:
        wallets = db.query(models.Wallet).all()
        for wallet in wallets:
            unused = wallet.daily_quota - wallet.daily_used
            if unused > 0:
                actual_addition = min(unused, wallet.max_bank_limit - wallet.bank_reserve)
                if actual_addition > 0:
                    wallet.bank_reserve += actual_addition
                    txn = models.TokenTransaction(
                        sender_id="SYSTEM",
                        receiver_id=wallet.user_id,
                        amount=actual_addition,
                        txn_type="BANK_ROLLOVER"
                    )
                    db.add(txn)

            wallet.daily_used = 0
            wallet.last_reset_date = str(date.today())
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error during rollover: {e}")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(execute_rollover, "cron", hour=0, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="AI Token Bank System", lifespan=lifespan)

# Schemas
class UserCreate(BaseModel):
    user_id: str
    initial_daily_quota: int = 10000

class TransferRequest(BaseModel):
    sender_id: str
    receiver_id: str
    amount: int = Field(..., gt=0)

class ChatRequest(BaseModel):
    user_id: str
    prompt: str

@app.get("/")
def home():
    return {"message": "AI Token Bank Server is running!"}

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    with open("templates/index.html", "r") as f:
        return f.read()
    
@app.post("/users/create")
def create_wallet(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Wallet).filter(models.Wallet.user_id == user.user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    new_wallet = models.Wallet(user_id=user.user_id, daily_quota=user.initial_daily_quota)
    db.add(new_wallet)
    db.commit()
    return {"status": "success", "wallet": new_wallet}

@app.get("/users/{user_id}/balance")
def get_balance(user_id: str, db: Session = Depends(get_db)):
    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == user_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="User not found")
    available_today = wallet.daily_quota - wallet.daily_used
    return {
        "user_id": wallet.user_id,
        "daily_quota": wallet.daily_quota,
        "daily_used": wallet.daily_used,
        "available_daily": available_today,
        "bank_reserve": wallet.bank_reserve,
        "total_available_tokens": available_today + wallet.bank_reserve
    }

@app.post("/bank/transfer")
def transfer_tokens(payload: TransferRequest, db: Session = Depends(get_db)):
    if payload.sender_id == payload.receiver_id:
        raise HTTPException(status_code=400, detail="Self-transfer not allowed")
    sender = db.query(models.Wallet).filter(models.Wallet.user_id == payload.sender_id).first()
    receiver = db.query(models.Wallet).filter(models.Wallet.user_id == payload.receiver_id).first()
    if not sender or not receiver:
        raise HTTPException(status_code=404, detail="User not found")
    if sender.bank_reserve < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient bank reserve")

    sender.bank_reserve -= payload.amount
    receiver.bank_reserve += payload.amount
    txn = models.TokenTransaction(
        sender_id=payload.sender_id,
        receiver_id=payload.receiver_id,
        amount=payload.amount,
        txn_type="TRANSFER"
    )
    db.add(txn)
    db.commit()
    return {"status": "success", "sender_reserve": sender.bank_reserve}

@app.post("/bank/trigger-rollover")
def trigger_rollover():
    execute_rollover()
    return {"status": "success", "message": "Rollover executed"}

@app.get("/users/{user_id}/history")
def get_transaction_history(user_id: str, db: Session = Depends(get_db)):
    txns = db.query(models.TokenTransaction).filter(
        (models.TokenTransaction.sender_id == user_id) | (models.TokenTransaction.receiver_id == user_id)
    ).order_by(models.TokenTransaction.created_at.desc()).all()
    return {"user_id": user_id, "transactions": txns}

# ----------------- PHASE 5: AI CHAT PROXY GATEWAY -----------------
@app.post("/v1/chat")
def chat_with_ai(payload: ChatRequest, db: Session = Depends(get_db)):
    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == payload.user_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="User not found")

    daily_left = wallet.daily_quota - wallet.daily_used
    total_tokens_left = daily_left + wallet.bank_reserve

    if total_tokens_left <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Tokens khatam ho gaye! Daily quota aur Bank reserve dono empty hain."
        )

    # AI API Call
    ai_response_text = ""
    tokens_consumed = 0

    if ai_client:
        try:
            response = ai_client.models.generate_content(
                model='gemini-3.8-flash',
                contents=payload.prompt,
            )
            ai_response_text = response.text
            # Usage metadata se actual token count
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                tokens_consumed = response.usage_metadata.total_token_count
            else:
                tokens_consumed = len(payload.prompt.split()) + len(ai_response_text.split())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")
    else:
        # Fallback simulation agar API key configure nahi hai
        ai_response_text = f"Simulated AI Response for: '{payload.prompt}'"
        tokens_consumed = len(payload.prompt.split()) * 2 + 35

    # Deduction Logic (Daily First, then Bank Reserve)
    deducted_from_daily = 0
    deducted_from_bank = 0

    if daily_left >= tokens_consumed:
        wallet.daily_used += tokens_consumed
        deducted_from_daily = tokens_consumed
    else:
        # Daily exhausted
        deducted_from_daily = max(0, daily_left)
        wallet.daily_used = wallet.daily_quota
        
        remaining_needed = tokens_consumed - deducted_from_daily
        deducted_from_bank = min(remaining_needed, wallet.bank_reserve)
        wallet.bank_reserve -= deducted_from_bank

    # Transaction log
    txn = models.TokenTransaction(
        sender_id=payload.user_id,
        receiver_id="AI_SERVICE",
        amount=tokens_consumed,
        txn_type="AI_USAGE"
    )
    db.add(txn)
    db.commit()

    return {
        "status": "success",
        "response": ai_response_text,
        "tokens_consumed": tokens_consumed,
        "breakdown": {
            "deducted_from_daily": deducted_from_daily,
            "deducted_from_bank": deducted_from_bank
        },
        "remaining_balance": {
            "daily_available": wallet.daily_quota - wallet.daily_used,
            "bank_reserve": wallet.bank_reserve
        }
    }