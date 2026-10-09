"""Quick script to POST a PDF to the local Azure Function and poll for results."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from azure.storage.blob import BlobServiceClient

FUNCTION_URL = "http://localhost:7071/api/pdf"
PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"


def load_local_settings():
    """The Functions host does not export settings to this client process."""
    settings_path = PROJECT_DIR / "local.settings.json"
    if settings_path.exists():
        values = json.loads(settings_path.read_text(encoding="utf-8-sig"))["Values"]
        for key, value in values.items():
            os.environ.setdefault(key, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to a PDF to process")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--url", default=FUNCTION_URL)
    parser.add_argument("--timeout", type=float, default=3600,
                        help="Maximum polling time in seconds (default: 3600)")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if not args.pdf.is_file():
        parser.error(f"PDF does not exist: {args.pdf}")

    load_local_settings()
    pdf_path = args.pdf

    # 1. Upload PDF
    print(f"Uploading: {pdf_path}")
    pdf_bytes = pdf_path.read_bytes()

    resp = requests.post(
        args.url,
        data=pdf_bytes,
        headers={
            "Content-Type": "application/pdf",
            "X-Filename": pdf_path.name,
        },
        timeout=120,
    )

    if resp.status_code != 202:
        print(f"Error: {resp.status_code} — {resp.text}")
        return 1

    status_info = resp.json()
    status_url = status_info["statusQueryGetUri"]
    print(f"Orchestration started. Polling: {status_url}\n")

    # 2. Poll for completion
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        poll = requests.get(status_url, timeout=30)
        poll.raise_for_status()
        data = poll.json()
        status = data.get("runtimeStatus", "Unknown")

        if status == "Completed":
            output = data.get("output", {})
            print("Done!")
            print(f"  Status:            {output.get('status')}")
            print(f"  Blob URL:          {output.get('blob_url')}")
            print(f"  Figures processed: {output.get('figures_processed')}")
            print(f"  Figures described: {output.get('figures_described')}")

            # Download the .md file from blob storage
            blob_url = output["blob_url"]
            download_md(blob_url, args.output_dir)
            return 0
        elif status in ("Failed", "Terminated", "Canceled"):
            print(f"Orchestration {status}.")
            print(json.dumps(data, indent=2))
            return 1
        else:
            print(f"  Status: {status} — waiting 10s...")
            time.sleep(min(10, max(0, deadline - time.monotonic())))

    print("Timed out waiting for completion; the orchestration may still be running.")
    return 1


def download_md(blob_url: str, output_dir: Path = OUTPUT_DIR):
    """Download the markdown file from Azure Blob Storage to local disk."""
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("Set AZURE_STORAGE_CONNECTION_STRING in local.settings.json or the environment.")
    container_name = os.environ.get("PDF_OUTPUT_CONTAINER", "pdf-output")

    # Extract blob name from URL (last path segment after container name)
    url_path = urlparse(blob_url).path
    marker = f"/{container_name}/"
    if marker not in url_path:
        raise ValueError(f"Blob URL does not reference the configured container: {container_name}")
    blob_name = unquote(url_path.split(marker, 1)[1])
    filename = Path(blob_name).name
    if not filename or filename in (".", ".."):
        raise ValueError("Blob URL must contain a filename.")
    if filename == "final.md" and "/" in blob_name:
        filename = f"{blob_name.split('/')[-2]}_final.md"

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    blob_client = blob_service.get_container_client(container_name).get_blob_client(blob_name)

    output_dir.mkdir(parents=True, exist_ok=True)
    local_path = output_dir / filename

    with open(local_path, "wb") as f:
        f.write(blob_client.download_blob().readall())

    print(f"\n  Downloaded to: {local_path}")


if __name__ == "__main__":
    sys.exit(main())
