# Beyond OCR: A Durable Pattern for Turning Visual Documents into AI-Ready Content

Extracting text from a PDF is only part of understanding it.

A report may place its most important information in a chart, a process diagram, or a table whose meaning depends on its layout. Text extraction can capture the words around these elements while losing the relationships they communicate.

A useful approach is to combine layout-aware document extraction with a vision-capable language model, then assemble the results into a single, readable artifact.

This article explores a reusable pattern for doing that reliably: **a durable document-enrichment pipeline**. It separates extraction, visual interpretation, and assembly into independently observable steps, while keeping the original extraction available for comparison.

> **[IMAGE PLACEHOLDER: Before-and-after illustration using a fictional document. Show a PDF page with text and a chart beside Markdown containing the extracted text and a description of the chart. Do not use real customer documents.]**

## The pattern: extract, enrich, assemble

The pipeline has five main steps:

1. Accept a document and store it.
2. Extract its text, structure, and figures.
3. Generate a description for each figure.
4. Insert those descriptions into the extracted content.
5. Store the final document and expose it to the caller.

An Azure implementation can use Azure Functions for the HTTP interface, Durable Functions for orchestration, Blob Storage for artifacts, Azure AI Document Intelligence for extraction, and Azure OpenAI for visual interpretation.

The architecture is not tied to those particular services. The same separation of responsibilities applies to other workflow engines, document parsers, model providers, and object stores.

> **[IMAGE PLACEHOLDER: Architecture diagram. Client -> HTTP starter -> input storage -> durable orchestrator -> document extraction -> bounded parallel figure-description activities -> assembly -> output storage. Include a separate path from the client to status and artifact endpoints.]**

## 1. Start the work without holding the connection open

Document processing is a poor fit for a single long-running HTTP request. A large document may require extraction, dozens of model calls, retries, and final assembly. Keeping the connection open makes the result vulnerable to client disconnects and request timeouts.

Instead, the upload endpoint validates the request, stores the file, starts an orchestration, and returns **HTTP 202 Accepted** with a job identifier and a status URL.

The client then polls for progress independently of the original upload.

Use a unique job identifier to namespace artifacts:

```text
input/{job-id}/document.pdf
output/{job-id}/interim.md
output/{job-id}/final.md
```

This also prevents two uploads with the same filename from overwriting one another.

There is an important distinction here: accepting a job is not the same as completing it. The client should show upload acceptance, processing progress, and final success as separate states.

## 2. Let the orchestrator coordinate, not perform the work

The orchestrator describes the sequence of activities and waits for their results. Activities perform external operations: downloading blobs, calling document services, invoking models, and saving artifacts.

Durable Functions persists workflow history so an orchestration can reconstruct its state through replay. That allows coordination to span multiple requests and long periods of waiting.

It does **not** make individual activities unlimited. Activity execution is still subject to the hosting plan, timeout settings, memory limits, and external service behavior.

Replay also imposes a design rule: keep orchestrator logic deterministic. Make network requests and other side effects inside activities. Use workflow-provided time and timer APIs instead of ordinary clocks and sleeps.

Retries introduce another consideration: an activity may execute more than once. Use predictable artifact paths and retry-safe writes where possible. External model calls may still be repeated, so retries can affect both latency and cost.

## 3. Preserve the original extraction

A layout-aware document service can return more than plain text. Depending on the service and document, its output may include:

- Markdown with headings, tables, and figure blocks.
- Cropped figure images.
- Captions and figure identifiers.
- Character spans locating figures within the extracted content.

Save the original Markdown before enrichment.

This **interim artifact** becomes the baseline for troubleshooting and comparison. If the final document is wrong, you can distinguish an extraction problem from a visual-description problem or an assembly problem.

It also gives users something useful to inspect while later stages are still running.

> **[IMAGE PLACEHOLDER: Interim Markdown from a synthetic document. Highlight a heading, an HTML table, a figure block, and a caption. Annotate which elements came directly from the extraction service.]**

## 4. Describe figures with bounded parallelism

Figures are natural candidates for parallel processing. Each description activity can receive an image, its caption, and a small window of nearby text.

The nearby text matters. A chart may contain abbreviated labels or unexplained units that the surrounding paragraph clarifies. Providing that context can make the description more useful than an image-only prompt.

A generic prompt might ask the model to:

> Describe the visible chart or diagram. Include its labels, units, legends, relationships, and clearly readable values. Distinguish visible facts from interpretation, and explicitly identify anything that cannot be read confidently.

The model output should be treated as an interpretation, not a guaranteed transcription. Precise numerical values and consequential conclusions still need review.

### Why not send every figure at once?

Unrestricted fan-out can exceed a model deployment's token or request limits. A workflow may successfully extract every figure, only to fail when a burst of model calls is throttled.

A practical starting point is **bounded fan-out/fan-in**: schedule a small batch, wait for it to finish, record progress, and schedule the next batch.

Small batches are simple to understand and make progress easy to report. Their tradeoff is that one slow call can hold up the next batch. A bounded worker pool can improve utilization when that becomes important.

Concurrency limits alone are not token-rate limits. Image sizes, prompt lengths, output budgets, other workloads, and the number of application instances all affect actual consumption.

Use retry policies that leave time for throttling conditions to clear, and account for retries already performed by the SDK. Before scaling out, review the aggregate load across all hosts.

> **[IMAGE PLACEHOLDER: Timeline contrasting unrestricted fan-out, with a burst of throttled requests, against a small number of concurrent figure calls with visible batch progress. Label this as conceptual, not measured performance.]**

## 5. Reassemble using metadata, not assumptions

One of the easiest mistakes in document enrichment is assuming that the extracted Markdown will always contain image links such as:

```markdown
![](figures/1.1)
```

Actual output may instead contain a block like:

```html
<figure>
Extracted chart text
<figcaption>Example chart caption</figcaption>
</figure>
```

A replacement routine that only recognizes image links can silently do nothing. All model calls may succeed, yet none of their descriptions appear in the final file.

The stronger approach is to use **figure identifiers and character spans** from the extraction result.

Map each figure to the original Markdown using its offsets and lengths. When a span belongs inside a figure block, replace the relevant block rather than leaving fragments of its markup behind.

There are several details worth handling explicitly:

**Align indexing conventions.** The extraction API and the programming language must agree on what an offset counts. For Python string slicing, request Unicode code-point indexing when the service supports it. Otherwise, some characters can shift replacement boundaries.

**Handle overlapping spans.** Multiple extracted images may belong to one figure block. Merge overlapping replacement regions and retain every associated description. Do not assume one image always corresponds to one HTML block.

**Handle figures without positions.** If a figure has no usable text span or explicit reference, append its description in a clearly labeled section. State that its original text position was unavailable rather than inventing a placement.

**Keep the original immutable.** Build the final document from the original text and the mapped replacements. Preserve content outside the replaced regions.

> **[IMAGE PLACEHOLDER: Span-mapping diagram showing two figure IDs associated with one Markdown figure block. Show both descriptions retained in the final replacement, with surrounding text unchanged.]**

## 6. Make progress and artifacts part of the interface

A useful document-processing page does more than show a spinner.

It can expose the major workflow stages, completed figure counts, recent activity events, and links to available artifacts. The interim extraction can appear first; the enriched output follows after assembly and storage complete.

Keep the status response small. It should not carry full Markdown documents, base64 images, or a large execution history on every poll. Serve artifacts through separate endpoints.

Be precise about what the page shows. Orchestration milestones are an **activity-level view**, not a trace of every HTTP request or SDK retry. If users need wire-level diagnostics, provide those through appropriately secured telemetry.

Document previews also need care. Extracted Markdown can contain HTML, and model output is untrusted content. A source-text preview is a simple safe default. If rendered Markdown is required, use a renderer with appropriate sanitization.

> **[IMAGE PLACEHOLDER: Screenshot of the upload page using a fictional sample. Include the progress stages, an activity log, and side-by-side interim and final Markdown panels with download buttons.]**

## 7. Verify the artifact, not just the workflow

A completed orchestration proves that its activities finished. It does not prove that the output contains the intended enrichment.

Test the transformation itself:

- Every extracted figure has one description result, with fallbacks identified separately.
- Every generated description appears in the final artifact.
- Each description has a unique figure marker.
- Overlapping spans do not overwrite another figure's description.
- Text outside replacement regions remains intact.
- Documents without figures remain unchanged.
- Missing descriptions and invalid spans fail explicitly.

An especially important regression test is a document containing real `<figure>` markup rather than assumed image-link placeholders.

For an integration check, submit a synthetic PDF through the same interface users will use. Confirm that the interim file becomes available, progress advances, and the downloaded final file contains the actual generated descriptions.

This closes the gap between "the model calls succeeded" and "the document was enriched."

## Before moving from a prototype to production

The pattern provides a foundation, but production requirements extend beyond successful conversion.

Add identity-based access and per-document authorization. A job identifier is not an authorization policy, and a shared function key is not a substitute for user isolation.

Define document retention, artifact cleanup, network access, model-processing geography, and logging policies. Avoid logging document bodies, credentials, or sensitive management URLs.

Review cost and throughput under representative workloads. Large image payloads and intermediate text in orchestration history can become expensive to serialize and replay; at higher scale, pass artifact references between activities instead of embedding large payloads in workflow state.

Finally, version workflow changes carefully. Active durable orchestrations depend on their recorded activity sequence. Drain existing jobs or use an appropriate versioning strategy before changing that sequence.

## The takeaway

The value of this pattern is not simply adding a vision model to OCR. It is separating **extraction, interpretation, orchestration, and assembly** so each stage can be inspected and improved.

Preserve the raw extraction. Bound model concurrency. Use structural metadata to place descriptions. Expose progress honestly. Most importantly, verify that the final artifact actually contains the enrichment you generated.

The result is a more useful text representation for search, retrieval, summarization, and human review, while retaining a clear path back to the original document. It is an enriched interpretation of that document, not a replacement for the source.
