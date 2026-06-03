# DocForge Hub

DocForge Hub is an AI-powered document workspace for generating structured business documents, managing a document library, querying Notion-backed knowledge with RAG, and escalating unanswered questions into support tickets through a LangGraph agent.

The project combines a FastAPI backend, Streamlit frontend, PostgreSQL persistence, Notion integration, Azure OpenAI generation, hybrid retrieval, Redis caching, ChromaDB vector storage, and a LangGraph-based agent workflow.

## Table of Contents

- [Features](#features)
- [System Overview](#system-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Core Workflows](#core-workflows)
- [Architecture](#architecture)
- [Environment Variables](#environment-variables)
- [Setup](#setup)
- [Running the App](#running-the-app)
- [API Overview](#api-overview)
- [Frontend Screens](#frontend-screens)
- [Data and Storage](#data-and-storage)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)

## Features

### Document Generation

- Select a department and document type.
- Auto-load dynamic form fields for the selected template.
- Generate structured business documents with Azure OpenAI.
- Preview generated content before saving.
- Regenerate individual sections with optional feedback.
- Download generated documents as PDF or DOCX.
- Publish generated documents to Notion.

### Document Library

- View all generated documents.
- Filter documents by department and document type.
- Open a saved document in a reader-style view.
- Download existing documents as PDF or DOCX.
- Delete documents.
- Publish saved documents to Notion.

### RAG Document Assistant

- Ingest documents from Notion.
- Chunk documents into parent and child sections.
- Store dense embeddings in ChromaDB.
- Build a BM25 sparse retrieval index.
- Ask grounded questions over the document library.
- Compare two document types.
- Summarize a document type or department.
- Evaluate RAG output with batch questions and RAGAS-style metrics.
- Show citations, confidence, and retrieval inspector details.

### Agent Assistant

- Uses LangGraph to classify user intent.
- Supports document questions, clarification, ticket creation, and ticket-status checks.
- Uses conversation memory from Redis and PostgreSQL.
- Retrieves relevant knowledge-base chunks.
- Evaluates confidence before answering.
- Offers ticket creation when the answer is low-confidence or out of the knowledge base.
- Creates support tickets in Notion.
- Deduplicates repeated ticket requests using Redis.
- Displays ticket status and Notion ticket links.

## System Overview

```text
User
  |
  v
Streamlit Frontend
  |
  +-- /api/*        -> Document generation, library, downloads, Notion publish
  +-- /rag/*        -> Ingestion, retrieval, RAG query, compare, summarize, evaluate
  +-- /agent/*      -> LangGraph agent, memory, tickets
  |
  v
FastAPI Backend
  |
  +-- PostgreSQL    -> departments, templates, sessions, generated documents
  +-- Redis         -> RAG/session cache, agent memory, ticket deduplication
  +-- ChromaDB      -> vector index for child chunks
  +-- Local JSON    -> chunks, raw Notion blocks, evaluation reports
  +-- Notion API    -> source documents and ticket publishing
  +-- Azure OpenAI  -> LLM generation and embeddings
```

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | Streamlit |
| Backend API | FastAPI |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| LLM | Azure OpenAI |
| Agent Orchestration | LangGraph |
| RAG Framework Pieces | Custom retrieval pipeline with LangChain integrations |
| Vector Store | ChromaDB |
| Sparse Retrieval | BM25 index |
| Cache and Memory | Redis |
| External Workspace | Notion API |
| Document Export | fpdf2, python-docx |
| Validation | Pydantic |

## Project Structure

```text
docforge/
  backend/
    agent/
      graph.py                  # LangGraph workflow definition
      notion_ticket.py          # Notion ticket integration
      state.py                  # Agent state type
      memory/
        pg_memory.py            # PostgreSQL chat history
        redis_memory.py         # Redis session memory
      nodes/
        intent.py               # Intent classification
        clarify.py              # Clarification response
        retrieve.py             # Knowledge retrieval
        evaluate.py             # Confidence evaluation
        answer.py               # Grounded answer generation
        ticket.py               # Ticket dedup/create/status logic
        notify.py               # Final user-facing response
    database/
      connection.py             # SQLAlchemy engine/session
      crud.py                   # Database access helpers
      models/models.py          # Database models
    rag/
      ingestion/
        notion_client.py        # Fetch Notion pages/blocks
        chunker.py              # Parent/child chunking and embeddings
      retrieval/
        dense.py                # ChromaDB dense retrieval
        sparse.py               # BM25 index
        hybrid.py               # Hybrid search
        reranker.py             # Optional reranking layer
      generation/
        prompt_builder.py       # RAG prompt construction
        llm_client.py           # Azure OpenAI answer generation
        citation_parser.py      # Citation extraction/mapping
      evaluation/
        ragas_runner.py         # RAG evaluation
      cache/
        redis_client.py         # Redis helpers
    renderers/
      pdf_renderer.py           # PDF export
      docx_renderer.py          # DOCX export
    routers/
      departments.py            # Department APIs
      templates.py              # Template APIs
      generate.py               # Document generation APIs
      documents.py              # Library/download APIs
      notion.py                 # Notion publishing APIs
      ingest.py                 # RAG ingestion API
      query.py                  # RAG query/compare/summarize/evaluate APIs
      agent.py                  # Agent chat and ticket APIs
    services/
      document_service.py       # Document generation orchestration
      prompt_service.py         # Prompt construction
      llm_service.py            # Azure OpenAI service
      notion_service.py         # Notion document publishing
      question_service.py       # Dynamic form structure
      text_utils.py             # Sanitization utilities
    main.py                     # FastAPI app entrypoint
  frontend/
    app.py                      # Streamlit app
  data/
    chunks.json                 # RAG parent/child chunks
    raw_blocks.json             # Raw Notion block export
    bm25_index.pkl              # Sparse retrieval index
    evaluations/                # RAG evaluation reports
  Wireframe/
    ER.jpeg                     # Existing ER/reference image
    WIREFRAME.md                # Full product wireframe
  requirements.txt
  README.md
```

## Core Workflows

### 1. Generate a Document

```text
Select department
  -> Select document type
  -> Backend loads template fields
  -> User fills form
  -> Preview or generate
  -> LLM creates structured sections
  -> Document is saved to PostgreSQL
  -> User can rewrite sections, download, or publish to Notion
```

### 2. Query Documents with RAG

```text
User asks a question
  -> Hybrid search retrieves relevant child chunks
  -> Parent sections are loaded for richer context
  -> LLM answers using only retrieved context
  -> Citation parser maps [Source N] back to document breadcrumbs
  -> Frontend shows answer, confidence, sources, and retrieval inspector
```

### 3. Agent Question and Ticket Flow

```text
User sends message
  -> intent_node classifies intent
  -> question intent retrieves knowledge chunks
  -> evaluate_node assigns confidence
  -> high confidence: answer_node generates response
  -> low/out-of-kb: notify_node offers support ticket
  -> user creates ticket
  -> ticket node checks Redis deduplication
  -> Notion ticket is created
  -> ticket link/status returns to user
```

## Architecture

### Backend Routing

```text
FastAPI app: backend/main.py
  /api/departments
  /api/templates
  /api/generate
  /api/sessions
  /api/notion
  /api/documents
  /rag/rag-ingest
  /rag/rag-query
  /rag/rag-compare
  /rag/rag-summarize
  /rag/rag-evaluate
  /agent/chat
  /agent/create-ticket
  /agent/tickets
  /agent/history/{session_id}
```

### LangGraph Agent

```mermaid
flowchart TD
    A[intent_node] --> B{Intent}
    B -->|unclear| C[clarify_node]
    B -->|question| D[retrieve_node]
    B -->|create_ticket| E[check_ticket_node]
    B -->|ticket_status| F[fetch_ticket_node]
    D --> G[evaluate_node]
    G -->|high| H[answer_node]
    G -->|low or out_of_kb| I[notify_node]
    H --> I
    E --> J{Ticket exists?}
    J -->|yes| I
    J -->|no| K[create_ticket_node]
    K --> I
```

### RAG Pipeline

```mermaid
flowchart LR
    A[Notion documents] --> B[Fetch pages and blocks]
    B --> C[Parent/child chunking]
    C --> D[Embeddings]
    C --> E[BM25 index]
    D --> F[ChromaDB]
    E --> G[Hybrid search]
    F --> G
    G --> H[Parent expansion]
    H --> I[Azure OpenAI answer]
    I --> J[Citations and confidence]
```

## Environment Variables

Create a `.env` file in the project working directory used to run the backend.

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/docforge

# Redis
REDIS_URL=redis://localhost:6379

# Azure OpenAI - chat/completion model
AZURE_OPENAI_LLM_KEY=your_azure_openai_key
AZURE_LLM_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_LLM_API_VERSION=2024-xx-xx
AZURE_LLM_DEPLOYMENT_41_MINI=your_chat_deployment_name
LLM_MAX_TOKENS=8000

# Azure OpenAI - embedding model
AZURE_OPENAI_EMB_KEY=your_azure_openai_embedding_key
AZURE_EMB_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_EMB_API_VERSION=2024-xx-xx
AZURE_EMB_DEPLOYMENT=your_embedding_deployment_name

# Notion document source/publishing
NOTION_API_KEY=secret_xxx
NOTION_DATABASE_ID=your_notion_document_database_id

# Notion support tickets
NOTION_TICKET_DATABASE_ID=your_notion_ticket_database_id
```

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/aangiturabit/Docforge-Hub.git
cd Docforge-Hub/docforge
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it:

```bash
# macOS/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Start Required Services

Make sure PostgreSQL and Redis are running before starting the backend.

Example local services:

```bash
# PostgreSQL: create a database named docforge
# Redis: default redis://localhost:6379
```

### 5. Configure `.env`

Add the environment variables listed above. The backend loads configuration with `python-dotenv`.

### 6. Prepare Data

The app expects seeded departments/templates in PostgreSQL for generation and Notion-ingested chunks for RAG. If the database is empty, add departments, templates, and template fields before using the Generate tab.

To refresh the RAG corpus from Notion:

```bash
curl -X POST http://localhost:8000/rag/rag-ingest
```

## Running the App

Run the backend from the `docforge` directory:

```bash
uvicorn backend.main:app --reload
```

Backend URLs:

```text
API:  http://localhost:8000
Docs: http://localhost:8000/docs
```

Run the frontend in another terminal from the `docforge` directory:

```bash
streamlit run frontend/app.py
```

Frontend URL:

```text
http://localhost:8501
```

## API Overview

### Health

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` | App status |
| GET | `/health` | Health check |

### Document Generation and Library

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/departments` | List departments |
| GET | `/api/templates/{department_id}` | List templates for a department |
| POST | `/api/generate/questions` | Get dynamic form fields |
| POST | `/api/generate/preview` | Generate unsaved preview |
| POST | `/api/generate/document` | Generate and save document |
| POST | `/api/generate/section` | Regenerate one section |
| GET | `/api/documents` | List documents |
| GET | `/api/documents/{document_id}` | Get one document |
| DELETE | `/api/documents/{document_id}` | Delete document |
| GET | `/api/documents/{document_id}/pdf` | Download PDF |
| GET | `/api/documents/{document_id}/docx` | Download DOCX |
| POST | `/api/notion/publish` | Publish document to Notion |

### RAG

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/rag/rag-ingest` | Fetch Notion docs, chunk, embed, and index |
| GET | `/rag/rag-metadata` | List available doc types/departments |
| POST | `/rag/rag-query` | Ask a grounded document question |
| POST | `/rag/rag-compare` | Compare two document types |
| POST | `/rag/rag-summarize` | Summarize document content |
| POST | `/rag/rag-evaluate` | Batch evaluate RAG answers |

### Agent

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/agent/chat` | Main LangGraph chat endpoint |
| POST | `/agent/create-ticket` | Create ticket from frontend button |
| GET | `/agent/tickets` | List support tickets |
| GET | `/agent/history/{session_id}` | Load chat history |

## Frontend Screens

### Sidebar

- Company name
- Industry
- Company size
- Location
- Tone

The company context is optional and improves the generated document style and specificity.

### Generate Tab

- Department selector
- Document type selector
- Dynamic form fields grouped by section
- Generate and Preview actions
- Generated document viewer
- Version and document ID metrics
- PDF/DOCX download actions
- Publish to Notion
- Per-section rewrite popover

### Document Library Tab

- Department filter
- Document type filter
- Document list
- View, PDF, DOCX, Delete actions
- Publish-to-Notion expander
- Full document reading view

### RAG Assistant Tab

- Filters for doc type and department
- Modes: Query, Compare, Summarize, Evaluate
- Chat-style Q&A
- Confidence indicator
- Sources/citations
- Retrieval inspector
- Batch evaluation metrics

### Agent Tab

- Current agent session
- New session action
- Refresh tickets action
- Conversational chat with assistant responses
- Intent/confidence/trace metadata
- Source list for grounded answers
- Create Ticket action for unresolved answers
- Tickets expander with status and Notion links

## Data and Storage

| Storage | Purpose |
| --- | --- |
| PostgreSQL | Departments, templates, sessions, generated documents, persisted agent messages |
| Redis | RAG cache, agent session memory, ticket deduplication |
| ChromaDB | Dense vector index for RAG child chunks |
| `data/chunks.json` | Parent/child RAG chunks |
| `data/raw_blocks.json` | Notion block export |
| `data/bm25_index.pkl` | Sparse retrieval index |
| `data/evaluations/*.json` | RAG evaluation reports |
| Notion | Source documents, published documents, support ticket database |

## Troubleshooting

### Frontend says backend cannot connect

Start FastAPI first:

```bash
uvicorn backend.main:app --reload
```

Then start Streamlit:

```bash
streamlit run frontend/app.py
```

### Generate tab shows no departments

The PostgreSQL database may not be seeded. Add department and template data, then refresh the app.

### RAG returns no relevant documents

Run ingestion and confirm Notion credentials:

```bash
curl -X POST http://localhost:8000/rag/rag-ingest
```

Also check that `data/chunks.json`, ChromaDB storage, and `data/bm25_index.pkl` exist.

### Agent ticket creation fails

Check:

- `NOTION_API_KEY`
- `NOTION_TICKET_DATABASE_ID`
- Notion integration permissions on the ticket database
- Redis availability for deduplication

### PDF or DOCX download is disabled

The document must contain structured sections. If a legacy/plain document has no structured JSON, export may not be available.

## Roadmap

- Make the Agent tab fully conversational while preserving the current ticket flow.
- Add authentication and user-level document ownership.
- Add admin screens for managing departments/templates.
- Add automated database migrations.
- Add Docker Compose for PostgreSQL, Redis, backend, and frontend.
- Add automated tests for generation, RAG, and agent routing.
- Add richer ticket lifecycle controls from the frontend.

## License

Add your preferred license before publishing this repository publicly.
