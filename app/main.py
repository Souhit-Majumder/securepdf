from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import documents, students, distribution, verification
from app.database.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="Secure PDF Fingerprinting API",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(documents.router, prefix="/documents", tags=["Documents"])
app.include_router(students.router, prefix="/students", tags=["Students"])
app.include_router(distribution.router, prefix="/documents", tags=["Distribution"])
app.include_router(verification.router, prefix="/verify", tags=["Verification"])
