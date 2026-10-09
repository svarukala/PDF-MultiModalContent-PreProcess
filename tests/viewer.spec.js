const { test, expect } = require("@playwright/test");

const id = "a".repeat(32);
const interim = "<figure>\nOCR <script>window.injected = true</script>\n</figure>";
const final = "<!-- Figure 1.1 -->\n\nA detailed chart description.";

test("uploads a PDF, displays real status responses, previews and downloads both files", async ({ page }) => {
  let polls = 0;
  await page.route("**/api/pdf", async route => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["content-type"]).toBe("application/pdf");
    expect(route.request().postDataBuffer().subarray(0, 5).toString()).toBe("%PDF-");
    await route.fulfill({ status: 202, json: { id } });
  });
  await page.route(`**/api/jobs/${id}`, async route => {
    const done = ++polls > 1;
    await route.fulfill({ json: {
      id, filename: "sample.pdf", runtimeStatus: done ? "Completed" : "Running",
      progress: { stage: done ? "completed" : "describe", completed: done ? 1 : 0, total: 1,
        events: [{ sequence: polls, time: new Date().toISOString(), message: done ? "Final saved" : "describe_figure -> Azure OpenAI: 1.1" }] },
      files: { interim: `/api/jobs/${id}/files/interim`, final: done ? `/api/jobs/${id}/files/final` : null },
      output: { figures_described: 1, figures_with_fallback: 0 },
    } });
  });
  await page.route(`**/api/jobs/${id}/files/*`, route => route.fulfill({
    contentType: "text/plain", body: route.request().url().endsWith("interim") ? interim : final,
  }));
  await page.goto("/api/viewer");
  await page.getByLabel("PDF file", { exact: true }).setInputFiles({
    name: "sample.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nsynthetic"),
  });
  await page.getByRole("button", { name: "Process PDF" }).click();
  await expect(page.locator("#interim")).toHaveText(interim);
  await expect(page.locator("#calls")).toContainText("Azure OpenAI");
  await expect(page.locator("#status")).toHaveText("Completed");
  await expect(page.locator("#final")).toHaveText(final);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-final").click();
  expect((await downloadPromise).suggestedFilename()).toBe("sample_final.md");
  await page.reload();
  await expect(page.locator("#final")).toHaveText(final);
});

test("rejects invalid files without uploading", async ({ page }) => {
  let uploaded = false;
  page.on("request", request => { if (request.method() === "POST") uploaded = true; });
  await page.goto("/api/viewer");
  await page.getByLabel("PDF file", { exact: true }).setInputFiles({
    name: "bad.pdf", mimeType: "application/pdf", buffer: Buffer.from("not a PDF"),
  });
  await page.getByRole("button", { name: "Process PDF" }).click();
  await expect(page.getByRole("alert")).toContainText("valid PDF");
  expect(uploaded).toBe(false);
});

test("surfaces workflow failure and preserves interim output", async ({ page }) => {
  await page.route(`**/api/jobs/${id}`, route => route.fulfill({ json: {
    id, filename: "sample.pdf", runtimeStatus: "Failed", progress: { stage: "describe" },
    files: { interim: `/api/jobs/${id}/files/interim`, final: null }, output: {}, error: "Token quota exceeded",
  } }));
  await page.route(`**/api/jobs/${id}/files/interim`, route => route.fulfill({ body: interim }));
  await page.goto(`/api/viewer?job=${id}`);
  await expect(page.getByRole("alert")).toContainText("Token quota exceeded");
  await expect(page.locator("#interim")).toHaveText(interim);
  await expect(page.locator("#download-final")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Resume monitoring" })).toBeVisible();
});

test("does not claim legacy jobs have downloadable artifacts", async ({ page }) => {
  await page.route(`**/api/jobs/${id}`, route => route.fulfill({ json: {
    id, filename: "sample.pdf", runtimeStatus: "Completed", progress: {},
    files: { interim: null, final: null }, output: { figures_described: 100 },
  } }));
  await page.goto(`/api/viewer?job=${id}`);
  await expect(page.getByRole("alert")).toContainText("older run has no viewer artifacts");
  await expect(page.locator("#download-final")).toBeDisabled();
  await expect(page.locator("#summary")).toBeEmpty();
});
