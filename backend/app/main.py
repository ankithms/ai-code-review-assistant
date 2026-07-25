import logging
from fastapi import FastAPI
from app.routes.auth import router as auth_router
from app.routes.webhook import router as webhook_router
from app.routes.reviews import router as reviews_router
from app.routes.pull_requests import router as pull_request_router
from app.routes.analytics import router as analytics_router
from app.routes.fixes import router as fixes_router
from app.routes.repositories import router as repositories_router
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI(
    title="AI Code Review Assistant",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(repositories_router)
app.include_router(reviews_router)
app.include_router(fixes_router)
app.include_router(pull_request_router)
app.include_router(analytics_router)

@app.get("/")
def root():
    return {
        "message": "AI Code Review Assistant Running"
    }
