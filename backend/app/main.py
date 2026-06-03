from fastapi import FastAPI
from app.routes.auth import router as auth_router
from app.routes.webhook import router as webhook_router

app = FastAPI(
    title="AI Code Review Assistant",
    version="1.0.0"
)

app.include_router(auth_router, prefix="/auth")
app.include_router(webhook_router, prefix="/webhooks")

@app.get("/")
def root():
    return {
        "message": "AI Code Review Assistant Running"
    }