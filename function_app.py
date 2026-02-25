import base64
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import azure.functions as func
import azure.durable_functions as df
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    DocumentContentFormat,
    AnalyzeOutputOption,
)
from openai import AzureOpenAI

# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

MAX_PDF_SIZE = 200 * 1024 * 1024  # 200 MB

# ---------------------------------------------------------------------------
# Lazy-initialized singleton clients (reused across activity invocations)
# ---------------------------------------------------------------------------

_blob_service: BlobServiceClient | None = None
_di_client: DocumentIntelligenceClient | None = None
_openai_client: AzureOpenAI | None = None


def _get_blob_service() -> BlobServiceClient:
    global _blob_service
    if _blob_service is None:
        _blob_service = BlobServiceClient.from_connection_string(
            os.environ["AZURE_STORAGE_CONNECTION_STRING"]
        )
    return _blob_service


def _get_di_client() -> DocumentIntelligenceClient:
    global _di_client
    if _di_client is None:
        _di_client = DocumentIntelligenceClient(
            endpoint=os.environ["DOCUMENTINTELLIGENCE_ENDPOINT"],
            credential=AzureKeyCredential(os.environ["DOCUMENTINTELLIGENCE_API_KEY"]),
        )
    return _di_client


def _get_openai_client() -> AzureOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version="2025-04-01-preview",
        )
    return _openai_client


# ---------------------------------------------------------------------------
# HTTP Starter — POST /api/pdf
# ---------------------------------------------------------------------------


@app.route(route="pdf", methods=["POST"])
@app.durable_client_input(client_name="client")
async def http_start(req: func.HttpRequest, client) -> func.HttpResponse:
    """Accept a PDF via request body and start the processing orchestration."""

    pdf_bytes = req.get_body()
    if not pdf_bytes:
        return func.HttpResponse("Request body is empty.", status_code=400)

    if len(pdf_bytes) > MAX_PDF_SIZE:
        return func.HttpResponse("PDF exceeds maximum size of 200 MB.", status_code=413)

    if not pdf_bytes[:5].startswith(b"%PDF-"):
        return func.HttpResponse("Request body is not a valid PDF.", status_code=400)

    # Sanitize filename from header
    raw_filename = req.headers.get("X-Filename") or f"{uuid.uuid4()}.pdf"
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", raw_filename)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    blob_name = f"{timestamp}_{filename}"

    container_name = os.environ.get("PDF_INPUT_CONTAINER", "pdf-input")

    blob_service = _get_blob_service()
    container_client = blob_service.get_container_client(container_name)
    try:
        container_client.create_container()
    except ResourceExistsError:
        pass

    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(pdf_bytes, overwrite=True)

    blob_url = blob_client.url

    orchestrator_input = {
        "blob_url": blob_url,
        "blob_name": blob_name,
        "original_filename": filename,
        "container": container_name,
    }

    instance_id = await client.start_new("pdf_processing_orchestrator", None, orchestrator_input)

    logging.info("Started orchestration with ID='%s' for blob '%s'.", instance_id, blob_name)

    return client.create_check_status_response(req, instance_id)


# ---------------------------------------------------------------------------
# Helper: _extract_surrounding_text
# ---------------------------------------------------------------------------


def _extract_surrounding_text(markdown: str, figure_id: str, window: int = 500) -> str:
    """Get ~500 chars before and after a figure reference in the markdown."""
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
# Orchestrator: pdf_processing_orchestrator
# ---------------------------------------------------------------------------


@app.orchestration_trigger(context_name="context")
def pdf_processing_orchestrator(context: df.DurableOrchestrationContext):
    """Orchestrate PDF parsing, figure description, markdown assembly, and save."""

    payload = context.get_input()
    blob_name = payload["blob_name"]
    original_filename = payload["original_filename"]
    container = payload["container"]

    # Step 1: Parse PDF with Document Intelligence
    parse_result = yield context.call_activity(
        "parse_pdf",
        {
            "blob_name": blob_name,
            "container": container,
        },
    )

    markdown = parse_result["markdown"]
    figures = parse_result.get("figures", [])

    # Step 2: Fan-out — describe each figure in parallel
    retry_options = df.RetryOptions(
        first_retry_interval_in_milliseconds=5000,
        max_number_of_attempts=3,
    )

    description_tasks = []
    for figure in figures:
        figure_id = figure["id"]
        # NOTE: _extract_surrounding_text is a pure function (regex over strings),
        # which is safe to call inside an orchestrator during replay.
        surrounding_text = _extract_surrounding_text(markdown, figure_id)
        task = context.call_activity_with_retry(
            "describe_figure",
            retry_options=retry_options,
            input_={
                "figure_id": figure_id,
                "base64_png": figure.get("base64_png"),
                "caption": figure.get("caption", ""),
                "surrounding_text": surrounding_text,
            },
        )
        description_tasks.append(task)

    # Step 3: Fan-in — wait for all descriptions
    if description_tasks:
        descriptions = yield context.task_all(description_tasks)
    else:
        descriptions = []

    # Step 4: Assemble final markdown
    final_markdown = yield context.call_activity(
        "assemble_markdown",
        {
            "markdown": markdown,
            "descriptions": descriptions,
        },
    )

    # Step 5: Save to output blob
    output_blob_url = yield context.call_activity_with_retry(
        "save_to_blob",
        retry_options=retry_options,
        input_={
            "markdown": final_markdown,
            "original_filename": original_filename,
        },
    )

    # Return metadata only — full markdown is in blob storage (avoids
    # Durable Functions history size limits on large documents).
    return {
        "status": "completed",
        "blob_url": output_blob_url,
        "figures_processed": len(figures),
        "figures_described": len(descriptions),
    }


# ---------------------------------------------------------------------------
# Activity: parse_pdf
# ---------------------------------------------------------------------------


@app.activity_trigger(input_name="payload")
def parse_pdf(payload: dict) -> dict:
    """Download PDF from blob and parse it with Azure Document Intelligence."""

    container = payload["container"]
    blob_name = payload["blob_name"]

    blob_service = _get_blob_service()
    blob_client = blob_service.get_container_client(container).get_blob_client(blob_name)
    pdf_bytes = blob_client.download_blob().readall()

    di_client = _get_di_client()

    poller = di_client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        output_content_format=DocumentContentFormat.MARKDOWN,
        output=[AnalyzeOutputOption.FIGURES],
    )
    result = poller.result()
    operation_id = poller.details["operation_id"]

    figures = []
    for figure in result.figures or []:
        figure_id = figure.id
        caption_text = ""
        if figure.caption and figure.caption.content:
            caption_text = figure.caption.content

        base64_png = None
        try:
            figure_response = di_client.get_analyze_result_figure(
                model_id="prebuilt-layout",
                result_id=operation_id,
                figure_id=figure_id,
            )
            image_bytes = b"".join(figure_response)
            base64_png = base64.b64encode(image_bytes).decode("utf-8")
        except Exception as exc:
            logging.warning("Failed to fetch figure '%s': %s", figure_id, exc)

        figures.append(
            {
                "id": figure_id,
                "base64_png": base64_png,
                "caption": caption_text,
            }
        )

    logging.info(
        "parse_pdf: extracted %d figures from '%s'.", len(figures), blob_name
    )

    return {
        "markdown": result.content,
        "figures": figures,
    }


# ---------------------------------------------------------------------------
# Activity: describe_figure
# ---------------------------------------------------------------------------


@app.activity_trigger(input_name="payload")
def describe_figure(payload: dict) -> dict:
    """Use the configured Azure OpenAI model to describe a single figure image."""

    figure_id = payload["figure_id"]
    base64_png = payload.get("base64_png")
    caption = payload.get("caption", "")
    surrounding_text = payload.get("surrounding_text", "")

    if not base64_png:
        fallback = (
            f"{caption}\n\n[Figure image could not be retrieved.]"
            if caption
            else "[Figure image could not be retrieved.]"
        )
        return {"figure_id": figure_id, "description": fallback}

    openai_client = _get_openai_client()
    deployment_name = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    system_prompt = (
        "You are a pharmaceutical data analyst. "
        "When given a figure from a clinical or scientific document, describe it with precision. "
        "Include all visible trends, axis labels, units, numerical values, drug names, "
        "dosage information, time periods, statistical annotations, and any legends. "
        "Be thorough and exact so a reader without the image can fully understand the data."
    )

    user_content = []

    if surrounding_text:
        user_content.append(
            {
                "type": "text",
                "text": (
                    "The following text appears near this figure in the document:\n\n"
                    f"{surrounding_text}\n\n"
                    "Now describe the figure shown in the image below."
                ),
            }
        )
    else:
        user_content.append(
            {"type": "text", "text": "Describe the figure shown in the image below."}
        )

    user_content.append(
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{base64_png}",
                "detail": "high",
            },
        }
    )

    response = openai_client.chat.completions.create(
        model=deployment_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=2000,
        temperature=0.1,
    )

    raw_content = response.choices[0].message.content
    if not raw_content:
        logging.warning("GPT returned empty content for figure '%s'.", figure_id)
        raw_content = "[Figure description could not be generated.]"
    description_text = raw_content.strip()

    if caption:
        description_text = f"{caption}\n\n{description_text}"

    logging.info("describe_figure: described figure '%s'.", figure_id)

    return {"figure_id": figure_id, "description": description_text}


# ---------------------------------------------------------------------------
# Activity: assemble_markdown
# ---------------------------------------------------------------------------


@app.activity_trigger(input_name="payload")
def assemble_markdown(payload: dict) -> str:
    """Replace figure placeholders in markdown with GPT-generated descriptions."""

    markdown = payload["markdown"]
    descriptions: list = payload.get("descriptions", [])

    desc_map = {item["figure_id"]: item["description"] for item in descriptions}

    def replacement(figure_id: str) -> str:
        description = desc_map.get(figure_id, "[Figure description unavailable.]")
        return f"\n\n---\n\n{description}\n\n---\n\n"

    # Replace <figure>![](figures/X)</figure> pattern first (more specific)
    figure_tag_pattern = re.compile(
        r"<figure>\s*!\[\]\(figures/([^)]+)\)\s*</figure>"
    )
    markdown = figure_tag_pattern.sub(
        lambda m: replacement(m.group(1)), markdown
    )

    # Replace bare ![](figures/X) pattern
    bare_pattern = re.compile(r"!\[\]\(figures/([^)]+)\)")
    markdown = bare_pattern.sub(lambda m: replacement(m.group(1)), markdown)

    logging.info("assemble_markdown: assembled final markdown.")
    return markdown


# ---------------------------------------------------------------------------
# Activity: save_to_blob
# ---------------------------------------------------------------------------


@app.activity_trigger(input_name="payload")
def save_to_blob(payload: dict) -> str:
    """Upload the final markdown to the output blob container."""

    markdown_content = payload["markdown"]
    original_filename = payload["original_filename"]

    # Strip .pdf extension (case-insensitive)
    name_base = re.sub(r"\.pdf$", "", original_filename, flags=re.IGNORECASE)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    blob_name = f"{name_base}_{timestamp}.md"

    output_container = os.environ.get("PDF_OUTPUT_CONTAINER", "pdf-output")

    blob_service = _get_blob_service()
    container_client = blob_service.get_container_client(output_container)
    try:
        container_client.create_container()
    except ResourceExistsError:
        pass

    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(
        markdown_content.encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="text/markdown"),
    )

    output_url = blob_client.url
    logging.info("save_to_blob: saved markdown to '%s'.", output_url)
    return output_url
