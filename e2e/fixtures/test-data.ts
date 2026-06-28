import { test as base } from "@playwright/test";

/**
 * Test data types for Quorum-AI E2E tests
 */
type QuorumTestData = {
  testQuestions: {
    simple: string;
    business: string;
    technical: string;
    policy: string;
  };
  testSession: {
    id: string;
    timestamp: number;
  };
};

export const test = base.extend<QuorumTestData>({
  testQuestions: async ({}, use) => {
    await use({
      simple: "What is machine learning?",
      business: "What are the key metrics for measuring SaaS customer retention?",
      technical:
        "How does container orchestration improve application deployment reliability?",
      policy: "What are the GDPR requirements for data retention and deletion?",
    });
  },

  testSession: async ({}, use) => {
    const session = {
      id: `test-${Date.now()}`,
      timestamp: Date.now(),
    };
    await use(session);
    // Cleanup happens automatically - no persistent state to clean
  },
});

/**
 * Shared test configurations
 */
export const TEST_CONFIG = {
  // Timeouts
  SHORT_TIMEOUT: 5000,
  MEDIUM_TIMEOUT: 15000,
  LONG_TIMEOUT: 30000,

  // Viewports
  DESKTOP: { width: 1280, height: 800 },
  MOBILE: { width: 375, height: 667 },
  TABLET: { width: 768, height: 1024 },

  // Test questions by category
  QUESTIONS: {
    SHORT: "What is AI?",
    MEDIUM: "Explain how neural networks learn through backpropagation.",
    LONG: "Compare and contrast microservices architecture with monolithic architecture, including trade-offs in scalability, deployment complexity, team organization, and operational overhead.",
  },
};

/**
 * Custom expect matchers
 */
export { expect } from "@playwright/test";