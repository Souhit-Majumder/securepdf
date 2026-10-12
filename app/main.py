from fastapi import FastAPI
from app.api.routes import documents, students, distribution, verification
from app.database.database import init_db

app = FastAPI(title="Secure PDF Fingerprinting API", version="1.0.0")

@app.on_event("startup")
def startup_event():
    init_db()

app.include_router(documents.router, prefix="/documents", tags=["Documents"])
app.include_router(students.router, prefix="/students", tags=["Students"])
app.include_router(distribution.router, prefix="/documents", tags=["Distribution"])
app.include_router(verification.router, prefix="/verify", tags=["Verification"])
