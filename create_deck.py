"""Generate a PowerPoint deck explaining the PDF MultiModal Analysis project."""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# -- Brand colors --
DARK_BG = RGBColor(0x1B, 0x1B, 0x2F)       # Deep navy
ACCENT_BLUE = RGBColor(0x00, 0x78, 0xD4)    # Azure blue
ACCENT_TEAL = RGBColor(0x00, 0xB2, 0x94)    # Teal green
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xE0, 0xE0, 0xE0)
MED_GRAY = RGBColor(0x99, 0x99, 0x99)
DARK_TEXT = RGBColor(0x2D, 0x2D, 0x2D)
ORANGE = RGBColor(0xFF, 0x8C, 0x00)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
W = prs.slide_width
H = prs.slide_height


def add_bg(slide, color=DARK_BG):
    """Fill slide background with a solid color."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_textbox(slide, left, top, width, height, text, font_size=18,
                color=WHITE, bold=False, alignment=PP_ALIGN.LEFT, font_name="Segoe UI"):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    return tf


def add_para(tf, text, font_size=18, color=WHITE, bold=False, space_before=Pt(6),
             alignment=PP_ALIGN.LEFT, font_name="Segoe UI"):
    p = tf.add_paragraph()
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    if space_before:
        p.space_before = space_before
    return p


def add_shape_box(slide, left, top, width, height, fill_color, border_color=None, text="",
                  font_size=14, font_color=WHITE, bold=False):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = Pt(1.5)
    else:
        shape.line.fill.background()
    if text:
        tf = shape.text_frame
        tf.word_wrap = True
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(font_size)
        p.font.color.rgb = font_color
        p.font.bold = bold
    shape.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    shape.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    return shape


def add_arrow(slide, left, top, width, height):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = ACCENT_TEAL
    shape.line.fill.background()
    return shape


# ============================================================
# SLIDE 1 — Title
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
add_bg(slide)

# Accent bar at top
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(1.5), Inches(1.8), Inches(10), Inches(1.2),
            "PDF MultiModal Analysis", font_size=44, color=WHITE, bold=True)

add_textbox(slide, Inches(1.5), Inches(3.0), Inches(10), Inches(0.8),
            "Turning Complex PDFs into Structured, AI-Ready Markdown",
            font_size=26, color=ACCENT_TEAL)

tf = add_textbox(slide, Inches(1.5), Inches(4.2), Inches(10), Inches(1.5),
                 "A reusable serverless pattern for extracting and describing",
                 font_size=18, color=LIGHT_GRAY)
add_para(tf, "every chart, table, and figure — no images required.",
         font_size=18, color=LIGHT_GRAY)

add_textbox(slide, Inches(1.5), Inches(5.8), Inches(10), Inches(0.5),
            "Azure Durable Functions  |  Document Intelligence  |  GPT-4.1 Vision",
            font_size=16, color=MED_GRAY)

# Accent bar at bottom
add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# SLIDE 2 — The Problem
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(0.8), Inches(0.4), Inches(10), Inches(0.7),
            "The Problem", font_size=36, color=WHITE, bold=True)

# Left column — pain points
problems = [
    ("100+ Page PDFs", "Enterprise documents are dense — clinical trials, financial reports, insurance claims, legal contracts."),
    ("Charts & Figures Everywhere", "Critical data lives inside images: line charts, bar graphs, flow diagrams, annotated tables."),
    ("Text Extraction Isn't Enough", "OCR and standard parsing miss the visual insights. Charts become empty placeholders."),
    ("Manual Review Doesn't Scale", "Subject-matter experts can't review thousands of documents by hand."),
]

y = Inches(1.5)
for title, desc in problems:
    add_shape_box(slide, Inches(0.8), y, Inches(0.12), Inches(0.8), ORANGE)
    add_textbox(slide, Inches(1.2), y, Inches(5), Inches(0.4), title,
                font_size=20, color=WHITE, bold=True)
    add_textbox(slide, Inches(1.2), y + Inches(0.4), Inches(5), Inches(0.5), desc,
                font_size=15, color=LIGHT_GRAY)
    y += Inches(1.3)

# Right column — industry examples
add_shape_box(slide, Inches(7.2), Inches(1.5), Inches(5.2), Inches(5.0),
              RGBColor(0x25, 0x25, 0x40), border_color=ACCENT_BLUE)

add_textbox(slide, Inches(7.5), Inches(1.7), Inches(4.5), Inches(0.5),
            "This Problem Is Everywhere", font_size=22, color=ACCENT_TEAL, bold=True)

industries = [
    "Pharma — Clinical trial reports with dosage charts",
    "Finance — Earnings reports with performance graphs",
    "Insurance — Claims with damage assessment photos",
    "Legal — Contracts with organizational charts",
    "Healthcare — Lab results with diagnostic images",
    "Manufacturing — Quality reports with spec diagrams",
    "Government — Regulatory filings with statistical charts",
]
tf = add_textbox(slide, Inches(7.5), Inches(2.4), Inches(4.5), Inches(3.5),
                 "", font_size=15, color=LIGHT_GRAY)
tf.paragraphs[0].text = ""
for ind in industries:
    add_para(tf, f"    {ind}", font_size=15, color=LIGHT_GRAY, space_before=Pt(10))

add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# SLIDE 3 — The Solution (high level)
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(0.8), Inches(0.4), Inches(10), Inches(0.7),
            "The Solution", font_size=36, color=WHITE, bold=True)

add_textbox(slide, Inches(0.8), Inches(1.2), Inches(11), Inches(0.6),
            "A serverless pipeline that converts any complex PDF into a fully self-contained Markdown file.",
            font_size=20, color=LIGHT_GRAY)

# Three pillars
pillars = [
    ("Parse", "Azure Document\nIntelligence", "Extract text, tables,\nand crop every figure\nas a PNG image."),
    ("Describe", "GPT-4.1\nVision", "Send each figure to a\nmultimodal LLM with\nsurrounding context."),
    ("Assemble", "Durable Functions\nOrchestrator", "Replace image placeholders\nwith AI descriptions.\nOutput: one .md file."),
]

x = Inches(1.0)
for label, service, desc in pillars:
    # Top label
    add_shape_box(slide, x, Inches(2.2), Inches(3.3), Inches(0.6), ACCENT_BLUE,
                  text=label, font_size=22, font_color=WHITE, bold=True)
    # Service name
    add_shape_box(slide, x, Inches(3.0), Inches(3.3), Inches(1.0),
                  RGBColor(0x25, 0x25, 0x40), border_color=ACCENT_BLUE,
                  text=service, font_size=16, font_color=ACCENT_TEAL, bold=True)
    # Description
    add_textbox(slide, x + Inches(0.2), Inches(4.2), Inches(3.0), Inches(1.2),
                desc, font_size=14, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)
    x += Inches(3.8)

# Arrows between pillars
for ax in [Inches(4.5), Inches(8.3)]:
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, ax, Inches(3.2), Inches(0.5), Inches(0.4))
    shape.fill.solid()
    shape.fill.fore_color.rgb = ACCENT_TEAL
    shape.line.fill.background()

# Key outcome
add_shape_box(slide, Inches(2.5), Inches(5.7), Inches(8), Inches(1.0),
              RGBColor(0x25, 0x25, 0x40), border_color=ACCENT_TEAL,
              text="Output: A single Markdown file where every visual element has a precise textual description.\nNo images needed. Fully searchable. AI-ready.",
              font_size=16, font_color=WHITE)

add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# SLIDE 4 — Architecture Deep Dive
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(0.8), Inches(0.4), Inches(10), Inches(0.7),
            "Architecture: Fan-Out / Fan-In Pattern", font_size=36, color=WHITE, bold=True)

# Pipeline boxes — vertical flow
steps = [
    ("1. HTTP Trigger", "Client POSTs PDF bytes", ACCENT_BLUE),
    ("2. Upload to Blob Storage", "pdf-input container", RGBColor(0x40, 0x40, 0x60)),
    ("3. Parse PDF", "Document Intelligence — prebuilt-layout model", ACCENT_BLUE),
    ("4. Fan-Out: Describe Figures", "N parallel GPT-4.1 Vision calls (one per figure)", ORANGE),
    ("5. Fan-In: Collect Descriptions", "task_all() waits for all parallel calls", ACCENT_TEAL),
    ("6. Assemble Final Markdown", "Replace placeholders with AI descriptions", RGBColor(0x40, 0x40, 0x60)),
    ("7. Save to Blob Storage", "pdf-output container — return URL to client", ACCENT_BLUE),
]

x_left = Inches(1.0)
y_start = Inches(1.4)
box_h = Inches(0.65)
gap = Inches(0.18)
arrow_h = Inches(0.15)

for i, (title, desc, color) in enumerate(steps):
    y = y_start + i * (box_h + gap + arrow_h)
    # Main box
    add_shape_box(slide, x_left, y, Inches(5.5), box_h, color,
                  text=f"{title}  —  {desc}", font_size=13, font_color=WHITE, bold=False)
    # Arrow between boxes
    if i < len(steps) - 1:
        add_arrow(slide, x_left + Inches(2.5), y + box_h, Inches(0.4), arrow_h)

# Right side — key design callouts
add_shape_box(slide, Inches(7.5), Inches(1.4), Inches(5.0), Inches(5.5),
              RGBColor(0x25, 0x25, 0x40), border_color=ACCENT_BLUE)

add_textbox(slide, Inches(7.8), Inches(1.6), Inches(4.4), Inches(0.5),
            "Key Design Decisions", font_size=22, color=ACCENT_TEAL, bold=True)

callouts = [
    ("Durable Functions", "No timeout limits. A 100-page PDF can take 30 min — the orchestrator checkpoints and resumes."),
    ("Parallel Fan-Out", "All figure descriptions run concurrently. Processing time = slowest single call (~15s), not N x 15s."),
    ("Context Window", "~500 chars of surrounding text are sent with each figure, giving GPT crucial domain context."),
    ("Metadata-Only Return", "Full Markdown goes to blob storage, not through the orchestrator — avoids the 1 MB Table Storage limit."),
    ("Singleton Clients", "SDK clients are initialized once per process, reused across invocations — reduces TCP/TLS overhead."),
]

y_c = Inches(2.3)
for title, desc in callouts:
    add_textbox(slide, Inches(7.8), y_c, Inches(4.4), Inches(0.3), title,
                font_size=14, color=WHITE, bold=True)
    add_textbox(slide, Inches(7.8), y_c + Inches(0.3), Inches(4.4), Inches(0.5), desc,
                font_size=12, color=LIGHT_GRAY)
    y_c += Inches(0.9)

add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# SLIDE 5 — The Reusable Pattern
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(0.8), Inches(0.4), Inches(11), Inches(0.7),
            "A Reusable Pattern for Any Document-Heavy Workflow",
            font_size=34, color=WHITE, bold=True)

add_textbox(slide, Inches(0.8), Inches(1.2), Inches(11), Inches(0.6),
            "Swap the domain prompt and the input format — the architecture stays the same.",
            font_size=20, color=LIGHT_GRAY)

# Pattern template
template_items = [
    ("Ingest", "Accept document via HTTP or event trigger. Validate and store in Blob Storage."),
    ("Parse", "Use Document Intelligence (or a domain-specific parser) to extract structure + visuals."),
    ("Fan-Out", "Send each visual element to a multimodal LLM with surrounding context — all in parallel."),
    ("Fan-In", "Collect all AI-generated descriptions. Handle failures gracefully with retry policies."),
    ("Assemble", "Merge AI descriptions back into the structured output. Store final result."),
]

y = Inches(2.0)
for i, (step, desc) in enumerate(template_items):
    num_box = add_shape_box(slide, Inches(0.8), y, Inches(0.6), Inches(0.6), ACCENT_BLUE,
                            text=str(i + 1), font_size=20, font_color=WHITE, bold=True)
    add_textbox(slide, Inches(1.6), y, Inches(3.0), Inches(0.4), step,
                font_size=18, color=WHITE, bold=True)
    add_textbox(slide, Inches(1.6), y + Inches(0.35), Inches(4.5), Inches(0.5), desc,
                font_size=13, color=LIGHT_GRAY)
    y += Inches(0.95)

# Right side — example adaptations
add_textbox(slide, Inches(7.5), Inches(2.0), Inches(5.0), Inches(0.5),
            "Example Adaptations", font_size=22, color=ACCENT_TEAL, bold=True)

adaptations = [
    ("Pharma", "Clinical trial PDFs", "Replace charts with\ntextual descriptions"),
    ("Finance", "Earnings reports", "Extract KPIs from\ngraphs as structured data"),
    ("Insurance", "Claims with photos", "Describe damage\nassessments in text"),
    ("Legal", "Contracts + diagrams", "Summarize org charts\nand process flows"),
]

y_a = Inches(2.7)
for industry, input_doc, output in adaptations:
    add_shape_box(slide, Inches(7.2), y_a, Inches(1.8), Inches(0.9), ACCENT_BLUE,
                  text=industry, font_size=14, font_color=WHITE, bold=True)
    add_shape_box(slide, Inches(9.2), y_a, Inches(1.8), Inches(0.9),
                  RGBColor(0x25, 0x25, 0x40), border_color=MED_GRAY,
                  text=input_doc, font_size=12, font_color=LIGHT_GRAY)
    # arrow
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(11.1), y_a + Inches(0.25),
                                   Inches(0.35), Inches(0.35))
    shape.fill.solid()
    shape.fill.fore_color.rgb = ACCENT_TEAL
    shape.line.fill.background()
    add_shape_box(slide, Inches(11.5), y_a, Inches(1.8), Inches(0.9),
                  RGBColor(0x25, 0x25, 0x40), border_color=ACCENT_TEAL,
                  text=output, font_size=11, font_color=WHITE)
    y_a += Inches(1.1)

add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# SLIDE 6 — Azure Services at a Glance
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(0.8), Inches(0.4), Inches(10), Inches(0.7),
            "Azure Services at a Glance", font_size=36, color=WHITE, bold=True)

services = [
    ("Azure Durable Functions", "Serverless orchestration with\ncheckpointing — no timeout limits", ACCENT_BLUE),
    ("Azure Document Intelligence", "prebuilt-layout model extracts\ntext, tables, and figures as PNGs", RGBColor(0x00, 0x6B, 0xBD)),
    ("Azure OpenAI — GPT-4.1", "Multimodal vision model describes\ncharts with pharma-grade precision", ORANGE),
    ("Azure Blob Storage", "Durable storage for input PDFs\nand output Markdown files", ACCENT_TEAL),
    ("Azure Table Storage", "Orchestration state checkpointing\n(managed by Durable framework)", RGBColor(0x68, 0x68, 0x68)),
]

cols = 3
x_start = Inches(0.8)
y_start = Inches(1.5)
box_w = Inches(3.6)
box_h = Inches(2.0)
x_gap = Inches(0.5)
y_gap = Inches(0.4)

for i, (name, desc, color) in enumerate(services):
    col = i % cols
    row = i // cols
    x = x_start + col * (box_w + x_gap)
    y = y_start + row * (box_h + y_gap)

    # Color bar on top
    add_shape_box(slide, x, y, box_w, Inches(0.1), color)
    # Box
    add_shape_box(slide, x, y + Inches(0.1), box_w, box_h - Inches(0.1),
                  RGBColor(0x25, 0x25, 0x40), border_color=RGBColor(0x40, 0x40, 0x60))
    add_textbox(slide, x + Inches(0.3), y + Inches(0.3), box_w - Inches(0.6), Inches(0.5),
                name, font_size=17, color=WHITE, bold=True, alignment=PP_ALIGN.CENTER)
    add_textbox(slide, x + Inches(0.3), y + Inches(0.9), box_w - Inches(0.6), Inches(0.9),
                desc, font_size=13, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)

# Bottom note
add_textbox(slide, Inches(0.8), Inches(5.8), Inches(11), Inches(0.8),
            "All services use connection-string auth locally and can switch to Managed Identity in production.\n"
            "The pattern requires zero infrastructure beyond these five services.",
            font_size=14, color=MED_GRAY, alignment=PP_ALIGN.CENTER)

add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# SLIDE 7 — Why This Matters / Value Proposition
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(0.8), Inches(0.4), Inches(10), Inches(0.7),
            "Why This Matters", font_size=36, color=WHITE, bold=True)

benefits = [
    ("Fully Self-Contained Output",
     "The Markdown file needs no images. A reader — human or AI — can understand the entire document from text alone. This makes the output ideal for RAG, search indexing, and downstream AI pipelines."),
    ("Scales to Any Volume",
     "Serverless architecture means zero idle costs and automatic scaling. Process 1 PDF or 10,000 — the pattern handles both without infrastructure changes."),
    ("Domain-Agnostic Architecture",
     "The fan-out/fan-in pattern is generic. Swap the system prompt from pharma to finance, insurance, or legal — the pipeline works unchanged."),
    ("Dramatically Faster Than Manual",
     "A 100-page PDF with 30+ charts processes in under 5 minutes. A human analyst would need hours. Multiply by thousands of documents per quarter."),
    ("Production-Ready Resilience",
     "Built-in retry policies, checkpoint-based orchestration, graceful fallbacks for failed figure extractions. No single failure kills the pipeline."),
]

y = Inches(1.4)
for title, desc in benefits:
    add_shape_box(slide, Inches(0.8), y, Inches(0.12), Inches(0.9), ACCENT_TEAL)
    add_textbox(slide, Inches(1.2), y, Inches(11), Inches(0.35), title,
                font_size=20, color=WHITE, bold=True)
    add_textbox(slide, Inches(1.2), y + Inches(0.35), Inches(11), Inches(0.6), desc,
                font_size=14, color=LIGHT_GRAY)
    y += Inches(1.15)

add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# SLIDE 8 — Call to Action / Next Steps
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide)
add_shape_box(slide, Inches(0), Inches(0), W, Inches(0.08), ACCENT_BLUE)

add_textbox(slide, Inches(0.8), Inches(0.4), Inches(10), Inches(0.7),
            "Next Steps", font_size=36, color=WHITE, bold=True)

# Left column
tf = add_textbox(slide, Inches(0.8), Inches(1.5), Inches(5.5), Inches(0.5),
                 "Try It Today", font_size=24, color=ACCENT_TEAL, bold=True)

next_steps = [
    "Deploy to your Azure subscription in under 30 minutes",
    "Point it at your own PDFs — any industry, any domain",
    "Customize the system prompt for your specific use case",
    "Integrate the Markdown output into your RAG / search pipeline",
    "Scale from proof-of-concept to production with zero architecture changes",
]

tf2 = add_textbox(slide, Inches(1.0), Inches(2.2), Inches(5.5), Inches(3.5),
                  "", font_size=16, color=LIGHT_GRAY)
tf2.paragraphs[0].text = ""
for step in next_steps:
    add_para(tf2, f"    {step}", font_size=16, color=LIGHT_GRAY, space_before=Pt(14))

# Right column — key message box
add_shape_box(slide, Inches(7.0), Inches(1.5), Inches(5.5), Inches(3.5),
              RGBColor(0x25, 0x25, 0x40), border_color=ACCENT_TEAL)

add_textbox(slide, Inches(7.3), Inches(1.8), Inches(4.9), Inches(0.5),
            "The Key Takeaway", font_size=22, color=ACCENT_TEAL, bold=True)

add_textbox(slide, Inches(7.3), Inches(2.5), Inches(4.9), Inches(2.0),
            "Every enterprise has complex PDFs.\n\n"
            "This pattern — parse, fan-out, describe, fan-in, assemble — "
            "is the blueprint for turning any visual-heavy document into "
            "structured, AI-ready text.\n\n"
            "It's not a one-off solution.\nIt's a reusable architecture.",
            font_size=16, color=WHITE)

# Bottom tagline
add_textbox(slide, Inches(0.8), Inches(6.0), Inches(11.5), Inches(0.6),
            "Built on Azure  |  Powered by AI  |  Ready for Production",
            font_size=20, color=MED_GRAY, alignment=PP_ALIGN.CENTER, bold=True)

add_shape_box(slide, Inches(0), H - Inches(0.08), W, Inches(0.08), ACCENT_TEAL)


# ============================================================
# Save
# ============================================================
output_path = "PDF_MultiModal_Analysis_Deck.pptx"
prs.save(output_path)
print(f"Presentation saved to: {output_path}")
