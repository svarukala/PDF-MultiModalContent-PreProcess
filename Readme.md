# PDF MultiModal Analysis — Architecture Overview

## What This Project Does

This is an Azure Durable Function that converts pharmaceutical PDF documents (100+ pages) into self-contained Markdown files. The PDFs contain charts, line diagrams, tables with numerical data, and drug performance metrics. The system extracts all text as Markdown and replaces every visual element (chart, graph, diagram) with a detailed AI-generated text description — so the final output is a single `.md` file that fully represents the document without needing images.

## High-Level Architecture

```
                          ┌──────────────────────┐
                          │   Client / Script     │
                          │   (test_local.py)     │
                          └──────────┬───────────┘
                                     │ POST /api/pdf
                                     │ (raw PDF bytes + X-Filename header)
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Azure Durable Functions App  (function_app.py)                     │
│                                                                     │
│  ┌───────────────────────────────────────────┐                      │
│  │  HTTP Starter (http_start)                │                      │
│  │  - Validates PDF (magic bytes, 200MB max) │                      │
│  │  - Sanitizes filename                     │                      │
│  │  - Uploads PDF to Blob Storage            │──────┐               │
│  │  - Starts orchestrator                    │      │               │
│  │  - Returns polling status URL             │      │               │
│  └──────────────────┬────────────────────────┘      │               │
│                     │                                │               │
│                     ▼                                │               │
│  ┌───────────────────────────────────────────┐      │               │
│  │  Orchestrator                             │      │               │
│  │  (pdf_processing_orchestrator)            │      │               │
│  │  No timeout — runs indefinitely           │      │               │
│  │                                           │      │               │
│  │  Step 1: call parse_pdf                   │      │               │
│  │  Step 2: FAN-OUT describe_figure (N)      │      │               │
│  │  Step 3: FAN-IN  (task_all)               │      │               │
│  │  Step 4: call assemble_markdown           │      │               │
│  │  Step 5: call save_to_blob                │      │               │
│  └───────────────────────────────────────────┘      │               │
│                                                      │               │
└──────────────────────────────────────────────────────┼───────────────┘
                                                       │
                     ┌─────────────────────────────────┘
                     ▼
        ┌────────────────────┐            ┌────────────────────┐
        │  Azure Blob Storage│            │  Azure Blob Storage│
        │  pdf-output/       │            │  pdf-input/        │
        │  (final .md files) │            │  (uploaded PDFs)   │
        └────────────────────┘            └────────────────────┘
```

## Azure Services Used

| Service | Purpose | Configuration |
|---------|---------|---------------|
| **Azure Functions** (Durable, Python v2) | Hosts the entire pipeline as a serverless app | DFApp with FUNCTION auth level |
| **Azure Document Intelligence** | Parses PDFs into Markdown text + extracts figures as PNG images | `prebuilt-layout` model, API `2024-11-30` |
| **Azure OpenAI** (GPT-4.1) | Describes each extracted figure using multimodal vision | `2025-04-01-preview` API, `temperature=0.1` |
| **Azure Blob Storage** | Stores input PDFs and output Markdown files | Two containers: `pdf-input`, `pdf-output` |

## Pipeline: Step-by-Step Detail

### Step 0: HTTP Starter (`http_start`)

**Trigger:** `POST /api/pdf`

The client sends the raw PDF bytes in the request body with an optional `X-Filename` header. The starter function:

1. **Validates the input:**
   - Rejects empty bodies (400)
   - Rejects files over 200 MB (413)
   - Checks for `%PDF-` magic bytes to confirm it's actually a PDF (400)
2. **Sanitizes the filename** — strips any characters that aren't `a-z A-Z 0-9 . _ -` to prevent path traversal or blob naming issues
3. **Uploads the PDF** to the `pdf-input` blob container with a timestamped name (e.g., `20260226T143000Z_RxInsights_5657563.pdf`)
4. **Starts the Durable orchestrator** with the blob reference as input
5. **Returns a status-check URL** — the client polls this URL to track progress and retrieve results

**Why a Durable orchestrator?** Standard Azure Functions have a 10-minute timeout on Consumption plans. A 100+ page pharma PDF with dozens of charts can take 15–30 minutes to fully process. The Durable Functions orchestrator has **no timeout limit** — it coordinates long-running work by checkpointing state to Azure Table Storage.

### Step 1: Parse PDF (`parse_pdf` activity)

**Input:** Blob reference (container + blob name)
**Output:** Draft Markdown string + list of extracted figure images

This activity:

1. **Downloads the PDF** from blob storage
2. **Calls Azure Document Intelligence** using the `prebuilt-layout` model with two critical parameters:
   - `output_content_format=MARKDOWN` — the service converts all text, headings, lists, and tables into well-structured Markdown. Tables are rendered as HTML `<table>` elements (to handle merged cells/multirow headers)
   - `output=[FIGURES]` — the service identifies every chart, graph, photo, and diagram in the PDF and crops each one as a separate PNG image
3. **Fetches each figure image** via `get_analyze_result_figure()`, which returns the cropped PNG bytes. Each figure is base64-encoded for transport through the orchestrator
4. **Returns** the draft Markdown (with `![](figures/1.1)` placeholders where figures were) plus a list of figures, each containing:
   - `id` — the figure identifier (e.g., `1.1` for page 1, figure 1)
   - `base64_png` — the cropped image as base64 (or `None` if extraction failed)
   - `caption` — any caption text Document Intelligence detected

**Failure handling:** If a specific figure image can't be fetched (network error, etc.), the figure's `base64_png` is set to `None` and processing continues. The figure will get a fallback placeholder in the final output rather than killing the entire job.

### Step 2: Fan-Out — Describe Figures (`describe_figure` activities, parallel)

**Input per figure:** Base64 PNG image + surrounding text context (~500 chars before/after the figure in the Markdown) + caption
**Output per figure:** Markdown description of the visual

For every figure extracted in Step 1, the orchestrator spawns a separate `describe_figure` activity **in parallel**. This is the Durable Functions "fan-out" pattern — if a PDF has 30 charts, all 30 GPT calls run concurrently.

Each activity:

1. **Checks if the image exists** — if `base64_png` is `None` (extraction failed), returns a fallback: `[Figure image could not be retrieved.]`
2. **Extracts surrounding context** — the orchestrator passes ~500 characters of Markdown text from before and after the figure reference. This gives GPT context about what the figure relates to (e.g., "Q3 revenue for Drug X was...")
3. **Sends a multimodal request to Azure OpenAI:**
   - **System prompt** (pharma-specific): instructs the model to act as a pharmaceutical data analyst and include trends, axis labels, units, numerical values, drug names, dosage info, time periods, statistical annotations, and legends
   - **User message:** the surrounding text context + the figure image (as a `data:image/png;base64,...` data URL with `detail: high` for maximum resolution)
   - **Parameters:** `max_tokens=2000`, `temperature=0.1` (low temperature for factual, precise descriptions)
4. **Handles null GPT responses** — if the model returns empty content (content filter, refusal), inserts `[Figure description could not be generated.]`
5. **Prepends the caption** if Document Intelligence detected one

**Retry policy:** Each `describe_figure` call retries up to 3 times with a 5-second initial backoff. If GPT fails on one chart, it retries without affecting other charts.

### Step 3: Fan-In (`task_all`)

The orchestrator calls `context.task_all(description_tasks)` which **suspends until every parallel `describe_figure` activity completes**. It then collects all descriptions into a single list.

If there are zero figures in the PDF (text-only document), the fan-out/fan-in is skipped entirely.

### Step 4: Assemble Final Markdown (`assemble_markdown` activity)

**Input:** Draft Markdown + all figure descriptions
**Output:** Final self-contained Markdown string

This activity:

1. **Builds a lookup map** from `figure_id` → `description`
2. **Runs two regex replacement passes:**
   - First: replaces `<figure>![](figures/X)</figure>` patterns (the tagged format Document Intelligence uses)
   - Second: replaces bare `![](figures/X)` patterns (fallback format)
3. **Each figure placeholder is replaced** with the GPT description wrapped in horizontal rules:
   ```
   ---
   [GPT-generated description of the chart/diagram]
   ---
   ```
4. If a figure has no matching description, inserts `[Figure description unavailable.]`

### Step 5: Save to Blob (`save_to_blob` activity)

**Input:** Final Markdown string + original filename
**Output:** Blob URL

This activity:

1. **Strips the `.pdf` extension** from the original filename
2. **Generates a timestamped blob name** (e.g., `RxInsights_5657563_20260226T143500Z.md`)
3. **Uploads to the `pdf-output` container** with `content_type: text/markdown`
4. **Returns the blob URL** — this is what the client receives when polling the status endpoint

**Retry policy:** 3 attempts with 5-second backoff (handles transient storage errors).

### Final Response

The orchestrator returns metadata only (not the full Markdown — see Design Decisions):

```json
{
  "status": "completed",
  "blob_url": "https://storage.blob.core.windows.net/pdf-output/RxInsights_5657563_20260226T143500Z.md",
  "figures_processed": 24,
  "figures_described": 24
}
```

The client retrieves this by polling the status-check URL returned in Step 0.

## Project Structure

```
PDF-MultiModal-Analysis/
├── function_app.py              # All functions in one file (v2 decorator model)
├── host.json                    # Durable Functions config + extension bundle
├── local.settings.json          # Local dev credentials (gitignored)
├── requirements.txt             # Python dependencies
├── .env.example                 # Template for required env vars
├── .gitignore
├── .funcignore                  # Excludes files from Azure deployment
├── test_local.py                # Test script: upload PDF, poll, download result
└── docs/
    ├── architecture.md          # This file
    └── plans/
        ├── 2026-02-25-pdf-vision-to-markdown-design.md
        └── 2026-02-25-pdf-vision-to-markdown-implementation.md
```

### Why a Single File?

The entire app lives in `function_app.py` (~450 lines). Azure Functions Python v2 model uses a `DFApp` instance with decorators — the HTTP starter, orchestrator, and all 4 activities are registered on the same `app` object. For a project of this scope, a single file keeps deployment simple and avoids circular import issues. It can be split into modules later if the project grows.

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `azure-functions` | latest | Azure Functions host SDK |
| `azure-functions-durable` | 1.5.0 | Durable Functions orchestration (fan-out/fan-in, retries, checkpointing) |
| `azure-ai-documentintelligence` | 1.0.2 | Document Intelligence SDK (PDF parsing, figure extraction) |
| `openai` | >=2.24.0 | Azure OpenAI SDK (multimodal vision API via `AzureOpenAI` client) |
| `azure-identity` | latest | Azure AD/Entra authentication (available for production use) |
| `azure-storage-blob` | >=12.20.0 | Blob Storage SDK (upload/download PDFs and Markdown) |

**Runtime:** Python 3.12 (3.14 has compatibility issues with the Durable Functions binding converter)

## Environment Variables

| Variable | Example | Required |
|----------|---------|----------|
| `AzureWebJobsStorage` | `DefaultEndpointsProtocol=https;AccountName=...` | Yes — Durable Functions uses this for orchestration state |
| `AZURE_STORAGE_CONNECTION_STRING` | Same as above (can be same storage account) | Yes — for PDF/Markdown blob operations |
| `DOCUMENTINTELLIGENCE_ENDPOINT` | `https://your-resource.cognitiveservices.azure.com/` | Yes |
| `DOCUMENTINTELLIGENCE_API_KEY` | `FQLQ49...` | Yes |
| `AZURE_OPENAI_ENDPOINT` | `https://your-resource.openai.azure.com/` | Yes — base URL only, no `/openai/v1/` suffix |
| `AZURE_OPENAI_API_KEY` | `46REI...` | Yes |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | `gpt-4.1` | Yes — the model deployment name in Azure AI Foundry |
| `PDF_INPUT_CONTAINER` | `pdf-input` | No (default: `pdf-input`) |
| `PDF_OUTPUT_CONTAINER` | `pdf-output` | No (default: `pdf-output`) |

## Design Decisions

### 1. Durable Functions over Simple Functions

Standard Azure Functions have a 10-minute timeout (Consumption plan). A 100+ page pharma PDF with 30+ charts can take 15–30 minutes. The Durable Functions orchestrator has no timeout — it persists state to Table Storage between activity calls and can resume after any duration.

### 2. Fan-Out/Fan-In for Figure Description

Each figure is described independently by GPT. By fanning out N parallel activity calls, a PDF with 30 charts processes all 30 concurrently rather than sequentially. This reduces total processing time from `N × ~15 seconds` to roughly `~15 seconds` (bounded by the slowest single GPT call).

### 3. Metadata-Only Orchestrator Output

The orchestrator return value is persisted in Durable Functions history (Azure Table Storage), which has a 1 MB entity size limit. A 100+ page PDF's Markdown output can easily exceed this. The full Markdown is saved to Blob Storage in Step 5, and only the blob URL is returned through the orchestrator.

### 4. Singleton SDK Clients

`BlobServiceClient`, `DocumentIntelligenceClient`, and `AzureOpenAI` are expensive to initialize (TCP connections, TLS handshakes). They're created once via lazy initialization and reused across all activity invocations within the same function host process.

### 5. Surrounding Text Context for GPT

When describing a figure, GPT receives ~500 characters of text from before and after the figure's position in the Markdown. This gives the model crucial context — e.g., if the text says "Figure 3 shows Q3 revenue for DrugX", GPT can correlate axis labels with the drug name even if the chart itself doesn't mention it explicitly.

### 6. AzureOpenAI Client (Classic Path)

The code uses `AzureOpenAI(api_version="2025-04-01-preview")` rather than the newer v1 path (`OpenAI(base_url=...)`). The classic path with explicit API versioning provides more stability for production workloads — the v1 path is newer and may have breaking changes.

### 7. Raw Body Upload over Multipart

The HTTP starter accepts raw PDF bytes in the request body (`Content-Type: application/pdf`) rather than multipart/form-data. This is simpler for single-file uploads and avoids multipart parsing overhead. The filename is passed via the `X-Filename` header.

## Error Handling Summary

| Failure Point | Behavior |
|---------------|----------|
| Invalid PDF (not PDF, too large, empty) | HTTP 400/413 returned immediately |
| Malicious filename in header | Sanitized to alphanumeric + `._-` only |
| Document Intelligence fails | `parse_pdf` raises, orchestrator fails immediately (fatal — nothing to process) |
| Single figure image extraction fails | `base64_png` set to `None`, fallback text inserted, other figures unaffected |
| GPT fails for one figure | Retried 3× with 5s backoff; after exhaustion, orchestrator fails that figure |
| GPT returns empty/filtered content | Fallback: `[Figure description could not be generated.]` |
| Blob container doesn't exist | Auto-created; `ResourceExistsError` caught if it already exists |
| Blob upload fails | `save_to_blob` retried 3× with 5s backoff |

## How to Run Locally

1. Fill in `local.settings.json` with Azure credentials
2. Create a Python 3.12 virtual environment: `py -3.12 -m venv .venv`
3. Activate: `.venv\Scripts\activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Start the function: `func start`
6. Test: `python test_local.py`

## How to Deploy to Azure

```bash
# Login
az login

# Create a Function App (Python 3.12, Consumption plan)
az functionapp create \
  --resource-group pdf-processing-rg \
  --consumption-plan-location eastus2 \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --name pdf-multimodal-func \
  --storage-account stmultimodalpdfeb1fba

# Set environment variables
az functionapp config appsettings set \
  --name pdf-multimodal-func \
  --resource-group pdf-processing-rg \
  --settings \
    DOCUMENTINTELLIGENCE_ENDPOINT="..." \
    DOCUMENTINTELLIGENCE_API_KEY="..." \
    AZURE_OPENAI_ENDPOINT="..." \
    AZURE_OPENAI_API_KEY="..." \
    AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4.1" \
    AZURE_STORAGE_CONNECTION_STRING="..."

# Deploy
func azure functionapp publish pdf-multimodal-func
```
