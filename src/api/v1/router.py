from fastapi import APIRouter
from src.api.v1.endpoints import analyze

api_router = APIRouter()

# Include the analyze endpoint we built earlier
api_router.include_router(analyze.router, tags=["Legal Analysis"])