"""Argus Agent — API: gestão de chaves de máquina (X-API-Key) para CI/CD."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src import auth, store

router = APIRouter(dependencies=[Depends(auth.require_api_key)])


class ApiKeyCreate(BaseModel):
    name: str


@router.post("/api/api-keys")
async def create_api_key(payload: ApiKeyCreate):
    if not payload.name.strip():
        return JSONResponse(status_code=400, content={"error": "Key name can't be empty."})
    row, full_key = store.create_api_key(payload.name.strip())
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "key": full_key,  # única vez que o valor completo é devolvido
        "created_at": row.created_at.isoformat(),
    }


@router.get("/api/api-keys")
async def list_api_keys():
    return [
        {
            "id": row.id,
            "name": row.name,
            "prefix": row.prefix,
            "created_at": row.created_at.isoformat(),
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "revoked": row.revoked,
        }
        for row in store.list_api_keys()
    ]


@router.delete("/api/api-keys/{key_id}")
async def revoke_api_key(key_id: str):
    if not store.revoke_api_key(key_id):
        return JSONResponse(status_code=404, content={"error": "Key not found."})
    return {"status": "ok"}
