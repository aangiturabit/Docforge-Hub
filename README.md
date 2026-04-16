# 📄 DocForge Hub

DocForge Hub is a modular document generation system that automates the creation of structured business documents using AI. It is built with a FastAPI backend, PostgreSQL database, and a Streamlit-based frontend.

---

## 🚀 Overview

The system enables users to generate department-specific documents by combining predefined templates with AI-generated content. It follows a service-oriented architecture with clear separation between API routing, business logic, and database operations.

---

## 🏗️ Project Structure

```bash
DocForge Hub/
│
├── docforge/
│   ├── backend/
│   │   ├── database/
│   │   │   ├── models/
│   │   │   │   ├── models.py
│   │   │   │   └── __init__.py
│   │   │   ├── connection.py
│   │   │   └── crud.py
│   │   │
│   │   ├── routers/
│   │   │   ├── departments.py
│   │   │   ├── documents.py
│   │   │   ├── generate.py
│   │   │   ├── notion.py
│   │   │   ├── sessions.py
│   │   │   └── templates.py
│   │   │
│   │   ├── schemas/
│   │   │   └── schemas.py
│   │   │
│   │   ├── services/
│   │   │   ├── document_service.py
│   │   │   ├── llm_service.py
│   │   │   ├── notion_service.py
│   │   │   ├── prompt_service.py
│   │   │   └── question_service.py
│   │   │
│   │   ├── utils/
│   │   └── main.py
│   │
│   ├── frontend/
│   │   └── app.py
│
├── Wireframe/
├── .env
├── requirements.txt
└── README.md
```

---

## ⚙️ Tech Stack

* **Backend:** FastAPI
* **Frontend:** Streamlit
* **Database:** PostgreSQL
* **ORM:** SQLAlchemy
* **Validation:** Pydantic

---

## 🔄 Architecture


[ User (Streamlit UI) ]
            ↓
[ FastAPI Routers ]
            ↓
[ Services Layer ]
   ├── Prompt Service
   ├── LLM Service
   ├── Document Service
            ↓
[ PostgreSQL Database ]

* **Routers:** Define API endpoints and handle HTTP requests
* **Services:** Contain core business logic and orchestration
* **Database Layer:** Manages models, connections, and CRUD operations
* **Schemas:** Define request and response validation
* **Frontend:** Provides user interaction via Streamlit

## 🔄 Execution Flow

1. User selects department and document type
2. Template is retrieved from the database
3. Prompt is generated dynamically
4. LLM generates structured content
5. Response is validated and stored
---

## 🛠️ Setup

### Clone Repository

```bash
git clone https://github.com/aangiturabit/Docforge-Hub.git
cd Docforge-Hub
git checkout feature/database-storage
```

---

### Create Virtual Environment

```bash
python -m venv venv
```

Activate:

* Windows:

```bash
venv\Scripts\activate
```

* macOS/Linux:

```bash
source venv/bin/activate
```

---

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

### Configure Environment Variables

Create a `.env` file:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/docforge
OPENAI_API_KEY=your_api_key
```

---

### Run Backend

```bash
uvicorn docforge.backend.main:app --reload
```

---

### Run Frontend

```bash
streamlit run docforge/frontend/app.py
```

---


