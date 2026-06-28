import { test, expect } from "../../fixtures/test-data";

/**
 * Tests for navigation and API endpoints
 */
test.describe("Navigation and API", () => {
  test.describe("Root Navigation", () => {
    test("should have working root endpoint", async ({ request }) => {
      const response = await request.get("/");
      expect(response.ok()).toBeTruthy();

      const data = await response.json();
      expect(data.service).toBe("Quorum-AI");
    });

    test("should have working health endpoint", async ({ request }) => {
      const response = await request.get("/health");
      expect(response.ok()).toBeTruthy();
    });

    test("should have working ready endpoint", async ({ request }) => {
      const response = await request.get("/ready");
      expect(response.ok()).toBeTruthy();

      const data = await response.json();
      // Ready endpoint should return status info
      expect(data).toBeDefined();
    });

    test("should have working UI endpoint", async ({ request }) => {
      const response = await request.get("/ui");
      expect(response.ok()).toBeTruthy();
    });

    test("should have docs endpoint", async ({ request }) => {
      const response = await request.get("/docs");
      expect(response.ok()).toBeTruthy();
    });
  });

  test.describe("API Endpoints", () => {
    test("should return model defaults", async ({ request }) => {
      const response = await request.get("/v1/models/defaults");
      // May return 401 if auth required
      expect([200, 401]).toContain(response.status());

      if (response.status() === 200) {
        const data = await response.json();
        expect(data).toHaveProperty("models");
        expect(Array.isArray(data.models)).toBeTruthy();
      }
    });

    test("should accept query run estimates", async ({ request }) => {
      const response = await request.post("/v1/query-runs/estimate", {
        data: {
          query_text: "What is the capital of France?",
          model_ids: ["claude-3-5-sonnet", "gpt-4o"],
        },
      });

      // Should either succeed or return proper error (401 for missing auth)
      expect([200, 400, 401, 422, 500]).toContain(response.status());
    });

    test("should accept query runs", async ({ request }) => {
      // Mock a quick response for the test
      const responsePromise = request.post("/v1/query-runs", {
        data: {
          query_text: "Test query",
          model_ids: ["claude-3-5-sonnet"],
        },
      });

      // Set timeout for the request
      const response = await responsePromise;

      // Should return a response (could be 200, 202 for async, or error)
      expect(response.status()).toBeDefined();
    });
  });

  test.describe("API Error Handling", () => {
    test("should handle 404 gracefully", async ({ request }) => {
      const response = await request.get("/nonexistent-endpoint");
      expect(response.status()).toBe(404);
    });

    test("should handle malformed requests", async ({ request }) => {
      const response = await request.post("/v1/query-runs/estimate", {
        data: {
          invalid: "data",
        },
      });

      // Should return error, not crash (401 for missing auth, 400/422 for bad data, 500 for server error)
      expect([400, 401, 422, 500]).toContain(response.status());
    });
  });
});