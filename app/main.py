import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.router import api_router
from app.config import settings
from app.core.database import init_db


def setup_logging() -> None:
    """Configure application logging."""
    # Format: timestamp - level - logger name - message
    log_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    date_format = "%H:%M:%S"

    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        stream=sys.stdout,
        force=True,
    )

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    # Quieten uvicorn access logs (we'll log requests ourselves)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    from app.services.scheduler import scheduler

    # Startup
    setup_logging()
    logger.info("Trajan API starting up")
    if settings.debug:
        await init_db()
    scheduler.start()
    yield
    # Shutdown
    scheduler.stop()
    logger.info("Trajan API shutting down")


app = FastAPI(
    title="Trajan API",
    description="Lightweight developer workspace API",
    version="0.1.0",
    lifespan=lifespan,
)

# Proxy headers middleware - trust X-Forwarded-Proto from reverse proxy (Fly.io)
# This ensures redirects use HTTPS when behind TLS-terminating proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log HTTP requests, skipping OPTIONS preflight."""
    # Skip OPTIONS (CORS preflight) and health checks
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)

    # Log the request
    response = await call_next(request)

    # Only log non-2xx or important endpoints
    path = request.url.path
    if response.status_code >= 400 or any(
        keyword in path for keyword in ["analyze", "generate", "sync", "import"]
    ):
        logger.info(f"{request.method} {path} → {response.status_code}")

    return response


# Include API routes
app.include_router(api_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
