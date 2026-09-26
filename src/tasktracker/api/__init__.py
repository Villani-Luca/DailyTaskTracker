from fastapi import APIRouter

from tasktracker.api import auth, calendar, folders, reports, tasks

api_router = APIRouter(prefix="/api")
for module in (auth, folders, tasks, calendar, reports):
    api_router.include_router(module.router)
