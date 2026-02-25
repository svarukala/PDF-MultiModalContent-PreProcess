# PDF Vision-to-Markdown Azure Function Design

## Context

Azure Durable Function that processes pharma PDF documents (100+ pages) containing charts, line diagrams, tables with numerical data, and drug performance metrics. Uses Azure Document Intelligence for parsing and GPT-5.2 for describing visual elements. Outputs a self-contained markdown file.

## Architecture: Durable Functions Fan-out/Fan-in

```
Client (HTTP POST /pdf)
    |
    v
+----------------------+
|  HTTP Starter        |  <- Accepts PDF, uploads to Blob, starts orchestrator
+----------+-----------+
           | returns status check URL
           v
+--------------------------------------+
|  Orchestrator                        |
|  pdf_processing_orchestrator         |
|                                      |
|  1. call_activity("parse_pdf")       |  <- Doc Intelligence: markdown + figures
|  2. FAN-OUT: for each figure:        |
|     call_activity("describe_figure") |  <- GPT-5.2: image -> description
|  3. FAN-IN: collect all descriptions |
|  4. call_activity("assemble_markdown")|<- Stitch final markdown
|  5. call_activity("save_to_blob")    |  <- Upload to Blob Storage
+--------------------------------------+
```

## Components

### HTTP Starter
- Accepts PDF via multipart/form-data POST
- Uploads raw PDF to `pdf-input` blob container
- Starts orchestrator with blob URL as input
- Returns status-check URL for polling

### Orchestrator (pdf_processing_orchestrator)
- Coordinates the full pipeline
- No timeout limit (Durable Functions orchestrators run indefinitely)
- Returns blob URL + full markdown content on completion

### Activity Functions

#### 1. parse_pdf
- Calls Azure Document Intelligence `prebuilt-layout` model
- Parameters: `output_content_format=MARKDOWN`, `output=[FIGURES]`
- Fetches each detected figure as PNG via `get_analyze_result_figure()`
- Returns: draft markdown string + list of figures (base64 PNG + metadata)

#### 2. describe_figure (fan-out, one per figure)
- Receives: figure image (base64 PNG) + ~500 words surrounding text context
- Sends multimodal request to GPT-5.2 deployment
- System prompt tailored for pharma data analysis
- Returns: structured markdown description of the visual

#### 3. assemble_markdown
- Takes draft markdown + all figure descriptions
- Replaces `![](figures/N)` placeholders with descriptive text blocks
- Returns: final assembled markdown string

#### 4. save_to_blob
- Saves final markdown to `pdf-output` blob container
- Naming: `{original_filename}_{timestamp}.md`
- Returns: blob URL

## Data Flow

1. Client POSTs PDF -> HTTP Starter uploads to blob -> starts orchestrator
2. parse_pdf: Doc Intelligence extracts markdown + figure images
3. describe_figure (parallel): GPT-5.2 describes each chart/diagram/table image
4. assemble_markdown: replaces figure placeholders with descriptions
5. save_to_blob: uploads to output container
6. Client polls status endpoint -> gets blob URL + markdown content

## GPT-5.2 Prompt Strategy

```
System: You are a pharmaceutical data analyst. Describe the visual
precisely, including: trends, axis labels, specific numerical values,
drug names, time periods, and how the data relates to the surrounding
context. Output as markdown.
```

## Project Structure

```
PDF-MultiModal-Analysis/
├── function_app.py              # All functions: starter, orchestrator, activities
├── host.json                    # Durable Functions config
├── local.settings.json          # Local dev settings (not committed)
├── requirements.txt             # Python dependencies
├── .env.example                 # Template for required env vars
├── .gitignore
├── .funcignore
└── docs/plans/
```

## Dependencies

```
azure-functions
azure-functions-durable==1.5.0
azure-ai-documentintelligence==1.0.2
openai>=2.24.0
azure-identity
azure-storage-blob>=12.20.0
```

## Environment Variables

| Variable | Purpose |
|---|---|
| DOCUMENTINTELLIGENCE_ENDPOINT | Azure Doc Intelligence endpoint URL |
| DOCUMENTINTELLIGENCE_API_KEY | Doc Intelligence API key |
| AZURE_OPENAI_ENDPOINT | Azure OpenAI endpoint URL |
| AZURE_OPENAI_API_KEY | Azure OpenAI API key |
| AZURE_OPENAI_DEPLOYMENT_NAME | GPT-5.2 deployment name |
| AZURE_STORAGE_CONNECTION_STRING | Blob storage connection |
| PDF_INPUT_CONTAINER | Input blob container (default: pdf-input) |
| PDF_OUTPUT_CONTAINER | Output blob container (default: pdf-output) |

## Error Handling

- **describe_figure retries:** Max 3 attempts, 5s backoff per figure
- **Figure fallback:** If description fails after retries, insert `> [Figure description unavailable]`
- **parse_pdf failure:** Fatal — orchestrator returns error immediately
- **save_to_blob failure:** Retries 3 times, orchestrator still returns markdown in response

## Decisions

- **Single file (function_app.py):** v2 decorator model with DFApp, keeps it simple for this scope
- **Python:** Best SDK support for Doc Intelligence + OpenAI
- **Durable Functions:** Required for 100+ page PDFs — no timeout, parallel figure processing, per-figure retry
- **AzureOpenAI client (classic path):** Using explicit api_version for stability over new v1 path
- **Output:** Both HTTP response body and Blob Storage
