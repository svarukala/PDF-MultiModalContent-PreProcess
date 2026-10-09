const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: "*.spec.js",
  workers: 1,
  use: { baseURL: "http://localhost:7071", channel: "msedge", headless: true },
});
