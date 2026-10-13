from fastapi import APIRouter

from backend.app.api.v1 import alerts, auth, cameras, dashboard, detection, health, incidents, system

api_router = APIRouter(prefix="/api/v1")
for module in (health, auth, cameras, detection, incidents, alerts, dashboard, system):
    api_router.include_router(module.router)
