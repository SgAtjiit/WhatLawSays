from fastapi import APIRouter
from src.api.v1.endpoints import contracts, procurement

api_router = APIRouter()

# `analyze` is deliberately NOT included here. src/main.py defines
# /api/v1/analyze itself, and mounting the endpoint module as well would serve
# two implementations of the same route -- the divergence its own comment warns
# about, where the two entry points scored the same scenario differently.
api_router.include_router(contracts.router)
api_router.include_router(procurement.router)
