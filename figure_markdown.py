"""Map Document Intelligence figure spans to Markdown without guessing by order."""

import logging
import re


def figure_ranges(markdown: str, figure: dict) -> list[tuple[int, int]]:
    blocks = list(re.finditer(r"<figure\b[^>]*>.*?</figure>", markdown, re.DOTALL))
    ranges = []
    for span in figure.get("spans", []):
        offset, length = span["offset"], span["length"]
        if (type(offset) is not int or type(length) is not int
                or offset < 0 or length < 0 or offset + length > len(markdown)):
            raise ValueError(f"Invalid Markdown span for figure {figure['id']}")
        if not length:
            continue
        start, end = offset, offset + length
        for block in blocks:
            if block.start() <= start and end <= block.end():
                start, end = block.span()
                break
        ranges.append((start, end))
    if not ranges:
        reference = rf"!\[[^\]]*\]\(figures/{re.escape(figure['id'])}\)"
        for match in re.finditer(reference, markdown):
            start, end = match.span()
            for block in blocks:
                if block.start() <= start and end <= block.end():
                    start, end = block.span()
                    break
            ranges.append((start, end))
    return ranges


def surrounding_text(markdown: str, figure: dict, window: int = 500) -> str:
    ranges = figure_ranges(markdown, figure)
    if not ranges:
        return ""
    start, end = ranges[0]
    return markdown[max(0, start - window):min(len(markdown), end + window)]


def assemble_figures(markdown: str, figures: list[dict], descriptions: list[dict]) -> str:
    by_id = {item["figure_id"]: item["description"] for item in descriptions}
    if len(by_id) != len(descriptions):
        raise ValueError("Duplicate figure descriptions.")
    if not figures:
        figures = [{"id": key} for key in by_id]
    figure_ids = {figure["id"] for figure in figures}
    if len(figure_ids) != len(figures) or figure_ids != set(by_id):
        raise ValueError("Each extracted figure must have exactly one description.")
    if any(not isinstance(text, str) or not text.strip() for text in by_id.values()):
        raise ValueError("Figure descriptions must not be empty.")

    intervals = []
    for figure in figures:
        for start, end in figure_ranges(markdown, figure):
            intervals.append((start, end, figure["id"]))
    # Multiple extracted images can belong to one figure block. Merge their
    # overlapping spans so no description is overwritten by another replacement.
    groups = []
    for start, end, figure_id in sorted(intervals):
        if groups and start < groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], end)
            if figure_id not in groups[-1][2]:
                groups[-1][2].append(figure_id)
        else:
            groups.append([start, end, [figure_id]])

    emitted = set()

    def render(figure_id):
        emitted.add(figure_id)
        return f"\n\n<!-- Figure {figure_id} -->\n\n---\n\n{by_id[figure_id]}\n\n---\n\n"

    parts, cursor = [], 0
    for start, end, ids in groups:
        parts.append(markdown[cursor:start])
        new_ids = [figure_id for figure_id in ids if figure_id not in emitted]
        parts.append("".join(render(figure_id) for figure_id in new_ids))
        cursor = end
    parts.append(markdown[cursor:])
    unplaced = [figure["id"] for figure in figures if figure["id"] not in emitted]
    if unplaced:
        logging.warning("Appending %d figures without Markdown positions: %s", len(unplaced), unplaced)
        parts.append("\n\n## Additional figure descriptions\n\n"
                     "Document Intelligence did not return a text position for these figures.\n")
        parts.extend(render(figure_id) for figure_id in unplaced)
    result = "".join(parts)
    if emitted != figure_ids:
        raise ValueError("Some figure descriptions were not inserted.")
    return result
