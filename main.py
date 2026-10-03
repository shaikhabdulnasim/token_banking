from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import date, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

from database import engine, get_db, SessionLocal, Base
import models

# Tables create karo
Base.metadata.create_all(bind=engine)

# Rollover execution function
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
        print(f"[{datetime.now()}] Bank rollover completed successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error during rollover: {e}")
    finally:
        db.close()

# Background Scheduler setup
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(execute_rollover, "cron", hour=0, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="AI Token Bank System", lifespan=lifespan)

# Pydantic Schemas
class UserCreate(BaseModel):
    user_id: str
    initial_daily_quota: int = 10000

class UsageSimulate(BaseModel):
    user_id: str
    tokens_to_use: int

class TransferRequest(BaseModel):
    sender_id: str
    receiver_id: str
    amount: int = Field(..., gt=0, description="Amount must be greater than 0")

@app.get("/")
def home():
    return {"message": "AI Token Bank Server is running!"}

# 1. User Registration
@app.post("/users/create")
def create_wallet(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(models.Wallet).filter(models.Wallet.user_id == user.user_id).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    
    new_wallet = models.Wallet(
        user_id=user.user_id,
        daily_quota=user.initial_daily_quota,
        daily_used=0,
        bank_reserve=0
    )
    db.add(new_wallet)
    db.commit()
    db.refresh(new_wallet)
    return {"status": "success", "wallet": new_wallet}

# 2. Balance Check
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

# 3. Simulate Daily Usage
@app.post("/users/simulate-usage")
def simulate_usage(payload: UsageSimulate, db: Session = Depends(get_db)):
    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == payload.user_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="User not found")
    
    available_today = wallet.daily_quota - wallet.daily_used
    if payload.tokens_to_use > available_today:
        raise HTTPException(status_code=400, detail="Not enough daily tokens")

    wallet.daily_used += payload.tokens_to_use
    db.commit()
    return {
        "status": "success",
        "used": payload.tokens_to_use,
        "remaining_daily": wallet.daily_quota - wallet.daily_used
    }

# 4. Manual Rollover Trigger
@app.post("/bank/trigger-rollover")
def trigger_rollover():
    execute_rollover()
    return {"status": "success", "message": "Manual rollover executed for all users."}

# 5. P2P Token Transfer (New)
@app.post("/bank/transfer")
def transfer_tokens(payload: TransferRequest, db: Session = Depends(get_db)):
    if payload.sender_id == payload.receiver_id:
        raise HTTPException(status_code=400, detail="Khud ko transfer nahi kar sakte (Self-transfer not allowed)")

    sender = db.query(models.Wallet).filter(models.Wallet.user_id == payload.sender_id).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender user nahi mila")

    receiver = db.query(models.Wallet).filter(models.Wallet.user_id == payload.receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver user nahi mila")

    # Check sender balance
    if sender.bank_reserve < payload.amount:
        raise HTTPException(
            status_code=400, 
            detail=f"Insufficient bank balance! Aapke bank me sirf {sender.bank_reserve} tokens hain."
        )

    # Receiver capacity check
    if receiver.bank_reserve + payload.amount > receiver.max_bank_limit:
        raise HTTPException(status_code=400, detail="Receiver ka bank wallet full ho jayega.")

    try:
        # Atomic balance update
        sender.bank_reserve -= payload.amount
        receiver.bank_reserve += payload.amount

        # Passbook receipt create karo
        txn = models.TokenTransaction(
            sender_id=payload.sender_id,
            receiver_id=payload.receiver_id,
            amount=payload.amount,
            txn_type="TRANSFER"
        )
        db.add(txn)
        db.commit()

        return {
            "status": "success",
            "message": f"Successfully transferred {payload.amount} tokens from {payload.sender_id} to {payload.receiver_id}",
            "sender_remaining_reserve": sender.bank_reserve
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Transaction failed: {str(e)}")

# 6. User Transaction History / Passbook (New)
@app.get("/users/{user_id}/history")
def get_transaction_history(user_id: str, db: Session = Depends(get_db)):
    txns = db.query(models.TokenTransaction).filter(
        (models.TokenTransaction.sender_id == user_id) | (models.TokenTransaction.receiver_id == user_id)
    ).order_by(models.TokenTransaction.created_at.desc()).all()
    
    return {"user_id": user_id, "transactions": txns}