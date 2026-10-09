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
3. **Uploads the PDF** to the `pdf-input` blob container under a unique job ID (e.g., `{job_id}/RxInsights_5657563.pdf`), preventing same-name uploads from colliding
4. **Starts the Durable orchestrator** with the blob reference as input
5. **Returns a status-check URL** — the client polls this URL to track progress and retrieve results

**Why a Durable orchestrator?** Standard Azure Functions have a 10-minute timeout on Consumption plans. A 100+ page pharma PDF with dozens of charts can take 15–30 minutes to fully process. The Durable Functions orchestrator has **no timeout limit** — it coordinates long-running work by checkpointing state to Azure Table Storage.

### Step 1: Parse PDF (`parse_pdf` activity)

**Input:** Blob reference (container + blob name)
**Output:** Draft Markdown string + list of extracted figure images

This activity:

1. **Downloads the PDF** from blob storage
2. **Calls Azure Document Intelligence** using the `prebuilt-layout` model:
   - `output_content_format=MARKDOWN` — the service converts all text, headings, lists, and tables into well-structured Markdown. Tables are rendered as HTML `<table>` elements (to handle merged cells/multirow headers)
   - `output=[FIGURES]` — the service identifies every chart, graph, photo, and diagram in the PDF and crops each one as a separate PNG image
   - `string_index_type=unicodeCodePoint` — figure offsets match Python string indices, including documents with emoji and other supplementary Unicode characters
3. **Fetches each figure image** via `get_analyze_result_figure()`, which returns the cropped PNG bytes. Each figure is base64-encoded for transport through the orchestrator
4. **Saves the exact draft Markdown** to `pdf-output/{job_id}/interim.md`.
5. **Returns** the draft Markdown (typically containing `<figure>` blocks with OCR text and captions, not image links) plus a list of figures, each containing:
   - `id` — the figure identifier (e.g., `1.1` for page 1, figure 1)
   - `base64_png` — the cropped image as base64 (or `None` if extraction failed)
   - `caption` — any caption text Document Intelligence detected
   - `spans` — offsets and lengths locating the figure in the original Markdown

**Failure handling:** If a specific figure image can't be fetched (network error, etc.), the figure's `base64_png` is set to `None` and processing continues. The figure will get a fallback placeholder in the final output rather than killing the entire job.

### Step 2: Fan-Out — Describe Figures (`describe_figure` activities, parallel)

**Input per figure:** Base64 PNG image + surrounding text context (~500 chars before/after the figure in the Markdown) + caption
**Output per figure:** Markdown description of the visual

For every figure extracted in Step 1, the orchestrator schedules a separate
`describe_figure` activity in **batches of two**, updating progress after each
batch. `host.json` also limits execution to **2 concurrent activities per host**
to reduce bursts against the development model's token quota.

Each activity:

1. **Checks if the image exists** — if `base64_png` is `None` (extraction failed), returns a fallback: `[Figure image could not be retrieved.]`
2. **Extracts surrounding context** — the orchestrator passes ~500 characters of Markdown text from before and after the figure reference. This gives GPT context about what the figure relates to (e.g., "Q3 revenue for Drug X was...")
3. **Sends a multimodal request to Azure OpenAI:**
   - **System prompt** (pharma-specific): instructs the model to act as a pharmaceutical data analyst and include trends, axis labels, units, numerical values, drug names, dosage info, time periods, statistical annotations, and legends
   - **User message:** the surrounding text context + the figure image (as a `data:image/png;base64,...` data URL with `detail: high` for maximum resolution)
   - **Parameters:** `max_tokens=2000`, `temperature=0.1` (low temperature for factual, precise descriptions)
4. **Handles null GPT responses** — if the model returns empty content (content filter, refusal), inserts `[Figure description could not be generated.]`
5. **Prepends the caption** if Document Intelligence detected one

**Retry policy:** Each `describe_figure` activity gets up to 3 attempts with a
60-second initial backoff, allowing the model's token-rate window to refill after
throttling. The OpenAI SDK also performs its own transient-error retries. Exhausted
activity retries fail the orchestration rather than silently omitting a figure.

### Step 3: Fan-In (`task_all`)

For each batch, the orchestrator calls `context.task_all(tasks)` and suspends
until both activities complete. It collects all descriptions into one list
and reports the completed figure count before starting the next batch.

If there are zero figures in the PDF (text-only document), the fan-out/fan-in is skipped entirely.

### Step 4: Assemble Final Markdown (`assemble_markdown` activity)

**Input:** Draft Markdown + figure IDs/spans + all figure descriptions
**Output:** Final self-contained Markdown string

This activity:

1. **Requires exactly one nonempty description per figure.** Missing or duplicate descriptions fail explicitly.
2. **Uses original character spans** to locate figures, expanding a span to its enclosing `<figure>` block when appropriate. Legacy `![](figures/X)` links are also supported.
3. **Merges overlapping spans** so multiple images in one figure block retain all their descriptions. Text outside the replaced spans is preserved.
4. **Inserts each description once**, wrapped in horizontal rules and identified by `<!-- Figure ID -->`.
5. **Appends figures without text positions** under `Additional figure descriptions` and logs a warning, rather than guessing their locations from list order or dropping them.

The raw interim file remains unchanged. Figure IDs and spans, not the number or
order of HTML blocks, are the source of truth: a document can have more extracted
images than `<figure>` blocks.

### Step 5: Save to Blob (`save_to_blob` activity)

**Input:** Final Markdown string + original filename
**Output:** Blob URL

This activity:

1. **Uses the unique job ID** to keep artifacts from separate uploads isolated
2. **Names the final artifact** `{job_id}/final.md` (legacy activity inputs without a job ID retain timestamped filenames)
3. **Uploads to the `pdf-output` container** with `content_type: text/markdown`
4. **Returns the blob URL** — this is what the client receives when polling the status endpoint

**Retry policy:** 3 attempts with 5-second backoff (handles transient storage errors).

### Final Response

The orchestrator returns metadata only (not the full Markdown — see Design Decisions):

```json
{
  "status": "completed",
  "blob_url": "https://storage.blob.core.windows.net/pdf-output/{job_id}/final.md",
  "figures_processed": 24,
  "figures_described": 24,
  "figures_with_fallback": 0
}
```

The client retrieves this by polling the status-check URL returned in Step 0.

## Project Structure

```
PDF-MultiModal-Analysis/
├── function_app.py              # All functions in one file (v2 decorator model)
├── figure_markdown.py           # Span mapping and lossless description insertion
├── web/index.html              # Self-contained upload/progress/file viewer
├── host.json                    # Durable Functions config + extension bundle
├── local.settings.json          # Local dev credentials (gitignored)
├── requirements.txt             # Python dependencies
├── .env.example                 # Template for required env vars
├── .gitignore
├── .funcignore                  # Excludes files from Azure deployment
├── test_local.py                # Test script: upload PDF, poll, download result
├── tests/                       # Python regressions and Playwright browser checks
└── docs/
    ├── architecture.md          # This file
    └── plans/
        ├── 2026-02-25-pdf-vision-to-markdown-design.md
        └── 2026-02-25-pdf-vision-to-markdown-implementation.md
```

### Why a Single File?

Azure Functions Python v2 registers the HTTP routes, orchestrator, and all four
activities on one `DFApp` in `function_app.py`. Pure figure-mapping logic lives in
`figure_markdown.py` for focused regression coverage. The viewer is a standalone
HTML file served by the same host; no frontend build or separate server is needed.

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

Each figure is described independently by GPT. The orchestrator schedules batches
of two and reports progress between batches; the host also executes at most two
activities concurrently. This conservative default suits the development deployment's quota;
it is not a token-rate limiter. Multiple scaled-out hosts share the Azure OpenAI
quota, so concurrency and deployment capacity must be reviewed before scaling.

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
| GPT fails for one figure | Up to 3 activity attempts with 60s initial backoff; after exhaustion, the orchestration fails |
| GPT returns empty/filtered content | Fallback: `[Figure description could not be generated.]` |
| Blob container doesn't exist | Auto-created; `ResourceExistsError` caught if it already exists |
| Blob upload fails | `save_to_blob` retried 3× with 5s backoff |
| Figure has no text span | Description explicitly appended; warning logged |
| Invalid spans, missing/duplicate descriptions | Assembly fails instead of reporting incomplete output as success |

## How to Run Locally

The Functions host and storage run locally; **PDF parsing and figure descriptions
still call Azure Document Intelligence and Azure OpenAI**. There is no offline AI
emulator. You can start the host and check request validation before configuring
those services, but valid PDFs require real endpoints and keys.

Prerequisites on Windows: **Python 3.12** (`py -3.12`) and **Node.js 22 or 24 LTS**
with npm. Run these PowerShell commands from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
Copy-Item local.settings.json.example local.settings.json
```

Copy the settings template only on first setup; do not overwrite existing
credentials. `local.settings.json` is gitignored. The Functions host reads it
automatically; it does **not** load `.env`. The `.env.example` file is a reference
for environments that explicitly load environment variables.

Start storage in one terminal:

```powershell
npm run storage
```

This runs the repository-pinned Azurite emulator on loopback ports **10000**
(Blob), **10001** (Queue), and **10002** (Table). Its data persists in the
gitignored `.azurite` directory. Both storage settings in the template use
`UseDevelopmentStorage=true`; no Azure storage account is needed locally.
The emulator skips API-version header checks because current Azure SDKs may
request a newer API version than Azurite advertises. This does not add support
for new storage features; the app uses standard blob upload/download operations.

In a second terminal, start the Functions host:

```powershell
npm start
```

The startup script selects `.venv` and runs the repository-pinned Azure Functions
Core Tools v4. Leave both terminals running; use **Ctrl+C** in each to stop.
Use `npm start -- --verbose` for detailed startup diagnostics. The first startup
downloads the Azure Functions extension bundle and requires internet access.
The upload endpoint is `http://localhost:7071/api/pdf`. Local Core Tools does not
enforce function keys by default; do not expose this development host publicly.

### Browser page

Open **http://localhost:7071/api/viewer**. Choose a PDF and click **Process PDF**.
The page uploads to the same `/api/pdf` endpoint, polls the real Durable job,
and shows extraction, GPT batches, assembly, and storage milestones. It is an
activity-level progress view, not a trace of every SDK retry or HTTP request.
The most recent 12 events are persisted in custom status; the open page retains
up to 250 events. Refresh restores the job from the `job` URL parameter.

The exact **interim Markdown** appears once parsing finishes. The **final
Markdown** appears after assembly and storage complete. Each has a download button.
Previews intentionally show Markdown source as text (including HTML tables and
figure tags), rather than executing or rendering untrusted document HTML.
Downloads go to your browser's download location, not automatically to `output`.
AI fallback descriptions are counted separately from successfully described figures.

| Route | Purpose |
|-------|---------|
| `GET /api/viewer` | Upload and comparison page |
| `POST /api/pdf` | Raw PDF upload; HTTP 202 with Durable management URLs and `jobStatusUrl` |
| `GET /api/jobs/{job_id}` | Bounded progress summary, counts, error, and artifact URLs |
| `GET /api/jobs/{job_id}/files/interim` | Original Document Intelligence Markdown as plain text |
| `GET /api/jobs/{job_id}/files/final` | Assembled Markdown as plain text |

Artifacts use private storage and are streamed through Functions; Azure AI and
storage credentials are never sent to the page. These routes share the app's
function-key authorization when deployed. The page has an optional function-key
field for requests; this is a development diagnostic UI, **not multi-user
authentication or per-user document authorization**. Before a public deployment,
add appropriate identity/access controls. Do not share job management URLs or keys.

Existing completed jobs from before the viewer was added have no per-job artifact
files or UI progress; rerun a PDF to produce them. Stop or drain active
orchestrations before updating orchestrator code, because Durable replay depends
on the recorded activity sequence.

### Automated checks

With the local host running:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npx playwright test
```

Browser checks use installed Microsoft Edge and mock Azure job responses; they
do not send documents to Azure or incur model charges. A real PDF run is required
to exercise the configured Azure services.

A request-validation check that does not call any Azure AI services:

```powershell
curl.exe -i -X POST http://localhost:7071/api/pdf -H "Content-Type: application/pdf" --data-binary "not a PDF"
```

Expected response: **HTTP 400**, `Request body is not a valid PDF.`

When the Azure AI resources are ready, fill in the five `DOCUMENTINTELLIGENCE_*`
and `AZURE_OPENAI_*` values in `local.settings.json`, then restart the Functions
host. Use the actual vision-capable model deployment name, not just the model
family; `gpt-4.1` is the template default. Keep keys out of source control.

Submit a PDF:

```powershell
.\.venv\Scripts\python.exe test_local.py "C:\path\to\document.pdf"
```

The client reads local settings (existing environment variables take precedence),
polls for up to one hour, and downloads the Markdown to this repository's `output`
directory. Use `--output-dir`, `--url`, or `--timeout` to override those defaults.
Failed requests, failed orchestrations, and polling timeouts exit with a nonzero
status. No Azure resources are created or deployed by this local setup.

### Configured development Azure resources

The development resources are in subscription
`dad4fa0b-aa0d-42bc-8ec7-a5e83450c6f0`, tenant
`67c96cd6-4a95-46ee-ac9b-8ee13ae256c4`, resource group
`rg-pdf-multimodal-dev`, in **East US 2**.

| Resource | Name | Configuration |
|----------|------|---------------|
| Document Intelligence | `di-pdf-multimodal-dad4fa0b` | S0, `prebuilt-layout` |
| Azure OpenAI | `aoai-pdf-multimodal-dad4fa0b` | S0 |
| Model deployment | `gpt-4.1` | Version `2025-04-14`, Global Standard, 50,000 TPM allocation |
| Storage | `stpdfmultidad4fa0b` | Standard LRS, TLS 1.2 minimum, anonymous blob access disabled |
| Blob containers | `pdf-input`, `pdf-output` | Private |

These are usage-billed development resources, not an Azure-hosted deployment of
the Functions app. Global Standard model processing is not restricted to East US 2.
The local host continues to use Azurite; the Azure storage account is available
for the later deployment.

To populate or refresh local AI credentials without printing keys:

```powershell
# If authentication is needed:
az login --tenant 67c96cd6-4a95-46ee-ac9b-8ee13ae256c4 --use-device-code

.\scripts\configure-azure-local.ps1
```

Sign in as `svarukala@powercattools.onmicrosoft.com`. The script explicitly targets
the development subscription, preserves storage settings and other local values,
and only updates the five AI settings. It accepts parameters for a different
subscription, resource group, account names, or deployment name. Restart
`npm start` after updating settings. Never commit `local.settings.json`.

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
