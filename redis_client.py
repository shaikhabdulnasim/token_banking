import os
import redis

# Container networking ke liye 'redis' host use karein
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

r = redis.Redis(
    host=REDIS_HOST, 
    port=REDIS_PORT, 
    decode_responses=True,
    socket_connect_timeout=2
)

def get_user_cache_key(user_id: str) -> str:
    return f"wallet:{user_id}:balance"

def update_cached_balance(user_id: str, daily_available: int, bank_reserve: int, daily_quota: int = 10000, daily_used: int = 0):
    try:
        key = get_user_cache_key(user_id)
        r.hset(key, mapping={
            "daily_available": str(daily_available),
            "bank_reserve": str(bank_reserve),
            "daily_quota": str(daily_quota),
            "daily_used": str(daily_used)
        })
        r.expire(key, 86400)
    except Exception as e:
        print(f"[Redis Warning] Cache update failed: {e}")

def get_cached_balance(user_id: str):
    try:
        key = get_user_cache_key(user_id)
        data = r.hgetall(key)
        if data and "daily_available" in data:
            return {
                "daily_available": int(data.get("daily_available", 0)),
                "bank_reserve": int(data.get("bank_reserve", 0)),
                "daily_quota": int(data.get("daily_quota", 10000)),
                "daily_used": int(data.get("daily_used", 0))
            }
    except Exception as e:
        print(f"[Redis Warning] Cache read failed: {e}")
    return None