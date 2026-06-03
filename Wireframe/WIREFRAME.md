# DocForge Hub Wireframe

This wireframe documents the full product experience for DocForge Hub as implemented in the Streamlit app. It is intentionally text-based so it can live cleanly in GitHub and stay close to the code.

## Global Layout

```text
+--------------------------------------------------------------------------------+
| Sidebar                                                                        |
| - Company Context                                                              |
|   - Company Name                                                               |
|   - Industry                                                                   |
|   - Company Size                                                               |
|   - Location                                                                   |
|   - Tone                                                                       |
| - App version                                                                  |
+-----------------------------+--------------------------------------------------+
| Main Header                 | DocForge Hub                                     |
|                             | AI-powered document generation                   |
+-----------------------------+--------------------------------------------------+
| Tabs                                                                           |
| [Generate] [Document Library] [RAG Assistant] [Agent]                          |
+--------------------------------------------------------------------------------+
```

## Navigation Model

```text
DocForge Hub
  |
  +-- Generate
  |     +-- Select department
  |     +-- Select document type
  |     +-- Fill dynamic fields
  |     +-- Preview document
  |     +-- Generate document
  |     +-- Rewrite sections
  |     +-- Download PDF/DOCX
  |     +-- Publish to Notion
  |
  +-- Document Library
  |     +-- Filter documents
  |     +-- View document
  |     +-- Download PDF/DOCX
  |     +-- Delete document
  |     +-- Publish to Notion
  |
  +-- RAG Assistant
  |     +-- Query
  |     +-- Compare
  |     +-- Summarize
  |     +-- Evaluate
  |
  +-- Agent
        +-- Chat
        +-- Create ticket when answer is missing
        +-- Check ticket status
        +-- Refresh tickets
```

## Screen 1: Sidebar Company Context

Purpose: collect optional company-level context that improves document generation quality.

```text
+-------------------------------+
| Company Context               |
| Optional - improves quality    |
|-------------------------------|
| Company Name                  |
| [ Acme Corp                 ] |
|                               |
| Industry                      |
| [ Technology                ] |
|                               |
| Company Size                  |
| [ 51-200                  v ] |
|                               |
| Location                      |
| [ Mumbai, India             ] |
|                               |
| Tone                          |
| [ Professional            v ] |
|-------------------------------|
| DocForge Hub - v1.0           |
+-------------------------------+
```

States:

- Empty values are allowed.
- Tone defaults to `Professional`.
- Changing company context reloads generation questions for the selected template.

## Screen 2: Generate Tab - Empty/Loading State

Purpose: guide the user into generating a document.

```text
+--------------------------------------------------------------------------------+
| Generate                                                                       |
|                                                                                |
| Department                  Document Type                                      |
| [ Human Resources      v ]  [ Offer Letter                                v ] |
|                                                                                |
|--------------------------------------------------------------------------------|
|                                                                                |
| Loading form fields...                                                         |
|                                                                                |
+--------------------------------------------------------------------------------+
```

Empty/backend-error state:

```text
+--------------------------------------------------------------------------------+
| No departments found. Check the backend is running.                            |
+--------------------------------------------------------------------------------+
```

## Screen 3: Generate Tab - Form and Document Placeholder

Purpose: collect structured answers before previewing or generating a document.

```text
+-------------------------------------+------------------------------------------+
| Offer Letter                        | Your document will appear here           |
| Human Resources                     |                                          |
|                                     | Fill in the form and click Generate      |
| [Generate Document] [Preview]       | Document.                                |
|-------------------------------------|                                          |
| Section: Candidate Details          | - AI generates all sections              |
| +---------------------------------+ | - Rewrite any section individually       |
| | Candidate Name                  | | - Download as PDF or DOCX               |
| | [                             ] | | - Publish to Notion                     |
| | Joining Date                    | |                                          |
| | [ date picker                 ] | |                                          |
| +---------------------------------+ |                                          |
|                                     |                                          |
| Section: Compensation               |                                          |
| +---------------------------------+ |                                          |
| | Salary                          | |                                          |
| | [                             ] | |                                          |
| +---------------------------------+ |                                          |
|                                     |                                          |
| [Generate Document] [Preview]       |                                          |
+-------------------------------------+------------------------------------------+
```

Primary actions:

- `Generate Document`: saves a generated document to the library.
- `Preview`: generates a temporary preview without saving.

## Screen 4: Generate Tab - Preview Mode

Purpose: let the user inspect generated output before saving.

```text
+--------------------------------------------------------------------------------+
| [Back] Preview mode - not saved to library.                                    |
|--------------------------------------------------------------------------------|
| Offer Letter                                                                   |
|--------------------------------------------------------------------------------|
| Candidate Details                                                              |
| +----------------------------------------------------------------------------+ |
| | Dear Rohan Sharma,                                                          | |
| | ...                                                                        | |
| +----------------------------------------------------------------------------+ |
|                                                                                |
| Compensation                                                                   |
| +----------------------------------------------------------------------------+ |
| | Your annual compensation will be...                                         | |
| +----------------------------------------------------------------------------+ |
+--------------------------------------------------------------------------------+
```

States:

- If previewing a saved document, label changes to `Preview of your generated document.`
- Back returns to the form/document workspace.

## Screen 5: Generate Tab - Generated Document

Purpose: work with the saved generated document.

```text
+--------------------------------------------------------------------------------+
| Offer Letter                                                                   |
|                                                                                |
| +----------------------------+ +---------------------------------------------+ |
| | Version: v1.0              | | Doc ID: 42                                  | |
| +----------------------------+ +---------------------------------------------+ |
|                                                                                |
| [Download PDF] [Download DOCX] [Publish to Notion]                             |
|--------------------------------------------------------------------------------|
| Candidate Details                                           [Rewrite]          |
| +----------------------------------------------------------------------------+ |
| | Dear Rohan Sharma, ...                                                      | |
| +----------------------------------------------------------------------------+ |
|                                                                                |
| Compensation                                                [Rewrite]          |
| +----------------------------------------------------------------------------+ |
| | Your annual compensation will be...                                         | |
| +----------------------------------------------------------------------------+ |
+--------------------------------------------------------------------------------+
```

Rewrite popover:

```text
+--------------------------------------+
| Candidate Details                    |
|                                      |
| Instructions (optional)              |
| [ Make this more formal...        ]  |
|                                      |
| [Regenerate]                         |
+--------------------------------------+
```

## Screen 6: Document Library - List View

Purpose: browse, filter, export, delete, and publish saved documents.

```text
+--------------------------------------------------------------------------------+
| Document Library                                                               |
|--------------------------------------------------------------------------------|
| Department                              Document Type                          |
| [ All Departments                  v ]  [ All Document Types              v ]  |
|--------------------------------------------------------------------------------|
| 12 document(s)                                                                 |
|                                                                                |
| +----------------------------------------------------------------------------+ |
| | Offer Letter                                      v1.0 - 01 Jun 2026        | |
| |                                                                            | |
| |                                  [View] [PDF] [DOCX] [Delete]              | |
| |                                                                            | |
| | Publish to Notion                                                           | |
| |   [Publish]                                                                 | |
| +----------------------------------------------------------------------------+ |
|                                                                                |
| +----------------------------------------------------------------------------+ |
| | Leave Policy                                      v1.0 - 30 May 2026        | |
| |                                  [View] [PDF] [DOCX] [Delete]              | |
| +----------------------------------------------------------------------------+ |
+--------------------------------------------------------------------------------+
```

Empty state:

```text
+--------------------------------------------------------------------------------+
| No documents found. Generate your first document to see it here.               |
+--------------------------------------------------------------------------------+
```

## Screen 7: Document Library - Detail View

Purpose: read a saved document.

```text
+--------------------------------------------------------------------------------+
| [Back] Offer Letter                                                            |
|        v1.0 - Created 01 Jun 2026                                               |
|--------------------------------------------------------------------------------|
| Candidate Details                                                              |
| +----------------------------------------------------------------------------+ |
| | Dear Rohan Sharma, ...                                                      | |
| +----------------------------------------------------------------------------+ |
|                                                                                |
| Compensation                                                                   |
| +----------------------------------------------------------------------------+ |
| | Your annual compensation will be...                                         | |
| +----------------------------------------------------------------------------+ |
+--------------------------------------------------------------------------------+
```

## Screen 8: RAG Assistant - Query Mode

Purpose: answer document questions with citations and retrieval inspection.

```text
+--------------------------------------------------------------------------------+
| RAG Document Assistant                                                         |
| Ask questions grounded in your Notion document library.                        |
|                                                                                |
| Filters                                                                        |
| +----------------------------------------------------------------------------+ |
| | Doc Type [ Policy              ] Department [ Human Resources             ] | |
| +----------------------------------------------------------------------------+ |
|                                                                                |
| Mode: (Query) (Compare) (Summarize) (Evaluate)                                 |
|--------------------------------------------------------------------------------|
| User                                                                           |
|   What is the notice period?                                                   |
|                                                                                |
| Assistant                                                                      |
|   The notice period is ... [Source 1]                                          |
|   Confidence: High                                                             |
|                                                                                |
| Sources                                                                        |
| - [1] Employment Contract > Notice Period                                      |
|                                                                                |
| Retrieval inspector                                                            |
| + [1] Employment Contract > Notice Period | score: 0.87                        |
|   Doc Type: Employment Contract                                                |
|   Department: Human Resources                                                  |
|   Retrieved Text: ...                                                          |
|                                                                                |
| [ Ask a question about your documents... ]                                     |
+--------------------------------------------------------------------------------+
```

## Screen 9: RAG Assistant - Compare Mode

Purpose: compare two document types on a specific question.

```text
+--------------------------------------------------------------------------------+
| Compare Two Document Types                                                     |
|                                                                                |
| Document Type A                         Document Type B                        |
| [ Employment Contract                ] [ Offer Letter                       ]  |
|                                                                                |
| What to compare?                                                               |
| [ notice period clauses                                                     ]  |
|                                                                                |
| [Compare]                                                                      |
|--------------------------------------------------------------------------------|
| Comparison Result                                                              |
| Q: notice period clauses                                                       |
|                                                                                |
| Executive summary...                                                           |
|                                                                                |
| Aspect | Document A | Document B | Difference / Risk                           |
| ...                                                                            |
|                                                                                |
| Sources                                                                        |
| - [1] Employment Contract > Notice Period                                      |
| - [2] Offer Letter > Terms                                                     |
+--------------------------------------------------------------------------------+
```

## Screen 10: RAG Assistant - Summarize Mode

Purpose: summarize a document type or department.

```text
+--------------------------------------------------------------------------------+
| Summarize a Document                                                           |
|                                                                                |
| Document Type to Summarize                                                     |
| [ Leave Policy                                                              ]  |
|                                                                                |
| Department (optional)                                                          |
| [ Human Resources                                                           ]  |
|                                                                                |
| [Summarize]                                                                    |
|--------------------------------------------------------------------------------|
| Summary                                                                        |
| Q: Summarize: Leave Policy                                                     |
|                                                                                |
| The leave policy explains...                                                   |
|                                                                                |
| Sources                                                                        |
| - [1] Leave Policy > Eligibility                                               |
+--------------------------------------------------------------------------------+
```

## Screen 11: RAG Assistant - Evaluate Mode

Purpose: test multiple RAG questions and inspect aggregate quality metrics.

```text
+--------------------------------------------------------------------------------+
| Evaluate RAG Pipeline                                                          |
|                                                                                |
| Enter questions (one per line)                                                 |
| +----------------------------------------------------------------------------+ |
| | what is the notice period?                                                  | |
| | what are the leave policies?                                                | |
| +----------------------------------------------------------------------------+ |
|                                                                                |
| [Run Evaluation]                                                               |
|--------------------------------------------------------------------------------|
| Results - 2 questions                                                          |
|                                                                                |
| +----------------------------+ +---------------------------------------------+ |
| | Faithfulness: 0.91         | | Answer Relevancy: 0.88                     | |
| +----------------------------+ +---------------------------------------------+ |
|                                                                                |
| + Q: what is the notice period?...                                             |
|   Faithfulness: 0.94                                                           |
|   Answer Relevancy: 0.90                                                       |
|   Answer text...                                                               |
+--------------------------------------------------------------------------------+
```

## Screen 12: Agent Assistant

Purpose: provide a conversational support interface over the document knowledge base and tickets.

```text
+--------------------------------------------------------------------------------+
| Agent Assistant                                                                |
| Chat with the LangGraph agent and raise support tickets when needed.           |
|                                                                                |
| +--------------------------+ +----------------------+ +----------------------+ |
| | Session: New             | | [New Session]        | | [Refresh Tickets]    | |
| +--------------------------+ +----------------------+ +----------------------+ |
|--------------------------------------------------------------------------------|
| User                                                                           |
|   What is the reimbursement policy for travel?                                 |
|                                                                                |
| Assistant                                                                      |
|   Employees can claim travel expenses when...                                  |
|   Intent: question | Confidence: high | Trace: a1b2c3d4                       |
|                                                                                |
| Sources                                                                        |
| - Travel Expense Policy > Eligibility                                          |
|                                                                                |
| User                                                                           |
|   What about a policy that is not available?                                   |
|                                                                                |
| Assistant                                                                      |
|   I could not find this information in the knowledge base.                     |
|   Would you like to raise a support ticket?                                    |
|   Intent: question | Confidence: out_of_kb | Trace: e5f6g7h8                  |
|                                                                                |
| [Create Ticket]                                                                |
|                                                                                |
| [ Ask the agent... ]                                                           |
|--------------------------------------------------------------------------------|
| Tickets                                                                        |
| +----------------------------------------------------------------------------+ |
| | Travel policy clarification                                                 | |
| | Status: Open | Priority: Medium | Session: abc123                          | |
| | Open in Notion                                                              | |
| +----------------------------------------------------------------------------+ |
+--------------------------------------------------------------------------------+
```

## Agent State Flow

```text
New Session
  |
  +-- User message
        |
        +-- intent = unclear
        |     -> ask clarification
        |
        +-- intent = question
        |     -> retrieve documents
        |     -> evaluate confidence
        |     -> answer if high confidence
        |     -> offer ticket if low or out-of-kb
        |
        +-- intent = create_ticket
        |     -> find previous user question when needed
        |     -> check duplicate ticket
        |     -> create Notion ticket
        |
        +-- intent = ticket_status
              -> fetch tickets for session
```

## Responsive Behavior

Streamlit handles most responsive behavior automatically. The intended behavior is:

- Desktop: form and document preview sit side by side in the Generate tab.
- Tablet: columns remain readable but may become tighter.
- Mobile: columns stack vertically; forms appear before document output.
- Chat inputs remain fixed at the bottom of the Streamlit chat area.

## Key Empty and Error States

| Area | State | User Message |
| --- | --- | --- |
| Generate | Backend unavailable | No departments found. Check the backend is running. |
| Generate | Waiting for output | Your document will appear here. |
| Library | No saved documents | No documents found. Generate your first document to see it here. |
| RAG Query | No retrieval match | I could not find relevant documents. |
| Agent | No response | No response. |
| Agent | No ticket data loaded | Click Refresh Tickets to load support tickets. |
| Agent | Ticket creation failure | Could not create ticket. |

## Recommended Future UX Improvements

- Convert the Agent tab into a more natural conversational chatbot while keeping the existing ticket routing and Notion ticket creation flow.
- Add visible chat history loading for previous agent sessions.
- Replace text-only buttons with icon-supported actions where practical.
- Add admin UI for departments, templates, and form fields.
- Add clearer ingestion status for RAG indexing.
- Add ticket filters by status, priority, and session.
