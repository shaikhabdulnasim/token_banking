from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, get_db, Base
import models

# Tables create karo agar pehle se nahi hain
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Token Bank System")

# Pydantic Schemas (Request structure)
class UserCreate(BaseModel):
    user_id: str
    initial_daily_quota: int = 10000

@app.get("/")
def home():
    return {"message": "AI Token Bank Server is running!"}

# 1. Naya User/Wallet Banane ka Endpoint
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

# 2. User ka Balance Check karne ka Endpoint
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