from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import departments, templates, generate, sessions, notion, documents, download
from backend.routers.ingest import router as ingest_router
from backend.routers.query import router as query_router

app = FastAPI(
    title="DocForge Hub",
    description="AI-Powered Business Document Generator",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Project 1 routers
app.include_router(departments.router, prefix="/api", tags=["Departments"])
app.include_router(templates.router, prefix="/api", tags=["Templates"])
app.include_router(generate.router, prefix="/api", tags=["Generate"])
app.include_router(sessions.router, prefix="/api", tags=["Sessions"])
app.include_router(notion.router, prefix="/api", tags=["Notion"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(download.router)

# RAG routers
app.include_router(ingest_router)
app.include_router(query_router)

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "running", "app": "DocForge Hub", "version": "1.0.0"}

@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}