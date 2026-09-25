from fastapi import APIRouter

from tasktracker.api import calendar, folders, reports, tasks

api_router = APIRouter(prefix="/api")
for module in (folders, tasks, calendar, reports):
    api_router.include_router(module.router)
