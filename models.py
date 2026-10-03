from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, date
from database import Base

class Wallet(Base):
    __tablename__ = "wallets"

    user_id = Column(String, primary_key=True, index=True)
    daily_quota = Column(Integer, default=10000)  # Har din ka fresh quota
    daily_used = Column(Integer, default=0)        # Aaj kitna use kiya
    bank_reserve = Column(Integer, default=0)      # Bank me jama tokens
    max_bank_limit = Column(Integer, default=100000) # Bank me max capacity
    last_reset_date = Column(String, default=str(date.today()))

class TokenTransaction(Base):
    __tablename__ = "token_transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sender_id = Column(String, index=True)
    receiver_id = Column(String, index=True)
    amount = Column(Integer, nullable=False)
    txn_type = Column(String)  # 'TRANSFER', 'DAILY_USAGE', 'BANK_ROLLOVER'
    created_at = Column(DateTime, default=datetime.utcnow)