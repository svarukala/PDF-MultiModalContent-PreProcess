# PDF Vision-to-Markdown Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an Azure Durable Function that converts pharma PDFs (100+ pages) into markdown with AI-generated descriptions of all charts, diagrams, and tables.

**Architecture:** HTTP-triggered Durable Function using fan-out/fan-in. Document Intelligence parses PDF to markdown + extracts figure images. GPT-5.2 describes each figure in parallel. Results assembled into a single self-contained markdown file saved to Blob Storage.

**Tech Stack:** Python 3.11, Azure Functions v2 model, azure-functions-durable 1.5.0, azure-ai-documentintelligence 1.0.2, openai 2.24.0, azure-storage-blob

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `host.json`
- Create: `.gitignore`
- Create: `.funcignore`
- Create: `.env.example`
- Create: `local.settings.json`

**Step 1: Create requirements.txt**

```txt
azure-functions
azure-functions-durable==1.5.0
azure-ai-documentintelligence==1.0.2
openai>=2.24.0
azure-identity
azure-storage-blob>=12.20.0
```

**Step 2: Create host.json**

```json
{
  "version": "2.0",
  "extensions": {
    "durableTask": {
      "hubName": "PdfProcessingHub",
      "storageProvider": {
        "type": "azure_storage"
      }
    }
  },
  "logging": {
    "logLevel": {
      "DurableTask": "Warning",
      "Function": "Information"
    }
  },
  "functionTimeout": "00:10:00"
}
```

**Step 3: Create .gitignore**

```
__pycache__/
.python_packages/
.venv/
local.settings.json
.env
*.pyc
.funcignore
bin/
obj/
.vs/
```

**Step 4: Create .funcignore**

```
.git*
.vscode
__azurite_db*__.json
__blobstorage__
__queuestorage__
local.settings.json
test
.venv
docs/
```

**Step 5: Create .env.example**

```
DOCUMENTINTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
DOCUMENTINTELLIGENCE_API_KEY=your-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-52
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
PDF_INPUT_CONTAINER=pdf-input
PDF_OUTPUT_CONTAINER=pdf-output
```

**Step 6: Create local.settings.json**

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "DOCUMENTINTELLIGENCE_ENDPOINT": "",
    "DOCUMENTINTELLIGENCE_API_KEY": "",
    "AZURE_OPENAI_ENDPOINT": "",
    "AZURE_OPENAI_API_KEY": "",
    "AZURE_OPENAI_DEPLOYMENT_NAME": "",
    "AZURE_STORAGE_CONNECTION_STRING": "",
    "PDF_INPUT_CONTAINER": "pdf-input",
    "PDF_OUTPUT_CONTAINER": "pdf-output"
  }
}
```

**Step 7: Initialize git repo and commit**

```bash
git init
git add requirements.txt host.json .gitignore .funcignore .env.example
git commit -m "chore: scaffold Azure Function project with dependencies and config"
```

---

### Task 2: HTTP Starter Function

**Files:**
- Create: `function_app.py`

**Step 1: Create function_app.py with HTTP starter and empty orchestrator/activities**

This creates the entry point. The HTTP starter accepts a PDF via multipart/form-data, uploads it to Blob Storage, and starts the orchestrator.

```python
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func
import azure.durable_functions as df
from azure.storage.blob import BlobServiceClient

# Initialize Durable Functions app
app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)


# ---------------------------------------------------------------------------
# HTTP Starter: POST /api/pdf
# ---------------------------------------------------------------------------
@app.route(route="pdf", methods=["POST"])
@app.durable_client_input(client_name="client")
async def http_start(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    """Accept PDF upload, store in blob, start orchestrator."""
    logging.info("PDF upload request received.")

    # Validate request has a file
    pdf_bytes = req.get_body()
    if not pdf_bytes:
        return func.HttpResponse(
            '{"error": "No PDF data in request body"}',
            status_code=400,
            mimetype="application/json",
        )

    # Extract filename from header or generate one
    filename = req.headers.get("X-Filename", f"upload_{uuid.uuid4().hex[:8]}.pdf")

    # Upload PDF to input blob container
    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    input_container = os.environ.get("PDF_INPUT_CONTAINER", "pdf-input")

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service.get_container_client(input_container)

    # Ensure container exists
    try:
        container_client.create_container()
    except Exception:
        pass  # Container already exists

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    blob_name = f"{timestamp}_{filename}"
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(pdf_bytes, overwrite=True)

    blob_url = blob_client.url
    logging.info(f"PDF uploaded to blob: {blob_url}")

    # Start orchestrator
    instance_id = await client.start_new(
        "pdf_processing_orchestrator",
        client_input={
            "blob_url": blob_url,
            "blob_name": blob_name,
            "original_filename": filename,
            "container": input_container,
        },
    )

    logging.info(f"Started orchestration: {instance_id}")
    return client.create_check_status_response(req, instance_id)
```

**Step 2: Verify the file is syntactically valid**

Run: `python -c "import ast; ast.parse(open('function_app.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add function_app.py
git commit -m "feat: add HTTP starter function with PDF upload to blob"
```

---

### Task 3: parse_pdf Activity

**Files:**
- Modify: `function_app.py`

**Step 1: Add parse_pdf activity to function_app.py**

Append after the HTTP starter. This calls Document Intelligence to extract markdown + figure images.

```python
import base64
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    DocumentContentFormat,
    AnalyzeOutputOption,
)


# ---------------------------------------------------------------------------
# Activity: Parse PDF with Document Intelligence
# ---------------------------------------------------------------------------
@app.activity_trigger(input_name="payload")
def parse_pdf(payload: dict) -> dict:
    """
    Call Azure Document Intelligence to extract markdown + figures from PDF.

    Input: {"blob_url": str, "container": str, "blob_name": str}
    Output: {
        "markdown": str,
        "figures": [{"id": str, "base64_png": str, "caption": str|None}]
    }
    """
    logging.info(f"parse_pdf: Processing {payload['blob_name']}")

    # Download PDF bytes from blob
    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service.get_container_client(payload["container"])
    blob_client = container_client.get_blob_client(payload["blob_name"])
    pdf_bytes = blob_client.download_blob().readall()

    # Initialize Document Intelligence client
    di_client = DocumentIntelligenceClient(
        endpoint=os.environ["DOCUMENTINTELLIGENCE_ENDPOINT"],
        credential=AzureKeyCredential(os.environ["DOCUMENTINTELLIGENCE_API_KEY"]),
    )

    # Analyze with markdown output + figure extraction
    poller = di_client.begin_analyze_document(
        "prebuilt-layout",
        AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        output_content_format=DocumentContentFormat.MARKDOWN,
        output=[AnalyzeOutputOption.FIGURES],
    )
    result = poller.result()

    # Extract operation ID for fetching figure images
    operation_id = poller.details["operation_id"]

    # Collect figures as base64 PNGs
    figures = []
    if result.figures:
        for figure in result.figures:
            try:
                figure_response = di_client.get_analyze_result_figure(
                    model_id="prebuilt-layout",
                    result_id=operation_id,
                    figure_id=figure.id,
                )
                image_bytes = b"".join(figure_response)
                figures.append({
                    "id": figure.id,
                    "base64_png": base64.b64encode(image_bytes).decode("utf-8"),
                    "caption": figure.caption.content if figure.caption else None,
                })
            except Exception as e:
                logging.warning(f"Failed to extract figure {figure.id}: {e}")
                figures.append({
                    "id": figure.id,
                    "base64_png": None,
                    "caption": figure.caption.content if figure.caption else None,
                })

    logging.info(
        f"parse_pdf: Extracted {len(result.content)} chars markdown, "
        f"{len(figures)} figures"
    )

    return {
        "markdown": result.content,
        "figures": figures,
    }
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('function_app.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add function_app.py
git commit -m "feat: add parse_pdf activity with Document Intelligence markdown + figure extraction"
```

---

### Task 4: describe_figure Activity

**Files:**
- Modify: `function_app.py`

**Step 1: Add describe_figure activity to function_app.py**

Append after parse_pdf. This sends each figure image + text context to GPT-5.2.

```python
from openai import AzureOpenAI


# ---------------------------------------------------------------------------
# Activity: Describe a single figure using GPT-5.2
# ---------------------------------------------------------------------------
@app.activity_trigger(input_name="payload")
def describe_figure(payload: dict) -> dict:
    """
    Send figure image + surrounding text to GPT-5.2 for description.

    Input: {
        "figure_id": str,
        "base64_png": str|None,
        "caption": str|None,
        "surrounding_text": str
    }
    Output: {"figure_id": str, "description": str}
    """
    figure_id = payload["figure_id"]
    logging.info(f"describe_figure: Processing figure {figure_id}")

    # If no image was extracted, return fallback
    if not payload.get("base64_png"):
        fallback = (
            f"> **Figure {figure_id}**"
            f"{': ' + payload['caption'] if payload.get('caption') else ''}\n"
            f"> [Figure image could not be extracted from the document]"
        )
        return {"figure_id": figure_id, "description": fallback}

    # Initialize Azure OpenAI client
    client = AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version="2025-04-01-preview",
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    )

    system_prompt = (
        "You are a pharmaceutical data analyst. You are given a figure "
        "(chart, graph, diagram, or table) extracted from a pharma performance "
        "report, along with surrounding text for context.\n\n"
        "Describe the visual precisely, including:\n"
        "- Type of visualization (bar chart, line graph, table, etc.)\n"
        "- Axis labels and units\n"
        "- Key data points and specific numerical values\n"
        "- Drug names and time periods shown\n"
        "- Trends, patterns, and notable observations\n"
        "- How the data relates to the surrounding context\n\n"
        "Output as clean markdown. Use a markdown table if the figure is a "
        "data table. Be precise with numbers — do not approximate."
    )

    user_content = []

    # Add context text
    context_text = payload.get("surrounding_text", "")
    if context_text:
        user_content.append({
            "type": "text",
            "text": f"Surrounding document context:\n\n{context_text}\n\nDescribe the following figure:",
        })
    else:
        user_content.append({
            "type": "text",
            "text": "Describe the following figure from a pharmaceutical report:",
        })

    # Add the figure image
    data_url = f"data:image/png;base64,{payload['base64_png']}"
    user_content.append({
        "type": "image_url",
        "image_url": {"url": data_url, "detail": "high"},
    })

    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=2000,
        temperature=0.1,
    )

    description = response.choices[0].message.content

    # Prepend caption if available
    if payload.get("caption"):
        description = f"**{payload['caption']}**\n\n{description}"

    logging.info(f"describe_figure: Generated {len(description)} chars for figure {figure_id}")
    return {"figure_id": figure_id, "description": description}
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('function_app.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add function_app.py
git commit -m "feat: add describe_figure activity with GPT-5.2 multimodal vision"
```

---

### Task 5: assemble_markdown and save_to_blob Activities

**Files:**
- Modify: `function_app.py`

**Step 1: Add assemble_markdown activity**

```python
import re


# ---------------------------------------------------------------------------
# Activity: Assemble final markdown with figure descriptions
# ---------------------------------------------------------------------------
@app.activity_trigger(input_name="payload")
def assemble_markdown(payload: dict) -> str:
    """
    Replace figure placeholders in draft markdown with GPT-5.2 descriptions.

    Input: {"markdown": str, "descriptions": [{"figure_id": str, "description": str}]}
    Output: str (final markdown)
    """
    markdown = payload["markdown"]
    descriptions = {d["figure_id"]: d["description"] for d in payload["descriptions"]}

    logging.info(
        f"assemble_markdown: Replacing {len(descriptions)} figure placeholders"
    )

    # Document Intelligence markdown uses patterns like:
    # <figure>![](figures/1.1)</figure>  or  ![](figures/1.1)
    def replace_figure(match):
        figure_ref = match.group(1)  # e.g., "1.1"
        if figure_ref in descriptions:
            desc = descriptions[figure_ref]
            return f"\n\n---\n\n{desc}\n\n---\n\n"
        return match.group(0)  # Keep original if no description

    # Match both <figure>![](figures/X)</figure> and standalone ![](figures/X)
    markdown = re.sub(
        r'<figure>\s*!\[\]\(figures/([^)]+)\)\s*</figure>',
        replace_figure,
        markdown,
    )
    markdown = re.sub(
        r'!\[\]\(figures/([^)]+)\)',
        replace_figure,
        markdown,
    )

    logging.info(f"assemble_markdown: Final markdown is {len(markdown)} chars")
    return markdown
```

**Step 2: Add save_to_blob activity**

```python
# ---------------------------------------------------------------------------
# Activity: Save final markdown to Blob Storage
# ---------------------------------------------------------------------------
@app.activity_trigger(input_name="payload")
def save_to_blob(payload: dict) -> str:
    """
    Upload final markdown to output blob container.

    Input: {"markdown": str, "original_filename": str}
    Output: str (blob URL)
    """
    original = payload["original_filename"]
    # Strip .pdf extension if present
    name_base = original.rsplit(".", 1)[0] if "." in original else original
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    blob_name = f"{name_base}_{timestamp}.md"

    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    output_container = os.environ.get("PDF_OUTPUT_CONTAINER", "pdf-output")

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service.get_container_client(output_container)

    try:
        container_client.create_container()
    except Exception:
        pass

    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(
        payload["markdown"].encode("utf-8"),
        overwrite=True,
        content_settings={"content_type": "text/markdown"},
    )

    logging.info(f"save_to_blob: Saved markdown to {blob_name}")
    return blob_client.url
```

**Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('function_app.py').read()); print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add function_app.py
git commit -m "feat: add assemble_markdown and save_to_blob activities"
```

---

### Task 6: Orchestrator Function

**Files:**
- Modify: `function_app.py`

**Step 1: Add the orchestrator function and context extraction helper**

Insert after the HTTP starter but before the activities. The orchestrator wires all activities together with fan-out/fan-in.

```python
# ---------------------------------------------------------------------------
# Helper: Extract surrounding text context for a figure
# ---------------------------------------------------------------------------
def _extract_surrounding_text(markdown: str, figure_id: str, window: int = 500) -> str:
    """Get ~500 chars before and after a figure reference in the markdown."""
    # Look for figure reference patterns
    patterns = [
        f"<figure>\\s*!\\[\\]\\(figures/{re.escape(figure_id)}\\)\\s*</figure>",
        f"!\\[\\]\\(figures/{re.escape(figure_id)}\\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, markdown)
        if match:
            start = max(0, match.start() - window)
            end = min(len(markdown), match.end() + window)
            return markdown[start:end]
    return ""


# ---------------------------------------------------------------------------
# Orchestrator: Coordinate the full PDF processing pipeline
# ---------------------------------------------------------------------------
@app.orchestration_trigger(context_name="context")
def pdf_processing_orchestrator(context: df.DurableOrchestrationContext):
    """
    1. Parse PDF with Document Intelligence
    2. Fan-out: describe each figure with GPT-5.2 in parallel
    3. Fan-in: assemble final markdown
    4. Save to blob
    """
    input_data = context.get_input()

    # Step 1: Parse PDF
    parse_result = yield context.call_activity("parse_pdf", {
        "blob_url": input_data["blob_url"],
        "blob_name": input_data["blob_name"],
        "container": input_data["container"],
    })

    draft_markdown = parse_result["markdown"]
    figures = parse_result["figures"]

    # Step 2: Fan-out — describe each figure in parallel
    description_tasks = []
    for figure in figures:
        surrounding_text = _extract_surrounding_text(draft_markdown, figure["id"])
        task = context.call_activity_with_retry(
            "describe_figure",
            retry_options=df.RetryOptions(
                first_retry_interval_in_milliseconds=5000,
                max_number_of_attempts=3,
            ),
            input_={
                "figure_id": figure["id"],
                "base64_png": figure["base64_png"],
                "caption": figure["caption"],
                "surrounding_text": surrounding_text,
            },
        )
        description_tasks.append(task)

    # Step 3: Fan-in — wait for all descriptions
    descriptions = yield context.task_all(description_tasks)

    # Step 4: Assemble final markdown
    final_markdown = yield context.call_activity("assemble_markdown", {
        "markdown": draft_markdown,
        "descriptions": descriptions,
    })

    # Step 5: Save to blob
    blob_url = yield context.call_activity_with_retry(
        "save_to_blob",
        retry_options=df.RetryOptions(
            first_retry_interval_in_milliseconds=5000,
            max_number_of_attempts=3,
        ),
        input_={
            "markdown": final_markdown,
            "original_filename": input_data["original_filename"],
        },
    )

    return {
        "status": "completed",
        "blob_url": blob_url,
        "markdown": final_markdown,
        "figures_processed": len(figures),
        "figures_described": len([d for d in descriptions if "could not be extracted" not in d.get("description", "")]),
    }
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('function_app.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add function_app.py
git commit -m "feat: add orchestrator with fan-out/fan-in and retry logic"
```

---

### Task 7: Final Assembly & Verification

**Files:**
- Modify: `function_app.py` (reorder imports, ensure correct order of functions)

**Step 1: Verify the complete function_app.py has correct import order**

The top of `function_app.py` should consolidate all imports:

```python
import base64
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import azure.functions as func
import azure.durable_functions as df
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    DocumentContentFormat,
    AnalyzeOutputOption,
)
from openai import AzureOpenAI
```

**Step 2: Verify the full file parses correctly**

Run: `python -c "import ast; ast.parse(open('function_app.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Install dependencies and verify imports resolve**

Run: `pip install -r requirements.txt`
Run: `python -c "import function_app; print('All imports OK')"`

**Step 4: Commit**

```bash
git add function_app.py
git commit -m "refactor: consolidate imports and finalize function_app.py"
```

---

### Task 8: Local Testing Setup

**Files:**
- No new files — this is a verification task

**Step 1: Install Azure Functions Core Tools (if not installed)**

Run: `npm install -g azure-functions-core-tools@4 --unsafe-perm true`
Or verify: `func --version`

**Step 2: Fill in local.settings.json with real credentials**

Update `local.settings.json` with your actual Azure resource values:
- Document Intelligence endpoint + key
- Azure OpenAI endpoint + key + deployment name
- Storage connection string

**Step 3: Start the function locally**

Run: `func start`
Expected: Function host starts, shows endpoints including `http://localhost:7071/api/pdf`

**Step 4: Test with a sample PDF**

```bash
curl -X POST http://localhost:7071/api/pdf \
  -H "Content-Type: application/pdf" \
  -H "X-Filename: test_report.pdf" \
  --data-binary @sample.pdf
```

Expected: Returns JSON with `statusQueryGetUri` for polling.

**Step 5: Poll for results**

Use the `statusQueryGetUri` from the response to check progress until `runtimeStatus` is `Completed`.

**Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: address issues found during local testing"
```
