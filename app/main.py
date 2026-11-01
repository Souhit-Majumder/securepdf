from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import documents, students, distribution, verification, inspection, auth
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/documents", tags=["Documents"])
app.include_router(students.router, prefix="/students", tags=["Students"])
app.include_router(distribution.router, prefix="/documents", tags=["Distribution"])
app.include_router(verification.router, prefix="/verify", tags=["Verification"])
app.include_router(inspection.router, prefix="/api/inspection", tags=["Inspection"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])

