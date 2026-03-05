"""Quick script to POST a PDF to the local Azure Function and poll for results."""

import json
import os
import sys
import time

import requests
from azure.storage.blob import BlobServiceClient

FUNCTION_URL = "http://localhost:7071/api/pdf"
PDF_PATH = r"C:\IntraVibe\PDF2MD\PDF\RxInsights_5657563.pdf"
OUTPUT_DIR = r"C:\IntraVibe\PDF-MultiModal-Analysis\output"


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else PDF_PATH

    # 1. Upload PDF
    print(f"Uploading: {pdf_path}")
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    filename = pdf_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

    resp = requests.post(
        FUNCTION_URL,
        data=pdf_bytes,
        headers={
            "Content-Type": "application/pdf",
            "X-Filename": filename,
        },
    )

    if resp.status_code != 202:
        print(f"Error: {resp.status_code} — {resp.text}")
        return

    status_info = resp.json()
    status_url = status_info["statusQueryGetUri"]
    print(f"Orchestration started. Polling: {status_url}\n")

    # 2. Poll for completion
    while True:
        poll = requests.get(status_url)
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
            blob_url = output.get("blob_url")
            if blob_url:
                download_md(blob_url)
            break
        elif status in ("Failed", "Terminated", "Canceled"):
            print(f"Orchestration {status}.")
            print(json.dumps(data, indent=2))
            break
        else:
            print(f"  Status: {status} — waiting 10s...")
            time.sleep(10)


def download_md(blob_url: str):
    """Download the markdown file from Azure Blob Storage to local disk."""
    conn_str = os.environ.get(
        "AZURE_STORAGE_CONNECTION_STRING",
        "fill it from local settings",
    )
    container_name = os.environ.get("PDF_OUTPUT_CONTAINER", "pdf-output")

    # Extract blob name from URL (last path segment after container name)
    blob_name = blob_url.split(f"/{container_name}/")[-1]

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    blob_client = blob_service.get_container_client(container_name).get_blob_client(blob_name)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    local_path = os.path.join(OUTPUT_DIR, blob_name)

    with open(local_path, "wb") as f:
        f.write(blob_client.download_blob().readall())

    print(f"\n  Downloaded to: {local_path}")


if __name__ == "__main__":
    main()
