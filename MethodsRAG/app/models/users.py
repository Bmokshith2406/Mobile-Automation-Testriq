from typing import Optional
from bson import ObjectId

from app.db.mongo import get_users_collection
from app.core.security import hash_password, verify_password


async def get_user_by_username(username: str) -> Optional[dict]:
    try:
        col = get_users_collection()
    except Exception:
        return None

    try:
        user = await col.find_one({"username": username})
        return user
    except Exception:
        return None


async def create_user(username: str, password: str, role: str = "viewer") -> dict:
    try:
        col = get_users_collection()
    except Exception:
        raise RuntimeError("User collection unavailable")

    try:
        hashed = hash_password(password)
    except Exception:
        raise RuntimeError("Password hashing failed")

    doc = {
        "username": username,
        "hashed_password": hashed,
        "role": role,
    }

    try:
        res = await col.insert_one(doc)
        doc["_id"] = res.inserted_id
        return doc
    except Exception:
        raise RuntimeError("Failed creating user")


async def authenticate_user(username: str, password: str) -> Optional[dict]:
    try:
        user = await get_user_by_username(username)
    except Exception:
        return None

    if not user:
        return None

    try:
        is_valid = verify_password(
            password,
            user.get("hashed_password", ""),
        )
    except Exception:
        return None

    if not is_valid:
        return None

    return user


def user_to_out(user: dict) -> dict:
    try:
        return {
            "id": str(user.get("_id") or ""),
            "username": user.get("username"),
            "role": user.get("role", "viewer"),
        }
    except Exception:
        return {
            "id": "",
            "username": None,
            "role": "viewer",
        }
