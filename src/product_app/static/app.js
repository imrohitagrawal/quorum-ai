// Quorum AI browser UI client.
//
// The client is a small, dependency-free SPA. It loads the model
// catalog from the JSON data island, runs the four-model workflow
// against the FastAPI backend, and renders results into the
// statically-rendered panels in workspace.html.
//
// Design goals for this rewrite:
//
//   * Treat the API as the source of truth. Never echo raw HTTP
//     status text to the user; always show a structured error with a
//     code, message, and (when relevant) an action they can take.
//   * Make state transitions observable. Buttons show a spinner and
//     disable while a request is in flight. The connection pill in the
//     header reflects session health. The run status pill mirrors the
//     server's status field.
//   * Be resilient. Polling errors do not wipe the screen; they fade
//     in as a toast. The user can dismiss any banner or toast.
//   * Be accessible. Focus is moved to the error banner when an
//     operation fails. ARIA live regions are used for progress and
//     time. The keyboard shortcuts (Ctrl/Cmd+Enter to run, Esc to
//     cancel) are documented inline.
//   * Be small. There is no framework, no build step, no transpiler.
//     The file is hand-written ES2020 that runs in every browser
//     FastAPI supports.

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Data islands and DOM cache
  // ---------------------------------------------------------------------------

  const modelCatalog = JSON.parse(
    document.getElementById("model-catalog-data").textContent || "[]",
  );
  const defaultModelIds = window.DEFAULT_MODEL_IDS;

  const el = (id) => document.getElementById(id);
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) =>
    Array.from(root.querySelectorAll(selector));

  const errorRegion = el("error-region");
  const errorTitle = el("error-region-title");
  const errorMessage = el("error-region-message");
  const errorActions = el("error-region-actions");
  const errorDismiss = el("error-region-dismiss");
  const driftRegion = el("drift-region");
  const driftMessage = el("drift-region-message");
  const driftDismiss = el("drift-region-dismiss");
  const readinessRegion = el("readiness-banner");
  const readinessTitle = el("readiness-banner-title");
  const readinessMessage = el("readiness-banner-message");
  const toastRegion = el("toast-region");
  const modelInputs = el("model-inputs");
  const modelGrid = el("model-grid");
  const debateOutput = el("debate-output");
  const synthesisOutput = el("synthesis-output");
  const noticeList = el("notice-list");
  const progressList = el("progress-list");
  const timeMeta = el("time-meta");
  const queryTextarea = el("query-text");
  const charCount = el("query-char-count");
  const validationHint = el("query-validation-hint");
  const queryError = el("query-error");
  const costConfirmation = el("cost-confirmation");
  const costConfirmationMessage = el("cost-confirmation-message");
  const proceedButton = el("proceed-run");
  const cancelEstimateButton = el("cancel-estimate");
  const estimateButton = el("estimate-run");
  const runNowButton = el("run-now");
  const costConfirmationSecondary = el("cost-confirmation-secondary");
  const copyCorrelationButton = el("copy-correlation");
  const cancelButton = el("cancel-run");
  const cancelContainer = el("cancel-run-container");
  const connectionPill = el("connection-pill");
  const connectionPillText = el("connection-pill-text");
  const statusMeta = el("status-meta");
  const workflowSteps = qsa(".workflow-step");
  const demoModeBanner = el("demo-mode-banner");
  const demoModeTarget = demoModeBanner ? demoModeBanner.querySelector("[data-demo-mode-target]") : null;
  const infoTooltip = el("info-tooltip");

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  const state = {
    csrfToken: "",
    currentEstimate: null,
    currentRunId: null,
    pollingTimer: null,
    isRunning: false,
    // The last status we rendered, used to short-circuit DOM churn.
    lastStatus: null,
    // Used by the demo banner to avoid toggling ``hidden`` on every
    // poll tick.
    lastDemoMode: null,
    // PR-0 / Bug 8: the "Current time" card freezes at the run
    // start time and only changes on a terminal transition. We
    // track which transition we're on so a poll tick in the middle
    // of a run does not overwrite the start time. The server's
    // ``result_generated_at_utc`` is regenerated on every poll
    // (it's the "now" the response was assembled at), so we can't
    // just trust the value — we have to gate the update on a
    // status transition.
    runStartTime: null,
    runTimeFinalized: false,
    // Auto-scrolls the cancel button into view exactly once on the
    // transition into a running state.
    hasScrolledToRunControls: false,
    // Workstream 3: live-readiness snapshot. ``lastReadiness`` is the
    // most recent ``/ready`` payload (state, reasons, drift ids).
    // ``lastStaleModelIds`` is the most recent ``stale_model_ids`` from
    // ``/v1/models/defaults``. Both are seeded from the page-load
    // ``window.LIVE_READINESS`` and ``window.STALE_MODEL_IDS``
    // literals so the pre-run banners can render before the first
    // client-initiated fetch completes.
    lastReadiness: null,
    lastStaleModelIds: null,
    // Track if user has attempted to submit (gates inline error display)
    submissionAttempted: false,
  };

  // ---------------------------------------------------------------------------
  // Error / toast / banner presentation
  // ---------------------------------------------------------------------------

  // Map a server "code" string to a user-friendly title. Anything we
  // don't recognise falls through to the generic "Something went wrong".
  const ERROR_TITLES = {
    AUTH_REQUIRED: "Session expired",
    SESSION_EXPIRED: "Session expired",
    CSRF_INVALID: "Security check failed",
    INVALID_MODEL_SLOT: "Model selection needs adjustment",
    SAFETY_ACK_REQUIRED: "Acknowledgement required",
    VALIDATION_ERROR: "Please check the form",
    COST_CONFIRMATION_REQUIRED: "Cost confirmation required",
    COST_LIMIT_EXCEEDED: "Run blocked: cost too high",
    QUERY_TOO_LONG: "Question is too long",
    QUERY_REQUIRED: "Question is required",
    NETWORK_UNREACHABLE: "Can't reach the server",
    RUN_FAILED: "Run failed",
    TIMEOUT: "Run timed out",
  };

  // Some error codes have a CTA the user can take. Each entry has a
  // label + an onClick callback. We render them in the error banner.
  const ERROR_ACTIONS = {
    AUTH_REQUIRED: [{ label: "Refresh session", action: () => location.reload() }],
    SESSION_EXPIRED: [{ label: "Refresh session", action: () => location.reload() }],
  };

  function showError({ code, message, hint, fieldErrors } = {}) {
    const title = (code && ERROR_TITLES[code]) || "Something went wrong";
    errorTitle.textContent = title;
    errorMessage.textContent = message || "An unexpected error occurred. Please try again.";
    errorRegion.dataset.severity = "error";
    if (fieldErrors && fieldErrors.length) {
      const list = document.createElement("ul");
      list.className = "status-banner-field-errors";
      for (const err of fieldErrors) {
        const li = document.createElement("li");
        const field = document.createElement("strong");
        field.textContent = err.field || "(field)";
        li.append(field, " — ", err.message || "invalid value");
        list.appendChild(li);
      }
      errorMessage.appendChild(list);
    } else if (hint) {
      const hintEl = document.createElement("div");
      hintEl.className = "status-banner-hint";
      hintEl.textContent = hint;
      errorMessage.appendChild(hintEl);
    }
    // Render any action buttons the registry recommends for this code.
    errorActions.replaceChildren();
    const actions = (code && ERROR_ACTIONS[code]) || [];
    for (const { label, action } of actions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button button-secondary button-compact";
      button.textContent = label;
      button.addEventListener("click", action);
      errorActions.appendChild(button);
    }
    errorRegion.hidden = false;
    // Move focus so screen readers announce the error.
    errorRegion.focus({ preventScroll: true });
    // Bring the banner into view if it is below the fold.
    errorRegion.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function clearError() {
    errorRegion.hidden = true;
    errorTitle.textContent = "";
    errorMessage.textContent = "";
    errorActions.replaceChildren();
  }

  // Render the catalog-drift banner. ``renderDriftBanner`` builds a
  // user-facing message from the stale model id list — it does NOT
  // use the operator-facing ``reasons`` text from the /ready payload,
  // which may contain internal references (file paths, module names).
  // The message is intentionally plain: the user only needs to know
  // that a default model may not work and what to do about it.
  //
  // PR-0 / Bug 9: the banner used to flag the *stale defaults*
  // regardless of which model the user actually had selected. After
  // the user moved slot 3 off the drifted default onto a working
  // model, the banner stayed up telling them their new selection
  // was broken. The fix is to intersect the stale set with the
  // currently *selected* model ids — if none of the user's four
  // picks is drifted, hide the banner. ``driftDismiss`` still
  // closes it manually for the session.
  function renderDriftBanner() {
    if (!driftRegion || !driftMessage) return;
    const stale = Array.isArray(state.lastStaleModelIds)
      ? state.lastStaleModelIds
      : [];
    if (stale.length === 0) {
      driftRegion.hidden = true;
      return;
    }
    // Only show the banner for stale models the user is actually
    // running. ``getModelIds`` may read from the static template
    // before ``refreshDefaults`` has rebuilt the dropdowns; in
    // that case we still want to flag the static defaults (the
    // pre-rebuild state is what the user sees on first paint).
    let selectedIds = [];
    try {
      selectedIds = getModelIds();
    } catch (_) {
      selectedIds = [];
    }
    const staleSet = new Set(stale);
    const activeStale = selectedIds.filter(
      (modelId) => staleSet.has(modelId),
    );
    if (activeStale.length === 0) {
      driftRegion.hidden = true;
      return;
    }
    const names = activeStale.join(", ");
    const action = activeStale.length === 1
      ? "Choose a different model from the dropdown, or contact support."
      : "Choose different models from the dropdowns, or contact support.";
    driftMessage.textContent =
      `One or more configured default models are no longer in the catalog. ` +
      `Your selections still work — this just means the defaults you see on a fresh ` +
      `page may differ from what was last cached.`;
    driftRegion.hidden = false;
  }
  if (driftDismiss) {
    driftDismiss.addEventListener("click", () => {
      driftRegion.hidden = true;
    });
  }

  // Seed the readiness and drift caches from the page-load data
  // islands. The islands are populated server-side by
  // ``_render_workspace_html`` (see ``product_app.main``). A bad /
  // missing island must not break boot — we fall back to an empty
  // snapshot and let the first ``refreshReadiness`` call fill in the
  // real values.
  function seedReadinessFromPageLoad() {
    const seed = window.LIVE_READINESS;
    if (seed && typeof seed === "object") {
      state.lastReadiness = {
        state: typeof seed.state === "string" ? seed.state : null,
        reasons: Array.isArray(seed.reasons) ? seed.reasons.slice() : [],
        catalog_drift_ids: Array.isArray(seed.catalog_drift_ids)
          ? seed.catalog_drift_ids.slice()
          : [],
      };
    }
    if (Array.isArray(window.STALE_MODEL_IDS)) {
      state.lastStaleModelIds = window.STALE_MODEL_IDS.slice();
    }
  }

  // Render the pre-run honesty banner. The banner is a *deployment*
  // disclosure: it tells the user the answers they will see are
  // templated, before they have to run a query to find out. The
  // per-run partial-live disclosure stays in
  // ``renderModelPanels`` (it owns ``#demo-mode-banner``). Two
  // surfaces, two distinct signals.
  function applyReadinessState() {
    // The drift banner is the sibling of the readiness banner; both
    // are driven by the same cache so they cannot disagree.
    renderDriftBanner();
    if (!readinessRegion || !readinessTitle || !readinessMessage) return;
    const readiness = state.lastReadiness;
    // No snapshot yet (probe never ran): keep the banner hidden. The
    // first ``refreshReadiness`` call will fill the cache and
    // re-trigger this renderer.
    if (!readiness || !readiness.state) {
      readinessRegion.hidden = true;
      readinessTitle.textContent = "Live execution is unavailable";
      readinessMessage.textContent = "";
      return;
    }
    const stateName = readiness.state;
    if (stateName === "live") {
      // No offline disclosure. If there is drift we still show the
      // drift banner (the surface above the composer) but the
      // readiness banner itself is hidden — the model answers will
      // come from real providers, and the drift banner is the
      // dedicated place to flag catalog drift.
      readinessRegion.hidden = true;
      readinessTitle.textContent = "Live execution is unavailable";
      readinessMessage.textContent = "";
      return;
    }
    let severity;
    let title;
    let body;
    if (stateName === "offline_by_no_key") {
      severity = "warning";
      title = "Live execution is unavailable";
      body =
        "Live execution is enabled on this deployment, but the model " +
        "provider key is missing. Every model answer and the synthesis " +
        "below will come from Quorum's local simulation helpers. They " +
        "look like real output but are not generated by GPT, Claude, " +
        "Gemini, or Deepseek. Ask the operator to add the key and " +
        "restart, or turn live execution off to acknowledge offline mode.";
    } else if (stateName === "offline_by_config") {
      // Deliberate operator choice — info severity, not warning.
      severity = "info";
      title = "Live execution is turned off";
      body =
        "Live execution is turned off. Every model answer and the " +
        "synthesis below will come from Quorum's local simulation " +
        "helpers. They look like real output but are not generated by " +
        "GPT, Claude, Gemini, or Deepseek. This is a deliberate " +
        "offline / dev mode.";
    } else {
      // Unknown state value (server might add a new one in the
      // future). Stay honest: render the raw state, keep the
      // warning severity.
      severity = "warning";
      title = "Live-readiness state is unrecognised";
      body =
        `The /ready endpoint reported an unknown state ` +
        `("${stateName}"). Treat model answers as unverified until the ` +
        `operator confirms the deployment is configured correctly.`;
    }
    // If we are in an offline state and the probe also flagged
    // catalog drift, surface it here too so the user does not have
    // to scroll up to the drift banner. The live path returns
    // earlier so this branch only runs for offline_*, where the
    // drill-down is genuinely useful.
    const drift = Array.isArray(readiness.catalog_drift_ids)
      ? readiness.catalog_drift_ids
      : [];
    if (drift.length > 0) {
      body +=
        ` Catalog drift: the following static default model ids are ` +
        `no longer in the live  catalog — ${drift.join(", ")}. The app ` +
        `will still call them, but they may have been renamed or moved.`;
    }
    readinessRegion.dataset.severity = severity;
    readinessTitle.textContent = title;
    readinessMessage.textContent = body;
    readinessRegion.hidden = false;
  }

  // Pull the current readiness snapshot from the server. The /ready
  // endpoint re-runs the probe on every hit so the response reflects
  // the *current* settings, not a boot snapshot. We also refresh the
  // /v1/models/defaults payload so the drift diagnostic stays in
  // sync with the live catalog. Best-effort: any error is logged to a
  // toast and the cached snapshot is preserved, so a flaky probe
  // cannot wipe a known-good banner.
  async function refreshReadiness() {
    let nextReadiness = null;
    let nextStale = null;
    try {
      const ready = await api("/ready", { method: "GET" });
      const live = ready && ready.live_readiness;
      if (live && typeof live === "object") {
        nextReadiness = {
          state: typeof live.state === "string" ? live.state : null,
          reasons: Array.isArray(live.reasons) ? live.reasons.slice() : [],
          catalog_drift_ids: Array.isArray(live.catalog_drift_ids)
            ? live.catalog_drift_ids.slice()
            : [],
        };
      }
    } catch (error) {
      // Keep the previous snapshot; surface a non-blocking toast so
      // the operator knows the probe is unreachable.
      toast({
        message: `Live-readiness probe failed: ${error.message || "unknown error"}`,
        tone: "warn",
        timeout: 5000,
      });
    }
    try {
      // /v1/models/defaults requires a session cookie. If the session
      // bootstrap has not completed yet (we are called from boot
      // before initSession), fall back to the page-load seed and try
      // again on the next refresh tick.
      const defaults = await api("/v1/models/defaults", { method: "GET" });
      if (Array.isArray(defaults && defaults.stale_model_ids)) {
        nextStale = defaults.stale_model_ids.slice();
      }
    } catch (_) {
      // Session not yet issued, or transient error. Leave the cache
      // alone — renderDriftBanner / applyReadinessState will fall
      // back to the page-load seed.
    }
    if (nextReadiness) state.lastReadiness = nextReadiness;
    if (nextStale) state.lastStaleModelIds = nextStale;
    applyReadinessState();
  }

  // Lightweight toast for transient, non-blocking messages.
  function toast({ message, tone = "info", timeout = 4500 } = {}) {
    const card = document.createElement("div");
    card.className = `toast toast-${tone}`;
    card.setAttribute("role", tone === "error" ? "alert" : "status");
    const body = document.createElement("div");
    body.className = "toast-body";
    body.textContent = message;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.innerHTML = "&times;";
    close.addEventListener("click", () => dismissToast(card));
    card.append(body, close);
    toastRegion.appendChild(card);
    const timer = window.setTimeout(() => dismissToast(card), timeout);
    card.dataset.timer = String(timer);
  }

  function dismissToast(card) {
    if (card.dataset.timer) {
      window.clearTimeout(Number(card.dataset.timer));
      delete card.dataset.timer;
    }
    card.classList.add("toast-dismissing");
    // Wait for the fade-out animation before removing the node.
    window.setTimeout(() => card.remove(), 220);
  }

  // ---------------------------------------------------------------------------
  // Connection pill and status pill
  // ---------------------------------------------------------------------------

  const STATUS_LABELS = {
    idle: "Idle",
    initial_answers_running: "Initial answers running",
    initial_answers_completed: "Initial answers ready",
    debate_round_1_running: "Debate round 1",
    debate_round_1_completed: "Debate round 1 ready",
    debate_round_2_running: "Debate round 2",
    debate_round_2_completed: "Debate round 2 ready",
    synthesis_running: "Synthesising",
    completed: "Completed",
    partial: "Partial result",
    failed: "Failed",
    timed_out: "Timed out",
    cancelled: "Cancelled",
  };

  // Error classification system for failed runs
  const ERROR_TYPES = {
    // Recoverable - show banner with retry hint
    CONNECTION_TIMEOUT: { recoverable: true, message: "Connection timed out. Please try again." },
    RATE_LIMITED: { recoverable: true, message: "Rate limit exceeded. Wait a moment and retry." },
    NETWORK_ERROR: { recoverable: true, message: "Network error. Check your connection." },
    PROVIDER_TIMEOUT: { recoverable: true, message: "Provider request timed out. Please try again." },

    // Unrecoverable - show error code + contact support
    INVALID_API_KEY: { errorCode: "E1001" },
    INSUFFICIENT_BALANCE: { errorCode: "E1002" },
    API_KEY_MISSING: { errorCode: "E1003" },
    PERMISSION_DENIED: { errorCode: "E1004" },
    CATALOG_UNAVAILABLE: { errorCode: "E1005" },
    MODEL_NOT_FOUND: { errorCode: "E1006" },
  };

  // Friendly band labels for ``CostThresholdAction``. The raw enum
  // value (``allow`` / ``require_confirmation`` / ``block``) is
  // fine for behavior comparisons but reads oddly in the UI
  // ("0.0134 USD / allow"). Map the enum to the same wording the
  // cost confirmation callout already uses, and fall back to the
  // raw value if a future server-side value sneaks through.
  const COST_BAND_LABEL = {
    allow: "normal band",
    require_confirmation: "upper band",
    block: "blocked",
  };

  function formatCostBand(action) {
    return COST_BAND_LABEL[action] ?? action;
  }

  function getErrorType(errorCode) {
    // Handle error codes from different sources
    if (typeof errorCode === 'string') {
      // Clean error codes (remove "E" prefix if present)
      const cleanCode = errorCode.replace(/^E/i, '');

      // Map to our standard codes
      for (const [key, type] of Object.entries(ERROR_TYPES)) {
        if (type.errorCode === `E${cleanCode}` || type.errorCode === cleanCode) {
          return type;
        }
      }

      // Default to unrecoverable if unknown code
      return { errorCode: `E${cleanCode}` };
    }

    // If no error code, treat as network error (most common)
    return ERROR_TYPES.NETWORK_ERROR;
  }

  // Static FX rates (units of foreign currency per 1 USD). Intentionally
  // not live — the cost figure is already framed as "a local planning
  // estimate, not a provider quote" in the existing disclaimer copy at
  // app.js:668, and the same honesty applies here. Refresh quarterly.
  // (USD is the guardrail currency and the provider-billed currency;
  // it must remain primary — see costs.py:35-36.)
  const FX_PER_USD = {
    EUR: 0.93,
    GBP: 0.79,
    INR: 83.5,
    JPY: 156.0,
    AUD: 1.52,
    CAD: 1.37,
    CHF: 0.90,
    CNY: 7.25,
    SGD: 1.35,
    BRL: 5.10,
  };

  // Detects the user's local currency from the browser locale and
  // returns a primary/secondary pair for display. When the locale
  // resolves to USD (or anything not in FX_PER_USD), secondary is an
  // empty string and the callout renders only the USD primary.
  //
  // PR-0 / Bug 3: the old fixed ``.toFixed(2)`` rounded any
  // sub-cent cost to ``"$0.00 USD"`` (e.g. ``0.0023`` displayed as
  // free). Use a magnitude-aware decimal count: 4 dp below 1¢, 3 dp
  // below $1, 2 dp otherwise. Strip trailing zeros so the display
  // stays compact (e.g. ``$0.0023`` not ``$0.00230``).
  function formatUsd(usdAmount) {
    const num = Number(usdAmount);
    if (!Number.isFinite(num)) return "$0.00 USD";
    let decimals;
    if (num < 0.01) {
      decimals = 4;
    } else if (num < 1) {
      decimals = 3;
    } else {
      decimals = 2;
    }
    // ``toFixed`` returns a string with trailing zeros; strip them so
    // ``0.0023`` is shown as ``"$0.0023"`` rather than ``"$0.00230"``.
    const fixed = num.toFixed(decimals);
    const trimmed = fixed.replace(/\.?0+$/, "");
    const withCents = trimmed.includes(".") ? trimmed : `${trimmed}.00`;
    return `$${withCents} USD`;
  }

  function formatCostWithLocal(usdAmount) {
    const usd = formatUsd(usdAmount);
    let locale;
    try {
      locale = Intl.NumberFormat().resolvedOptions().locale;
    } catch (_) {
      return { primary: usd, secondary: "" };
    }
    // Resolve a likely currency from the locale. Fall back to USD if
    // Intl rejects the locale or returns something unknown.
    let currency = "USD";
    try {
      const parts = new Intl.NumberFormat(locale).formatToParts(1);
      for (const part of parts) {
        if (part.type === "currency") {
          currency = part.value;
          break;
        }
      }
    } catch (_) {
      return { primary: usd, secondary: "" };
    }
    if (currency === "USD" || !FX_PER_USD[currency]) {
      return { primary: usd, secondary: "" };
    }
    const localAmount = Number(usdAmount) * FX_PER_USD[currency];
    let localFormatted;
    try {
      localFormatted = new Intl.NumberFormat(locale, {
        style: "currency",
        currency,
        maximumFractionDigits: 4,
      }).format(localAmount);
    } catch (_) {
      return { primary: usd, secondary: "" };
    }
    return {
      primary: usd,
      secondary: `≈ ${localFormatted} · planning estimate, not a provider quote`,
    };
  }

  // Renders the secondary (local-currency) line into the cost callout.
  // Hides the element when there is no secondary text (i.e. user is in
  // a USD locale or an unsupported currency).
  function renderCostSecondary(usdAmount) {
    if (!costConfirmationSecondary) return;
    const { secondary } = formatCostWithLocal(usdAmount);
    if (secondary) {
      costConfirmationSecondary.textContent = secondary;
      costConfirmationSecondary.hidden = false;
    } else {
      costConfirmationSecondary.textContent = "";
      costConfirmationSecondary.hidden = true;
    }
  }

  function setConnectionPill(stateName, label) {
    connectionPill.dataset.state = stateName;
    connectionPillText.textContent = label;
  }

  function setStatusPill(stateName, label) {
    const pill = statusMeta.querySelector(".status-pill");
    if (!pill) return;
    pill.dataset.state = stateName;
    const labelEl = pill.querySelector("span:last-child");
    if (labelEl) labelEl.textContent = label;
  }

  // ---------------------------------------------------------------------------
  // API client
  // ---------------------------------------------------------------------------

  // Friendly status text. We never want the user to see the raw
  // "Unprocessable Content" / "Bad Request" status text. Map common
  // statuses to domain-relevant copy.
  const STATUS_COPY = {
    400: "The request was rejected by the server.",
    401: "Your session has expired. Please refresh the page.",
    403: "You do not have permission to perform this action.",
    404: "The requested resource could not be found.",
    408: "The request took too long. Please try again.",
    409: "There was a conflict with the current state. Please refresh and retry.",
    413: "The request was too large to send.",
    422: "Some of the values you provided could not be processed.",
    429: "You are sending requests too quickly. Please wait a moment.",
    500: "The server encountered an unexpected error. Our team has been notified.",
    502: "The upstream service is temporarily unavailable. Please try again in a moment.",
    503: "The service is temporarily unavailable. Please try again in a moment.",
    504: "The upstream service took too long to respond. Please try again.",
  };

  class ApiError extends Error {
    constructor({ status, code, message, slotErrors, fieldErrors, partial }) {
      super(message || STATUS_COPY[status] || "Unexpected error");
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.slotErrors = slotErrors;
      this.fieldErrors = fieldErrors;
      this.partial = partial;
    }
  }

  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        credentials: "same-origin",
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(state.csrfToken ? { "x-csrf-token": state.csrfToken } : {}),
          ...(options.headers || {}),
        },
      });
    } catch (networkError) {
      // Network failure (offline, DNS, CORS, abort). The user can
      // usually recover by retrying once connectivity returns.
      throw new ApiError({
        status: 0,
        code: "NETWORK_UNREACHABLE",
        message: "We could not reach the server. Check your network connection and try again.",
      });
    }
    if (!response.ok) {
      // Try to parse a structured body. If the response is not JSON we
      // synthesise a friendly message from the status code.
      let payload = null;
      try {
        payload = await response.json();
      } catch (_) {
        throw new ApiError({
          status: response.status,
          code: null,
          message: STATUS_COPY[response.status] || response.statusText,
        });
      }
      const detail = payload && (payload.detail || payload.error || payload);
      const code = (detail && detail.code) || null;
      let message = (detail && detail.message) || STATUS_COPY[response.status] || response.statusText;
      // For 422 with validation errors, surface the per-field message so
      // the user knows which field to fix.
      if (response.status === 422 && Array.isArray(detail && detail.slot_errors)) {
        const firstSlot = detail.slot_errors[0];
        if (firstSlot) {
          message = `Model slot ${firstSlot.slot_number} could not be accepted: ${firstSlot.message || "invalid value"}`;
        }
      }
      throw new ApiError({
        status: response.status,
        code,
        message,
        slotErrors: detail && detail.slot_errors,
        fieldErrors: detail && detail.field_errors,
        partial: payload,
      });
    }
    return response.json();
  }

  // ---------------------------------------------------------------------------
  // Model slot inputs
  // ---------------------------------------------------------------------------

  function getModelIds() {
    return [...document.querySelectorAll("[data-model-slot]")].map((input) =>
      input.value.trim(),
    );
  }

  function renderModelOptions(currentModelId, currentIndex, selectedModelIds) {
    const takenIds = new Set(
      selectedModelIds.filter((_, index) => index !== currentIndex),
    );
    // PR-0 / Bug 10: vendor-scoped filtering. The defaults are
    // curated so each slot targets a different vendor family
    // (openai / anthropic / google / deepseek). If we showed the
    // entire catalog and only filtered out the exact other slots'
    // selected ids, slot 1 and slot 3 both showed the openai
    // fallbacks (gpt-4.1, o3) as their first non-selected options
    // — confusing because the user picked google for slot 3, not
    // "any other openai model." Restrict each dropdown to the
    // vendor prefix of the slot's currently selected model id
    // (``openai/``, ``anthropic/``, etc.) so the visible options
    // always belong to the family the slot is supposed to pick
    // from. The "curated default — not in live catalog" synthetic
    // option is preserved for the case where the live catalog
    // no longer lists the default.
    const vendorPrefix = currentModelId.split("/", 1)[0];
    const catalogHasDefault = modelCatalog.some(
      (option) => option.model_id === currentModelId,
    );
    const options = [];
    if (!catalogHasDefault) {
      const synthetic = document.createElement("option");
      synthetic.value = currentModelId;
      synthetic.textContent = `${currentModelId} (curated default — not in live catalog)`;
      synthetic.selected = true;
      options.push(synthetic);
    }
    for (const option of modelCatalog) {
      // Vendor scope: only show models from the slot's vendor
      // family. The exact mutual-exclusion check is preserved as
      // a belt-and-braces guard, but the vendor filter does the
      // heavy lifting.
      if (!option.model_id.startsWith(`${vendorPrefix}/`)) {
        continue;
      }
      if (takenIds.has(option.model_id) && option.model_id !== currentModelId) {
        continue;
      }
      const optionElement = document.createElement("option");
      optionElement.value = option.model_id;
      optionElement.textContent = `${option.label} (${option.model_id})`;
      if (option.model_id === currentModelId) {
        optionElement.selected = true;
      }
      options.push(optionElement);
    }
    return options;
  }

  function renderModelInputs(modelIds) {
    const fields = modelIds.map((modelId, index) => {
      const field = document.createElement("div");
      field.className = "field";
      const label = document.createElement("label");
      label.htmlFor = `model-${index + 1}`;
      label.textContent = `Model slot ${index + 1}`;
      const select = document.createElement("select");
      select.id = `model-${index + 1}`;
      select.dataset.modelSlot = "";
      select.dataset.slotIndex = String(index);
      for (const option of renderModelOptions(modelId, index, modelIds)) {
        select.appendChild(option);
      }
      field.append(label, select);
      return field;
    });
    modelInputs.replaceChildren(...fields);
  }

  // ---------------------------------------------------------------------------
  // Progress + result rendering
  // ---------------------------------------------------------------------------

  function renderProgress(progress) {
    if (!progress) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No active run.";
      progressList.replaceChildren(empty);
      updateWorkflowProgress(null);
      return;
    }
    const cards = progress.stages.map((stage) => {
      const card = document.createElement("div");
      card.className = "stage";
      card.dataset.state = stage.state;
      const header = document.createElement("div");
      header.className = "stage-header";
      const label = document.createElement("span");
      label.className = "stage-label";
      label.textContent = stage.stage.replaceAll("_", " ");
      const state = document.createElement("span");
      state.className = `stage-state stage-state-${stage.state}`;
      state.textContent = stage.state;
      header.append(label, state);
      card.appendChild(header);
      if (stage.detail) {
        const detail = document.createElement("div");
        detail.className = "stage-detail";
        detail.textContent = stage.detail;
        card.appendChild(detail);
      }
      return card;
    });
    progressList.replaceChildren(...cards);

    // Phase 4: Update workflow progress indicator
    const runningStage = progress.stages.find(s => s.state === "running");
    if (runningStage) {
      updateWorkflowProgress(mapStageToStep(runningStage.stage));
      return;
    }

    // No stage is running — the run has ended. Check terminal state.
    const terminalStates = ["completed", "partial", "failed", "timed_out", "cancelled"];
    const terminalStage = progress.stages.find(
      s => terminalStates.includes(s.state)
    );

    if (terminalStage) {
      if (terminalStage.state === "completed" || terminalStage.state === "partial") {
        // Run finished — show all steps as completed
        updateWorkflowProgressCompleted();
      } else {
        // Run failed/timed_out/cancelled — reset to initial state
        updateWorkflowProgress(null);
      }
    }
  }

  function mapStageToStep(stageName) {
    if (!stageName) return null;  // No stage = clear indicator

    if (stageName === "orchestrate_models" || stageName.startsWith("model_")) return "models";
    if (stageName.startsWith("debate") || stageName.startsWith("critique")) return "debate";
    if (stageName === "synthesize" || stageName === "final_synthesis") return "synthesis";

    // Unknown stage = don't change current step
    return null;
  }

  // Phase 4: Workflow progress indicator
  function updateWorkflowProgress(currentStage) {
    if (!workflowSteps.length) return;
    // Map stages: question -> models -> debate -> synthesis
    const stageOrder = ["question", "models", "debate", "synthesis"];

    // Handle null (no active run) — reset to initial state
    if (currentStage === null) {
      workflowSteps.forEach((step, index) => {
        step.dataset.state = index === 0 ? "active" : "";
        // Update ARIA attributes for accessibility
        step.setAttribute("aria-selected", index === 0 ? "true" : "false");
        step.setAttribute("tabindex", index === 0 ? "0" : "-1");
      });
      return;
    }

    const currentIndex = stageOrder.indexOf(currentStage);

    workflowSteps.forEach((step, index) => {
      const stepName = step.dataset.step;
      const stepIndex = stageOrder.indexOf(stepName);

      if (stepIndex < currentIndex) {
        step.dataset.state = "completed";
        step.setAttribute("aria-selected", "true");
        step.setAttribute("tabindex", "0");
      } else if (stepIndex === currentIndex) {
        step.dataset.state = "active";
        step.setAttribute("aria-selected", "true");
        step.setAttribute("tabindex", "0");
      } else {
        step.dataset.state = "";
        step.setAttribute("aria-selected", "false");
        step.setAttribute("tabindex", "-1");
      }
    });
  }

  // Phase 4: Show completed state for finished runs
  function updateWorkflowProgressCompleted() {
    if (!workflowSteps.length) return;

    workflowSteps.forEach((step, index) => {
      step.dataset.state = "completed";
      step.setAttribute("aria-selected", "true");
      step.setAttribute("tabindex", "0");
    });
  }

  function createSafeLink(title, url) {
    const link = document.createElement("a");
    link.textContent = title;
    try {
      const parsedUrl = new URL(url);
      if (parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:") {
        link.href = parsedUrl.toString();
        link.target = "_blank";
        link.rel = "noreferrer";
        return link;
      }
    } catch (_) {
      // Fall through to plain text.
    }
    return document.createTextNode(url);
  }

  // Sources whose ``provider`` path is a Quorum-side stub (the local
  // simulation helper, or the fallback search helper) point at the
  // ``example.test`` IANA-reserved domain, which never resolves.
  // Rendering them as anchors would either navigate the browser to a
  // broken URL or open a blank tab. Instead we render the title as
  // muted text with a small badge so the simulation state stays visible
  // at the source-list level — not just in the demo-mode banner above
  // the model grid.
  const STUB_SOURCE_PROVIDERS = new Set(["local_simulation", "fallback_search"]);
  const STUB_SOURCE_TAG_TEXT = {
    local_simulation: "simulated",
    fallback_search: "fallback stub",
  };

  function renderStubSource(source) {
    const li = document.createElement("li");
    li.classList.add("source-stub");
    const title = document.createElement("span");
    title.className = "source-stub-title";
    title.textContent = source.title;
    title.title =
      "This is a placeholder; the URL does not resolve to a real source.";
    title.setAttribute("aria-label", `${source.title} — simulated source`);
    const badge = document.createElement("span");
    badge.className = "source-stub-tag";
    badge.textContent = STUB_SOURCE_TAG_TEXT[source.provider] || "stub";
    li.append(title, " ", badge);
    return li;
  }

  function renderSourceList(sources) {
    const list = document.createElement("ul");
    list.className = "source-list";
    if (sources && sources.length) {
      for (const source of sources) {
        if (STUB_SOURCE_PROVIDERS.has(source.provider)) {
          list.appendChild(renderStubSource(source));
          continue;
        }
        const li = document.createElement("li");
        const maybeLink = createSafeLink(source.title, source.url);
        li.appendChild(maybeLink);
        if (source.is_fallback) {
          li.classList.add("source-fallback");
          const badge = document.createElement("span");
          badge.className = "badge badge-fallback";
          badge.textContent = "fallback";
          li.append(" ", badge);
        }
        list.appendChild(li);
      }
    } else {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "No source links yet.";
      list.appendChild(li);
    }
    return list;
  }

  function renderModelPanels(modelAnswers = [], result = null) {
    // The demo-mode banner lives in static HTML directly above the
    // model grid. We toggle its ``hidden`` attribute here and update
    // the body copy. The banner has ``role="alert"`` and
    // ``aria-live="assertive"`` so screen readers announce it before
    // the polite model-panel announcements.
    //
    // The server now returns per-run ``live_count`` and ``local_count``
    // so the banner copy can be honest about partial-live runs. Three
    // states: all-live (hide), all-local (full copy), mixed (partial
    // copy). The boolean ``result.demo_mode`` is preserved for
    // back-compat but is no longer the sole signal.
    //
    // Pre-run (``refreshDefaults`` calls this with ``result = null``
    // before any query has been issued) we hide the banner outright
    // — there are no live/local counts yet, so the mixed branch would
    // render "null of null model answers" which is dishonest copy.
    // The pre-run disclosure is the job of the readiness banner.
    if (demoModeBanner) {
      if (result == null) {
        if (!state.lastDemoMode || state.lastDemoMode !== "pre-run") {
          state.lastDemoMode = "pre-run";
          demoModeBanner.hidden = true;
        }
        // Fall through to render the (empty) model grid below.
      } else {
        const liveCount = Number.isFinite(result.live_count) ? result.live_count : null;
        const localCount = Number.isFinite(result.local_count) ? result.local_count : null;
        const fallbackCount =
          liveCount != null && localCount != null ? liveCount + localCount : null;
        let bannerState;
        let bannerCopy = "";
        if (liveCount === 4) {
          bannerState = "all-live";
          bannerCopy = "";
        } else if (liveCount === 0) {
          bannerState = "all-local";
          bannerCopy =
            "Live execution is turned off, so all four model answers and the synthesis below come from Quorum's local simulation helpers. They look like real output but are not generated by GPT, Claude, Gemini, or Deepseek. Ask the operator to enable live execution to run against real models.";
        } else {
          bannerState = "mixed";
          bannerCopy =
            `${liveCount} of ${fallbackCount ?? 4} model answers came from a live provider; ` +
            `the remaining ${localCount ?? fallbackCount - liveCount} are from Quorum's local simulation helpers. ` +
            `The synthesis below is also produced by a configured synthesis model. ` +
            `Ask the operator to enable live execution for all four models to run everything against real providers.`;
        }
        if (bannerState !== state.lastDemoMode) {
          state.lastDemoMode = bannerState;
          if (bannerState === "all-live") {
            demoModeBanner.hidden = true;
          } else {
            if (demoModeTarget) {
              demoModeTarget.textContent = bannerCopy;
            }
            demoModeBanner.hidden = false;
          }
        }
      }
    }
    const cards = defaultModelIds.map((fallbackModelId, index) => {
      const slot = modelAnswers.find((answer) => answer.slot_number === index + 1);
      const modelId = slot?.model_id || getModelIds()[index] || fallbackModelId;
      // Prefer the server-supplied ``display_name`` (catalog short
      // name like "Claude Haiku 4.5") over the raw model_id. The id
      // is still shown as a small subtitle so the user can identify
      // the exact endpoint if they need to.
      const displayName = slot?.display_name || modelId;
      const article = document.createElement("article");
      article.className = "model-card";
      const header = document.createElement("header");
      header.className = "model-card-header";
      const heading = document.createElement("h3");
      const title = document.createElement("span");
      title.className = "model-card-title";
      title.textContent = displayName;
      const sub = document.createElement("span");
      sub.className = "model-card-slot";
      sub.textContent = `Slot ${index + 1} · ${modelId}`;
      heading.append(title, sub);
      // Model card info icon - explains what this card represents
      const modelCardInfo = document.createElement("button");
      modelCardInfo.type = "button";
      modelCardInfo.className = "info-icon";
      modelCardInfo.setAttribute("data-info-icon", "");
      modelCardInfo.setAttribute("data-info-text", "This shows one model's initial answer. After all four models respond, each model is asked to revise its answer after reading the others — the refined version replaces this card.");
      modelCardInfo.setAttribute("aria-label", "What is this card?");
      modelCardInfo.innerHTML = "&#9432;";
      heading.append(modelCardInfo);
      const statusPill = document.createElement("span");
      const statusValue = slot?.status || "pending";
      statusPill.className = "status-pill";
      statusPill.dataset.state = statusValue;
      // C15: build the pill content with createElement + textContent
      // instead of innerHTML. The status value is server-controlled
      // today, but the innerHTML path is one forgotten escape call
      // away from an XSS. The DOM-construction form is safe by
      // construction.
      const dot = document.createElement("span");
      dot.className = "status-pill-dot";
      dot.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.textContent = statusValue;
      statusPill.append(dot, label);
      header.append(heading, statusPill);
      article.appendChild(header);
      const body = document.createElement("div");
      body.className = "model-card-body";
      if (slot) {
        body.appendChild(
          renderAnswerSection(slot.answer_text, { label: "Copy answer" }),
        );
        if (!slot.answer_text) {
          // Surface the existing placeholder copy when the slot is
          // empty so the user understands the card isn't broken.
          const placeholder = document.createElement("p");
          placeholder.className = "muted";
          placeholder.textContent = "Provider did not return text.";
          body.appendChild(placeholder);
        }
      } else {
        // Check if run failed - show error state instead of pending
        const runStatusValue = result?.status;
        if (runStatusValue && ['failed', 'timed_out', 'cancelled'].includes(runStatusValue)) {
          const errorPlaceholder = document.createElement("p");
          errorPlaceholder.className = "error-placeholder";
          errorPlaceholder.textContent = "Models did not respond — see error details above.";
          body.appendChild(errorPlaceholder);
        } else {
          const placeholder = document.createElement("p");
          placeholder.className = "muted";
          placeholder.textContent = "Awaiting provider output.";
          body.appendChild(placeholder);
        }
      }
      article.appendChild(body);
      // When the model is complete but carried a ``provider_notice`` —
      // e.g. it was a local-simulation answer with an honest disclosure,
      // or a fallback-search answer — surface the notice on the card so
      // the user can tell at a glance why the path is what it is.
      // We do NOT render this for pending slots (notice would just be
      // stale copy) or for slots whose ``answer_text`` is itself a
      // placeholder string.
      if (slot && slot.provider_notice && runStatusValue !== "pending") {
        const notice = document.createElement("p");
        notice.className = "model-card-notice";
        notice.textContent = slot.provider_notice;
        article.appendChild(notice);
      }
      const meta = document.createElement("div");
      meta.className = "model-card-meta";
      const path = document.createElement("div");
      // C15: use createElement + textContent for the meta line.
      // The previous innerHTML form relied on the developer to
      // remember to escape the user-influenced ``provider_path``
      // value. The DOM-construction form is safe by construction.
      const pathLabel = document.createElement("strong");
      pathLabel.textContent = "Provider path: ";
      const pathValue = document.createElement("span");
      pathValue.textContent = slot?.provider_path || "pending";
      path.append(pathLabel, pathValue);
      const latency = document.createElement("div");
      const latencyLabel = document.createElement("strong");
      latencyLabel.textContent = "Latency: ";
      const latencyValue = document.createElement("span");
      latencyValue.textContent =
        slot?.latency_ms != null ? `${slot.latency_ms} ms` : "—";
      latency.append(latencyLabel, latencyValue);
      meta.append(path, latency);
      article.appendChild(meta);
      const sources = renderSourceList(slot?.sources);
      article.appendChild(sources);
      return article;
    });
    modelGrid.replaceChildren(...cards);
  }

  // Tooltip copy per synthesis section. Each entry is intentionally
  // honest about the fact that these sections are produced by
  // Quorum's templated synthesis helper regardless of provider path —
  // they are never generated by a model, even with a live API key.
  const SYNTHESIS_TOOLTIPS = {
    "Consensus":
      "A templated summary of how many of the four models returned a usable answer, and what fraction of claims were supported by visible sources. Templated by Quorum; no model generates this.",
    "Disagreement":
      "A templated note about preserved disagreement — typically whether the four answers diverged on which provider path was used. Templated by Quorum; no model generates this.",
    "Source support":
      "The average ratio of visible source references to inspected claims across the four answers, expressed as a percentage. Templated by Quorum; no model generates this.",
    "Uncertainty":
      "A templated statement about how much of the run's evidence is uncertain, based on failed answers and low coverage. Templated by Quorum; no model generates this.",
    "Recommendation":
      "A decision-support framing from Quorum. Not medical, legal, financial, safety, or regulated professional advice. Templated by Quorum; no model generates this.",
  };

  function buildInfoIcon(text) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "info-icon";
    button.setAttribute("data-info-icon", "");
    button.setAttribute("data-info-text", text);
    button.setAttribute("aria-label", "More information about this section");
    button.innerHTML = "&#9432;";
    return button;
  }

  function renderDebateAndSynthesis(result) {
    const debate = result?.result?.debate_outputs || [];
    if (debate.length) {
      const roundCards = debate.map((round) => {
        const card = document.createElement("article");
        card.className = "round-card";
        // ``data-round`` picks the colour of the left accent bar
        // (the CSS defines round 1 = blue, round 2 = accent orange,
        // round 3 = green, round 4 = purple). Falls back to the
        // accent orange for any unexpected round number.
        card.dataset.round = String(Math.min(Math.max(round.round_number || 1, 1), 4));
        const header = document.createElement("div");
        header.className = "round-card-header";
        const pill = document.createElement("span");
        pill.className = "round-pill";
        pill.textContent = `Round ${round.round_number}`;
        const focus = document.createElement("span");
        focus.className = "round-focus";
        focus.textContent = `Focus: ${(round.focus_areas || []).join(", ") || "general critique"}`;
        header.append(pill, focus);
        const body = document.createElement("div");
        body.className = "round-card-body";
        body.appendChild(
          renderAnswerSection(round.critique_text, {
            label: "Copy critique",
          }),
        );
        card.append(header, body);
        return card;
      });
      debateOutput.replaceChildren(...roundCards);
    } else {
      const empty = document.createElement("div");
      empty.className = "muted";
      // Distinguish between "not run yet" and "run failed"
      if (result?.status && ['failed', 'timed_out', 'cancelled'].includes(result.status)) {
        empty.textContent = "Debate could not run — see error details above.";
        empty.className = "error-placeholder";
      } else {
        empty.textContent = "Debate rounds will appear here after models respond.";
      }
      debateOutput.replaceChildren(empty);
    }
    const synthesis = result?.result?.final_synthesis;
    if (synthesis) {
      const stack = document.createElement("div");
      stack.className = "stack";
      for (const [labelText, valueText] of [
        ["Consensus", synthesis.consensus],
        ["Disagreement", synthesis.disagreement],
        ["Source support", synthesis.source_support],
        ["Uncertainty", synthesis.uncertainty],
        ["Recommendation", synthesis.recommendation],
      ]) {
        if (!valueText) continue;
        const block = document.createElement("section");
        block.className = "synthesis-block";
        // ``data-section`` is the hook the CSS uses to colour the
        // section (Consensus = blue, Disagreement = red, etc.).
        block.dataset.section = labelText;
        const label = document.createElement("h4");
        const labelTextOnly = document.createElement("span");
        labelTextOnly.textContent = labelText;
        label.append(labelTextOnly, buildInfoIcon(SYNTHESIS_TOOLTIPS[labelText] || ""));
        const body = document.createElement("div");
        body.className = "synthesis-block-body";
        body.appendChild(
          renderAnswerSection(valueText, {
            label: `Copy ${labelText.toLowerCase()}`,
          }),
        );
        block.append(label, body);
        stack.appendChild(block);
      }
      if (synthesis.high_stakes_notice) {
        const notice = document.createElement("div");
        notice.className = "callout callout-high-stakes";
        // C15: build the callout with createElement + textContent.
        // The previous innerHTML form escaped the body but mixed
        // literal markup with the escaped user data. The DOM
        // form is safer and easier to read.
        const icon = document.createElement("div");
        icon.className = "callout-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "!";
        const body = document.createElement("div");
        body.className = "callout-body";
        body.textContent = synthesis.high_stakes_notice;
        notice.append(icon, body);
        stack.appendChild(notice);
      }
      synthesisOutput.replaceChildren(stack);
      // Wire up the newly inserted info icons (the static template
      // ones are wired up once in ``boot``; dynamic ones appear here).
      initInfoIcons();
    } else {
      const empty = document.createElement("div");
      empty.className = "muted";
      // Distinguish between "not run yet" and "run failed"
      if (result?.status && ['failed', 'timed_out', 'cancelled'].includes(result.status)) {
        empty.textContent = "Synthesis could not be generated — see error details above.";
        empty.className = "error-placeholder";
      } else {
        empty.textContent = "Final synthesis will appear here after debate.";
      }
      synthesisOutput.replaceChildren(empty);
    }
  }

  function renderNotices(result) {
    const notices = [];
    if (state.currentEstimate) {
      const ce = state.currentEstimate.cost_estimate;
      const { primary: usdPrimary, secondary: usdSecondary } = formatCostWithLocal(
        ce.estimated_cost_usd,
      );
      notices.push({
        tone: "info",
        text: `Planning estimate: ${usdPrimary} (${formatCostBand(ce.threshold_action)}).`,
      });
      if (usdSecondary) {
        notices.push({ tone: "muted", text: usdSecondary });
      } else {
        notices.push({
          tone: "muted",
          text: "This estimate is a local planning heuristic based on query length and selected model slots, not a provider quote or invoice.",
        });
      }
    }
    if (result?.partial_failure_notice) {
      notices.push({ tone: "warn", text: result.partial_failure_notice });
    }
    for (const notice of result?.provider_failure_notices || []) {
      notices.push({ tone: "warn", text: notice });
    }
    const failedSteps = result?.failed_steps || [];
    const missingSteps = result?.missing_steps || [];
    if (!notices.length && !failedSteps.length && !missingSteps.length) {
      noticeList.replaceChildren(
        Object.assign(document.createElement("div"), {
          className: "muted",
          textContent: "No cost estimate or run yet — enter a question above.",
        }),
      );
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const { tone, text } of notices) {
      const item = document.createElement("div");
      item.className = `notice notice-${tone}`;
      item.textContent = text;
      fragment.appendChild(item);
    }
    // L5b: render the per-stage diagnostic block when any stage
    // failed or was skipped. The block is collapsed by default so
    // a healthy run doesn't draw attention to an empty list.
    if (failedSteps.length || missingSteps.length) {
      fragment.appendChild(renderStageDiagnostics(failedSteps, missingSteps));
    }
    noticeList.replaceChildren(fragment);
  }

  // L5b: a small <details> block listing the stages that failed or
  // were skipped. The summary shows the headline counts; the body
  // lists the actual stage names. Empty stages are omitted so a
  // run with only missing steps (no failed) doesn't render an
  // empty "failed" list.
  function renderStageDiagnostics(failedSteps, missingSteps) {
    const details = document.createElement("details");
    details.className = "stage-diagnostics";
    const summary = document.createElement("summary");
    const failedLabel = `${failedSteps.length} stage${failedSteps.length === 1 ? "" : "s"} failed`;
    const missingLabel = `${missingSteps.length} missing`;
    summary.textContent = `${failedLabel} · ${missingLabel}`;
    details.appendChild(summary);
    const list = document.createElement("ul");
    if (failedSteps.length) {
      for (const stage of failedSteps) {
        const li = document.createElement("li");
        const tag = document.createElement("strong");
        tag.textContent = "failed";
        li.append(tag, " — ", stage);
        list.appendChild(li);
      }
    }
    if (missingSteps.length) {
      for (const stage of missingSteps) {
        const li = document.createElement("li");
        const tag = document.createElement("strong");
        tag.textContent = "missing";
        li.append(tag, " — ", stage);
        list.appendChild(li);
      }
    }
    details.appendChild(list);
    return details;
  }

  // ---------------------------------------------------------------------------
  // Misc helpers
  // ---------------------------------------------------------------------------

  // Light formatter for model answers, debate rounds, and synthesis
  // sections (L5a). We don't do real markdown (no build step, no
  // dependency budget) but we do split on blank lines into paragraphs
  // and convert single newlines into ``<br>`` so LLM output that
  // already has reasonable structure stays legible on first render —
  // long blocks of double-spaced prose collapse to a wall of text,
  // which is hard to scan.
  //
  // Returns an HTML string. The caller is responsible for inserting
  // it with ``innerHTML`` — escaping is handled internally via the
  // existing ``escapeHtml`` helper so a hostile answer cannot inject
  // script tags through the response payload.
  //
  // The function is intentionally a no-op on plain prose and on the
  // "Awaiting provider output." / "Provider did not return text."
  // placeholders, so a stuck poll still looks like a stuck poll.
  function formatAnswerText(rawText) {
    const placeholder =
      rawText == null ||
      rawText === "Awaiting provider output." ||
      rawText === "Provider did not return text.";
    const text = placeholder ? "" : String(rawText);
    if (!text) return "";
    // Normalise line endings and strip trailing whitespace per line.
    const lines = text
      .replace(/\r\n?/g, "\n")
      .split("\n")
      .map((line) => line.replace(/[ \t]+$/g, ""));
    // Collapse 3+ blank lines down to a single blank line.
    const collapsed = [];
    let blankRun = 0;
    for (const line of lines) {
      if (line.trim() === "") {
        blankRun += 1;
        if (blankRun <= 1) collapsed.push("");
      } else {
        blankRun = 0;
        collapsed.push(line);
      }
    }
    while (collapsed.length && collapsed[0].trim() === "") collapsed.shift();
    while (collapsed.length && collapsed[collapsed.length - 1].trim() === "") collapsed.pop();
    if (!collapsed.length) return "";
    // Group consecutive non-blank lines into blocks; classify each
    // block as a list, heading, fenced code block, or paragraph. The
    // inline renderer (mdInline) handles bold, italic, inline code,
    // and links within those block contents.
    const out = [];
    let buffer = [];
    const flushParagraph = () => {
      if (!buffer.length) return;
      const inner = buffer
        .map((line) => mdInline(escapeHtml(line)))
        .join("<br>");
      out.push(`<p>${inner}</p>`);
      buffer = [];
    };
    const flushList = () => {
      if (!buffer.length) return;
      const items = buffer.map((line) => {
        // Strip leading bullet marker ( "- ", "* ", or "1. " ).
        const stripped = line.replace(/^(\s*)([-*]|\d+\.)\s+/, "$1");
        return `<li>${mdInline(escapeHtml(stripped))}</li>`;
      });
      const ordered = buffer[0].match(/^\s*\d+\.\s+/) != null;
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.join("")}</${tag}>`);
      buffer = [];
    };
    const listMarker = (line) => /^\s*([-*]|\d+\.)\s+/.test(line);
    for (const line of collapsed) {
      if (line.trim() === "") {
        flushParagraph();
        flushList();
        continue;
      }
      if (listMarker(line)) {
        flushParagraph();
        buffer.push(line);
        continue;
      }
      flushList();
      // Headings: "# ", "## ", "### ".
      const heading = line.match(/^(#{1,3})\s+(.*)$/);
      if (heading) {
        const level = heading[1].length;
        out.push(`<h${level + 3}>${mdInline(escapeHtml(heading[2]))}</h${level + 3}>`);
        continue;
      }
      buffer.push(line);
    }
    flushParagraph();
    flushList();
    return out.join("");
  }

  // Inline markdown renderer. Escaped text is the input (so we
  // never reintroduce unescaped HTML). Recognises: **bold**, *italic*,
  // `code`, [text](url). Designed for the markdown flavour LLMs
  // actually emit; not CommonMark-complete.
  function mdInline(escaped) {
    let s = escaped;
    // Inline code first — everything inside backticks is verbatim and
    // must not be touched by the bold/italic/link rules below.
    s = s.replace(/`([^`]+)`/g, (_m, code) => `<code>${code}</code>`);
    // Bold then italic. Order matters: ** must be tried before *, or
    // the ** would each be consumed as empty italics.
    s = s.replace(/\*\*([^*]+)\*\*/g, (_m, t) => `<strong>${t}</strong>`);
    s = s.replace(/(^|[^*])\*([^*]+)\*/g, (_m, lead, t) => `${lead}<em>${t}</em>`);
    // [text](url). URL is escaped on input; we only need to add the
    // rel="noopener" for safety. The text may itself contain inline
    // markup already rendered above (rare), so we just emit the
    // anchor as-is.
    s = s.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      (_m, text, url) => {
        // URL scheme allow-list: only http(s) and mailto (and relative
        // URLs, i.e. those starting with no scheme) become anchors.
        // Everything else — javascript:, data:, vbscript:, file:,
        // etc. — is rendered as plain text with no href, so a
        // crafted LLM response cannot smuggle a script execution
        // vector into the page via a markdown link.
        const trimmed = url.trim();
        const safe =
          /^https?:/i.test(trimmed) ||
          /^mailto:/i.test(trimmed) ||
          !/^[a-z][a-z0-9+.-]*:/i.test(trimmed);
        if (!safe) {
          return `${text} (${url})`;
        }
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`;
      },
    );
    return s;
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (ch) => {
      switch (ch) {
        case "&": return "&amp;";
        case "<": return "&lt;";
        case ">": return "&gt;";
        case '"': return "&quot;";
        case "'": return "&#39;";
        default: return ch;
      }
    });
  }

  // L5a: render an answer body + Copy button. The body is a div
  // containing the ``formatAnswerText`` HTML; the Copy button writes
  // the raw text to the clipboard. Returns a DocumentFragment the
  // caller can append to any container. The button is disabled when
  // the source text is empty / placeholder.
  function renderAnswerSection(rawText, { label = "Copy section" } = {}) {
    const fragment = document.createDocumentFragment();
    const wrapper = document.createElement("div");
    wrapper.className = "answer-section";
    const body = document.createElement("div");
    body.className = "answer-section-body q-prose";
    const html = formatAnswerText(rawText);
    if (html) {
      body.innerHTML = html;
    } else {
      body.classList.add("muted");
      body.textContent = "—";
    }
    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "answer-section-copy";
    copyButton.textContent = label;
    copyButton.setAttribute("aria-label", label);
    if (!html || !rawText) {
      copyButton.disabled = true;
    }
    copyButton.addEventListener("click", async () => {
      const value = rawText || "";
      if (!value) return;
      try {
        await navigator.clipboard.writeText(value);
        copyButton.dataset.copied = "true";
        copyButton.textContent = "Copied";
        window.setTimeout(() => {
          delete copyButton.dataset.copied;
          copyButton.textContent = label;
        }, 1500);
      } catch (_) {
        copyButton.textContent = "Copy failed";
        window.setTimeout(() => {
          copyButton.textContent = label;
        }, 1500);
      }
    });
    wrapper.append(body, copyButton);
    fragment.appendChild(wrapper);
    return fragment;
  }

  function setButtonLoading(button, isLoading) {
    if (!button) return;
    if (isLoading) {
      button.dataset.loading = "true";
      button.disabled = true;
    } else {
      delete button.dataset.loading;
      button.disabled = false;
    }
  }

  function setRunning(isRunning) {
    state.isRunning = isRunning;
    estimateButton.disabled = isRunning;
    if (runNowButton) runNowButton.disabled = isRunning;
    // The cancel pill is hidden in the idle layout and revealed only
    // while a run is actually in flight. Toggling ``hidden`` on the
    // container (not the button) keeps the button's ``disabled`` state
    // honest and avoids a stranded "active" button after cancel.
    if (cancelContainer) cancelContainer.hidden = !isRunning;
    if (cancelButton) cancelButton.disabled = !isRunning;
    if (proceedButton) {
      // While a run is in flight, the user cannot start a new one or
      // re-estimate. Proceed is also re-disabled to prevent double-
      // submission.
      proceedButton.disabled = isRunning || !state.currentEstimate;
    }
    if (isRunning && !state.hasScrolledToRunControls) {
      // Scroll once on the transition into running. The poll loop
      // would otherwise scroll the page aggressively every 750ms.
      state.hasScrolledToRunControls = true;
      if (cancelButton) {
        cancelButton.scrollIntoView({ behavior: "smooth", block: "center" });
        cancelButton.focus({ preventScroll: true });
      }
    } else if (!isRunning && state.hasScrolledToRunControls) {
      // Reset for the next run so the scroll-once fires again.
      state.hasScrolledToRunControls = false;
    }
  }

  // PR-0 / Bug 8: the "Current time" card is a state machine. It
  // starts at "Not started", freezes at the run start time, and
  // is replaced with the completion time when the run reaches a
  // terminal state. The polling tick in the middle of a run does
  // not touch the displayed time. Only the explicit
  // ``setRunStartTime`` / ``finalizeRunTime`` / ``resetRunTime``
  // wrappers drive the card. ``updateRunTimeCard`` is the single
  // entry point that mutates the visible text.
  function updateRunTimeCard(transition, rawValue) {
    if (transition === "reset") {
      state.runStartTime = null;
      state.runTimeFinalized = false;
      timeMeta.textContent = "Not started";
      return;
    }
    if (!rawValue) return;
    if (transition === "start") {
      state.runStartTime = rawValue;
      state.runTimeFinalized = false;
    } else if (transition === "finalize") {
      state.runTimeFinalized = true;
    } else {
      return;
    }
    const resolvedDate = new Date(rawValue);
    let formatted;
    try {
      // ``Intl.DateTimeFormat`` with ``timeZoneName: "short"`` throws
      // on some runtimes (notably minimal ICU builds). We don't need
      // the timezone here — the user's local timezone is implied by
      // the label "Current time" — so we deliberately keep the option
      // list minimal and fall back to ``toLocaleString`` if the host
      // rejects even ``dateStyle``.
      formatted = new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(resolvedDate);
    } catch (_) {
      formatted = resolvedDate.toLocaleString();
    }
    timeMeta.textContent = formatted || "Not started";
  }

  function setRunStartTime(rawValue) {
    updateRunTimeCard("start", rawValue);
  }

  function finalizeRunTime(rawValue) {
    updateRunTimeCard("finalize", rawValue);
  }

  function resetRunTime() {
    updateRunTimeCard("reset", null);
  }

  function updateRunMeta(result) {
    el("correlation-meta").textContent = result?.correlation_id || "Not started";
    const status = result?.status || "idle";
    if (status !== state.lastStatus) {
      state.lastStatus = status;
      const label = STATUS_LABELS[status] || status;
      setStatusPill(status, label);
    }
    // PR-0 / Bug 8: the "Current time" card has its own state
    // machine (frozen-at-start, finalized-on-terminal) and is
    // updated by the ``setRunStartTime`` / ``finalizeRunTime``
    // wrappers from ``runNow`` / ``proceedWithRun`` / ``pollRun``.
    // A status update in the middle of a run is not a time
    // change, so we do not touch the time card from here.
    // Surface the citation coverage denominator so users can audit the
    // ratio itself. ``material_claim_count`` is the sum of the four
    // models' material-claim counts. We avoid displaying this when the
    // run has no initial answers yet (cost-blocked, pending, etc.).
    const claimMeta = el("claim-meta");
    if (claimMeta) {
      const count = Number(result?.material_claim_count ?? 0);
      const finished = status === "completed" || status === "partial" || status === "failed" || status === "timed_out";
      if (finished && count > 0) {
        claimMeta.textContent = `${count.toLocaleString()} material claim${count === 1 ? "" : "s"} inspected`;
      } else {
        claimMeta.textContent = "";
      }
    }
  }

  function updateQueryValidation() {
    const length = queryTextarea.value.length;
    charCount.textContent = `${length.toLocaleString()} chars`;
    // Empty (0) is invalid (required field). 1–11 chars is too short.
    const isInvalid = length < 12;
    queryTextarea.setAttribute("aria-invalid", isInvalid ? "true" : "false");
    if (length === 0) {
      validationHint.textContent = "Question is required.";
      charCount.dataset.warning = "true";
      // Phase 4: Show inline field error only after submission attempt
      if (state.submissionAttempted && queryError) {
        queryError.textContent = "Please enter a question before running.";
        queryError.hidden = false;
      } else if (queryError) {
        // Clear error when user is typing but hasn't submitted yet
        queryError.textContent = "";
        queryError.hidden = true;
      }
    } else if (length < 12) {
      validationHint.textContent = "A few more characters will help the models answer well.";
      charCount.dataset.warning = "true";
      // Hide inline error for short-but-not-empty queries
      if (queryError) {
        queryError.textContent = "";
        queryError.hidden = true;
      }
    } else if (length > 8000) {
      validationHint.textContent = "Long queries are blocked by the cost guardrail. Try to shorten this.";
      charCount.dataset.warning = "true";
      if (queryError) {
        queryError.textContent = "";
        queryError.hidden = true;
      }
    } else if (length > 5000) {
      validationHint.textContent = "This length is in the upper-cost band; confirmation may be required.";
      charCount.dataset.warning = "true";
      if (queryError) {
        queryError.textContent = "";
        queryError.hidden = true;
      }
    } else {
      validationHint.textContent = "";
      charCount.dataset.warning = "false";
      if (queryError) {
        queryError.textContent = "";
        queryError.hidden = true;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Run lifecycle
  // ---------------------------------------------------------------------------

  async function initSession() {
    try {
      const response = await fetch("/v1/session", { credentials: "same-origin" });
      if (!response.ok) {
        throw new ApiError({
          status: response.status,
          code: "AUTH_REQUIRED",
          message: STATUS_COPY[response.status] || "Could not start a session.",
        });
      }
      const session = await response.json();
      state.csrfToken = session.csrf_token;
      el("session-meta").textContent = "Managed by secure cookie";
      setConnectionPill("connected", "Connected");
    } catch (error) {
      setConnectionPill("error", "Disconnected");
      throw error;
    }
  }

  async function refreshDefaults() {
    const response = await api("/v1/models/defaults", { method: "GET" });
    // Re-seed the drift cache from the live payload so the drift
    // banner reflects the current catalog, not the boot-time
    // snapshot. The banner is rendered by the next ``applyReadinessState``
    // call (or by an explicit ``renderDriftBanner`` if the readiness
    // probe is not due yet).
    if (Array.isArray(response.stale_model_ids)) {
      state.lastStaleModelIds = response.stale_model_ids.slice();
      renderDriftBanner();
    }
    renderModelInputs(response.model_slots.map((slot) => slot.model_id));
    renderModelPanels([], null);
  }

  // Reset the cost confirmation UI back to its initial hidden state.
  // Called when the user dismisses the estimate or starts a fresh
  // estimate.
  function hideCostConfirmation() {
    if (costConfirmation) costConfirmation.hidden = true;
    if (costConfirmationMessage) costConfirmationMessage.textContent = "";
    if (costConfirmationSecondary) {
      costConfirmationSecondary.textContent = "";
      costConfirmationSecondary.hidden = true;
    }
    if (proceedButton) {
      proceedButton.disabled = true;
      delete proceedButton.dataset.loading;
    }
  }

  async function estimateRun() {
    clearError();
    hideCostConfirmation();
    setButtonLoading(estimateButton, true);
    try {
      const queryText = queryTextarea.value.trim();
      if (!queryText) {
        throw new ApiError({
          status: 422,
          code: "QUERY_REQUIRED",
          message: "Please enter a question before running an estimate.",
        });
      }
      const estimate = await api("/v1/query-runs/estimate", {
        method: "POST",
        body: JSON.stringify({
          query_text: queryText,
          model_slots: getModelIds(),
        }),
      });
      state.currentEstimate = estimate;
      const { primary: usdPrimary, secondary: usdSecondary } = formatCostWithLocal(
        estimate.cost_estimate.estimated_cost_usd,
      );
      const costLine = `Estimated cost: ${usdPrimary}.`;
      // PR-0 / Bug 2: the success-path DOM operations used to live
      // inline. If any of them threw (e.g. an unexpectedly-shaped
      // response made formatCostWithLocal fail), the throw would
      // jump straight to the finally, skipping the cost callout
      // and leaving the button briefly in the loading state before
      // the finally reset it. Wrap the callout rendering in its
      // own try/catch so a single broken callout render surfaces
      // an error message in the callout area instead of leaving
      // the screen blank. The button is always reset by the outer
      // finally regardless.
      try {
        if (usdSecondary) renderCostSecondary(estimate.cost_estimate.estimated_cost_usd);
        if (estimate.cost_estimate.threshold_action === "require_confirmation") {
          costConfirmationMessage.textContent =
            `${costLine} This is in the upper band. Confirm to proceed.`;
          costConfirmation.hidden = false;
          if (proceedButton) {
            proceedButton.disabled = false;
            proceedButton.dataset.estimateBand = "require_confirmation";
          }
        } else if (estimate.cost_estimate.threshold_action === "block") {
          costConfirmationMessage.textContent =
            `${costLine} This exceeds the hard limit (USD 0.25). The run is blocked.`;
          costConfirmation.hidden = false;
          if (proceedButton) {
            proceedButton.disabled = true;
            proceedButton.dataset.estimateBand = "block";
          }
        } else {
          costConfirmationMessage.textContent =
            `${costLine} This is in the normal band. Proceed to start.`;
          costConfirmation.hidden = false;
          if (proceedButton) {
            proceedButton.disabled = false;
            proceedButton.dataset.estimateBand = "allow";
          }
        }
        renderNotices(null);
        toast({
          message: `Cost estimate ready: ${usdPrimary}.`,
          tone: "success",
        });
      } catch (renderError) {
        // The estimate itself succeeded — the response is valid —
        // but rendering the callout blew up. Show the error in the
        // callout so the user can see what happened and reset the
        // proceed button so the next estimate isn't blocked.
        if (costConfirmation) {
          costConfirmationMessage.textContent =
            `Got the estimate (${usdPrimary}) but could not render the cost review. ` +
            `${renderError && renderError.message ? renderError.message : "Unknown error."}`;
          costConfirmation.hidden = false;
        }
        if (proceedButton) {
          proceedButton.disabled = true;
        }
      }
      return estimate;
    } finally {
      setButtonLoading(estimateButton, false);
    }
  }

  function warningAcknowledgements(warnings) {
    return warnings.map((warning) => ({
      warning_type: warning.warning_type,
      version: warning.version,
    }));
  }

  // L5c: developer-only "magic" phrases that flip the pipeline into
  // a forced-failure / forced-fallback / forced-timeout path. These
  // are useful in tests but should never appear in a real query by
  // accident. We surface a warn toast on the first run attempt and
  // require a second click before the request fires so the user is
  // not silently routed onto a degraded path.
  //
  // The exact strings here mirror the constants in
  // ``product_app.providers`` and ``product_app.debate``. They are
  // case-insensitive matches against the user query text.
  const MAGIC_TRIGGER_PHRASES = [
    "force provider failure",
    "force fallback search",
    "force debate timeout",
  ];

  function magicPhrasesIn(queryText) {
    const lowered = (queryText || "").toLowerCase();
    const hits = [];
    for (const phrase of MAGIC_TRIGGER_PHRASES) {
      if (lowered.includes(phrase)) hits.push(phrase);
    }
    return hits;
  }

  // Returns ``true`` if the user has already confirmed a magic
  // phrase on this run, OR if there are no magic phrases in the
  // query. Sets a flag on the button so the second click is the
  // one that fires the request. The flag is cleared once the
  // run starts so the user gets the warning again on the next run.
  function checkMagicPhraseAck(queryText, button) {
    const phrases = magicPhrasesIn(queryText);
    if (!phrases.length) return true;
    if (button && button.dataset.magicAck === "true") {
      delete button.dataset.magicAck;
      return true;
    }
    if (button) {
      button.dataset.magicAck = "true";
    }
    const list = phrases.map((p) => `"${p}"`).join(", ");
    toast({
      message:
        `This query contains a phrase that may trigger a non-live run ` +
        `(${list}). Click again to proceed; the run will not go to real models.`,
      tone: "warn",
      timeout: 8000,
    });
    return false;
  }

  // The single primary composer action. Always estimates first so the
  // user sees the cost, then surfaces Proceed / Cancel inside the
  // cost confirmation callout. The previous two-button flow had a
  // hidden auto-estimates-then-starts shortcut; that shortcut is gone
  // — the user always sees the estimate before a run starts.
  async function startRun() {
    state.submissionAttempted = true;
    clearError();
    setButtonLoading(estimateButton, true);
    try {
      const queryText = queryTextarea.value.trim();
      if (!queryText) {
        throw new ApiError({
          status: 422,
          code: "QUERY_REQUIRED",
          message: "Please enter a question before starting a run.",
        });
      }
      await estimateRun();
    } catch (error) {
      handleError(error);
    } finally {
      setButtonLoading(estimateButton, false);
    }
  }

  // The fast-path primary action: skip the estimate and POST the run
  // directly. If the server reports the cost needs confirmation or
  // exceeds the hard limit, auto-fall-back to the cost callout so the
  // user sees the same review UI as the estimate-first path. The
  // hard guardrail (>$0.25) is server-enforced and cannot be bypassed
  // client-side — see costs.py:35-36.
  //
  // PR-0 / Bug 4 (Option A): when the server returns
  // ``COST_CONFIRMATION_REQUIRED`` from the run-create call, the
  // fast-path silently fell back to the estimate callout and the
  // user had to click "Proceed" themselves. The fast path should
  // still be a single click when possible, so we estimate, then
  // immediately re-fire the create-run with the fresh
  // ``confirmation_token`` if the user has not yet blocked the
  // run. The user sees a brief "Cost review" callout (less than a
  // second) and the run starts without a second click. We only do
  // this when the band is ``require_confirmation`` — the
  // ``block`` band surfaces the callout as a read-only refusal
  // and the user clicks Cancel.
  async function runNow() {
    state.submissionAttempted = true;
    clearError();
    setButtonLoading(runNowButton, true);
    try {
      const queryText = queryTextarea.value.trim();
      if (!queryText) {
        throw new ApiError({
          status: 422,
          code: "QUERY_REQUIRED",
          message: "Please enter a question before starting a run.",
        });
      }
      if (!checkMagicPhraseAck(queryText, runNowButton)) {
        return;
      }
      const warnings = await api("/v1/query-runs/warnings", {
        method: "POST",
        body: JSON.stringify({ query_text: queryText }),
      });
      let created;
      try {
        created = await api("/v1/query-runs", {
          method: "POST",
          body: JSON.stringify({
            query_text: queryText,
            model_slots: getModelIds(),
            safety_acknowledgements: warningAcknowledgements(warnings.warnings),
            // No cost_confirmation: server will compute the estimate
            // and either accept (allow band), require confirmation, or
            // block. The fallback below handles the latter two.
          }),
        });
      } catch (error) {
        if (error instanceof ApiError) {
          if (error.code === "COST_CONFIRMATION_REQUIRED") {
            // PR-0 / Bug 4: the user clicked "Run now" expecting a
            // single-click start. The server wants confirmation, so
            // run the estimate and then chain the proceed with the
            // fresh token. The callout flashes briefly before the
            // run actually starts. The user does not have to click
            // anything for an upper-band query.
            state.currentEstimate = null;
            toast({
              message: "Cost confirmation required — auto-confirming with the latest estimate.",
              tone: "warn",
            });
            const estimate = await estimateRun();
            if (estimate && state.currentEstimate) {
              const band =
                state.currentEstimate.cost_estimate.threshold_action;
              if (band === "require_confirmation") {
                // Re-fire the create-run with the confirmation token.
                // ``proceedWithRun`` reads ``state.currentEstimate`` and
                // posts the same payload the manual Proceed button
                // would have, so the behaviour is identical to a
                // two-click flow.
                await proceedWithRun();
              }
              // For the allow band the run already started; for the
              // block band the callout is now showing the refusal and
              // the user clicks Cancel.
            }
            return;
          }
          if (error.code === "COST_LIMIT_EXCEEDED") {
            // Same fallback: surface the cost callout (now showing the
            // hard-limit message) so the user can read the figure
            // before deciding. No auto-proceed — the run is blocked.
            state.currentEstimate = null;
            await estimateRun();
            return;
          }
        }
        throw error;
      }
      state.currentRunId = created.query_run_id;
      // Server accepted the run. Consume any prior estimate copy and
      // hide the callout.
      hideCostConfirmation();
      setRunning(true);
      updateRunMeta(created);
      renderProgress(created.progress);
      // PR-0 / Bug 8: capture the run start time once, here, on the
      // first run-create response. Subsequent poll ticks will not
      // overwrite the displayed time until the run reaches a
      // terminal state.
      setRunStartTime(created.result_generated_at_utc);
      toast({ message: "Run started. Tracking progress below.", tone: "info" });
      startPolling();
    } catch (error) {
      handleError(error);
    } finally {
      setButtonLoading(runNowButton, false);
    }
  }

  // User clicked "Proceed with this run" inside the cost callout.
  // Sends the create-run POST. For the REQUIRE_CONFIRMATION band the
  // server is sent the matching confirmation token; for ALLOW no
  // token is needed; for BLOCK the button is disabled and this path
  // cannot fire.
  async function proceedWithRun() {
    state.submissionAttempted = true;
    if (!state.currentEstimate) {
      // Defensive: button should be disabled until an estimate exists.
      return;
    }
    clearError();
    const queryText = queryTextarea.value.trim();
    if (!queryText) {
      throw new ApiError({
        status: 422,
        code: "QUERY_REQUIRED",
        message: "Please enter a question before starting a run.",
      });
    }
    if (!checkMagicPhraseAck(queryText, proceedButton)) {
      return;
    }
    setButtonLoading(proceedButton, true);
    try {
      const thresholdAction =
        state.currentEstimate.cost_estimate.threshold_action;
      const warnings = await api("/v1/query-runs/warnings", {
        method: "POST",
        body: JSON.stringify({ query_text: queryText }),
      });
      const costConfirmationPayload =
        thresholdAction === "require_confirmation"
          ? {
              estimated_cost_usd:
                state.currentEstimate.cost_estimate.estimated_cost_usd,
              confirmation_token:
                state.currentEstimate.cost_estimate.confirmation_token,
            }
          : null;
      const created = await api("/v1/query-runs", {
        method: "POST",
        body: JSON.stringify({
          query_text: queryText,
          model_slots: getModelIds(),
          safety_acknowledgements: warningAcknowledgements(warnings.warnings),
          cost_confirmation: costConfirmationPayload,
        }),
      });
      state.currentRunId = created.query_run_id;
      setRunning(true);
      updateRunMeta(created);
      renderProgress(created.progress);
      // PR-0 / Bug 8: capture the run start time once. See
      // ``runNow`` for the full rationale.
      setRunStartTime(created.result_generated_at_utc);
      // The estimate is now consumed; collapse the cost callout until
      // the next estimate.
      hideCostConfirmation();
      toast({ message: "Run started. Tracking progress below.", tone: "info" });
      startPolling();
    } catch (error) {
      // If the server reports the confirmation token expired (HTTP 402
      // with COST_CONFIRMATION_REQUIRED), auto-re-estimate so the user
      // sees fresh copy rather than a stale estimate.
      if (error instanceof ApiError && error.code === "COST_CONFIRMATION_REQUIRED") {
        state.currentEstimate = null;
        toast({
          message: "Cost re-estimated because the original confirmation expired.",
          tone: "warn",
        });
        await estimateRun();
        return;
      }
      handleError(error);
    } finally {
      setButtonLoading(proceedButton, false);
    }
  }

  // User clicked "Cancel" inside the cost callout. Clears the
  // estimate and re-enables the composer without starting a run.
  function cancelEstimate() {
    state.currentEstimate = null;
    hideCostConfirmation();
    renderNotices(null);
    toast({ message: "Estimate cleared.", tone: "info", timeout: 2500 });
  }

  async function pollRun() {
    if (!state.currentRunId) {
      // PR-0 / Bug 6: guard against stale null renders when a run is
      // already in flight. If the user has already clicked Run Now or
      // Proceed, the run id is in module-scope state and the active-
      // query check is redundant. A failed or empty response from
      // the active endpoint should never clobber the progress display
      // with "No active run." while a run is live.
      if (state.isRunning) {
        return;
      }
      const active = await api("/v1/query-runs/active", { method: "GET" });
      if (!active.query_run_id) {
        renderProgress(null);
        return;
      }
      state.currentRunId = active.query_run_id;
      setRunning(true);
      // PR-0 / Bug 8: when ``pollRun`` rehydrates the active run on
      // a fresh page load, capture its start time so the
      // "Current time" card is not stuck on "Not started" while the
      // run is still in flight. The poll response carries the
      // server's ``result_generated_at_utc`` which is acceptable as
      // an approximation of the run start (the run is in progress
      // and the user just navigated back to the tab).
      setRunStartTime(active.result_generated_at_utc);
    }
    const result = await api(`/v1/query-runs/${state.currentRunId}`, {
      method: "GET",
    });
    updateRunMeta(result);
    renderProgress(result.progress);
    renderModelPanels(result.result.model_answers, result);
    renderDebateAndSynthesis(result);
    renderNotices(result);
    // PR-0.1 / F1+F2: the "Current time" card is now driven
    // exclusively by ``setRunStartTime`` / ``finalizeRunTime`` /
    // ``resetRunTime``. The poll tick is intentionally a no-op for
    // the time card — Bug 8's contract (frozen-at-start,
    // replaced-on-terminal) must hold even when ``runStartTime``
    // is null on a poll response.
    if (
      ["completed", "partial", "failed", "timed_out", "cancelled"].includes(
        result.status,
      )
    ) {
      stopPolling();
      setRunning(false);
      // PR-0 / Bug 8: replace the displayed time with the
      // completion time on the first terminal transition. Polling
      // has already stopped, so this is the last time we touch
      // the card for this run.
      finalizeRunTime(result.result_generated_at_utc);
      if (result.status === "completed") {
        toast({ message: "Run completed. See the synthesis below.", tone: "success" });
      } else if (result.status === "partial") {
        toast({
          message: "Run finished with partial results. Check the notices section.",
          tone: "warn",
          timeout: 6500,
        });
      } else if (result.status === "failed") {
        // Show error banner for failed runs using server-provided info
        const failedSteps = result.failed_steps || [];
        const partialNotice = result.partial_failure_notice || '';
        const failedStepsText = failedSteps.length > 0
          ? `Failed at: ${failedSteps.join(', ').replace(/_/g, ' ')}`
          : '';

        // Build a user-friendly message based on failed steps
        let errorMessage = 'Run failed. ';
        if (failedSteps.includes('initial_answers')) {
          errorMessage += 'Models could not provide initial answers. ';
        } else if (failedSteps.includes('debate_round_1') || failedSteps.includes('debate_round_2')) {
          errorMessage += 'Debate could not complete. ';
        } else if (failedSteps.includes('synthesis')) {
          errorMessage += 'Final synthesis could not be generated. ';
        }

        if (partialNotice) {
          errorMessage += partialNotice;
        } else {
          errorMessage += 'Please try again or contact support if the problem persists.';
        }

        showError({
          code: 'RUN_FAILED',
          message: errorMessage,
          hint: failedStepsText
            ? `Technical details: ${failedStepsText}`
            : 'Check the notices section for more information.',
        });

        toast({ message: "Run failed. See error banner above.", tone: "error", timeout: 8000 });
      } else if (result.status === "timed_out") {
        showError({
          code: 'TIMEOUT',
          message: "Run timed out. The request took too long to process.",
          hint: "Try simplifying your question or wait a moment and retry."
        });
        toast({ message: "Run timed out. See error banner above.", tone: "warn", timeout: 6500 });
      } else if (result.status === "cancelled") {
        toast({ message: "Run cancelled.", tone: "info" });
      }
    }
  }

  function startPolling() {
    stopPolling();
    state.pollingTimer = window.setInterval(() => {
      pollRun().catch((error) => {
        // Polling errors are non-blocking; show a toast but keep the
        // last good result on screen.
        toast({ message: error.message, tone: "error", timeout: 6000 });
      });
    }, 750);
    pollRun().catch((error) => {
      toast({ message: error.message, tone: "error", timeout: 6000 });
    });
  }

  function stopPolling() {
    if (state.pollingTimer) {
      window.clearInterval(state.pollingTimer);
      state.pollingTimer = null;
    }
  }

  async function cancelRun() {
    if (!state.currentRunId) return;
    setButtonLoading(cancelButton, true);
    try {
      const result = await api(`/v1/query-runs/${state.currentRunId}`, {
        method: "DELETE",
      });
      updateRunMeta(result);
      renderProgress(result.progress);
      renderNotices(result);
      // PR-0 / Bug 8: cancel is a terminal transition; finalize
      // the run time once so the card shows the cancel time
      // rather than the start time.
      finalizeRunTime(result.result_generated_at_utc);
      stopPolling();
      setRunning(false);
      toast({ message: "Run cancelled.", tone: "info" });
    } catch (error) {
      handleError(error);
    } finally {
      setButtonLoading(cancelButton, false);
    }
  }

  function handleError(error) {
    // Re-enable the Proceed button so a transient failure does not
    // strand the user. The button is gated again on a fresh estimate
    // in the REQUIRE_CONFIRMATION band, but stays clickable in the
    // ALLOW band where the server only needs the latest estimate.
    if (proceedButton && !state.isRunning) {
      const band = proceedButton.dataset.estimateBand;
      proceedButton.disabled = band === "block";
    }
    if (error instanceof ApiError) {
      const detail = {
        code: error.code,
        message: error.message,
        fieldErrors: error.fieldErrors,
        hint: error.slotErrors ? formatSlotErrors(error.slotErrors) : undefined,
      };
      showError(detail);
      return;
    }
    showError({ code: null, message: error.message || "Unexpected error" });
  }

  function formatSlotErrors(errors) {
    return errors
      .map((e) => `Slot ${e.slot_number}: ${e.message || "invalid value"}`)
      .join(" · ");
  }

  // ---------------------------------------------------------------------------
  // Info icons (shared tooltip)
  // ---------------------------------------------------------------------------

  // Each section heading can carry a small "i" button that shows a
  // tooltip explaining what the section means. The tooltip body is
  // static text (set via ``data-info-text`` on the icon) — the
  // implementation never reads tooltip text from the server response,
  // so we use ``textContent`` only and never ``innerHTML``, avoiding
  // any XSS surface.
  function showInfoTooltip(icon) {
    if (!infoTooltip) return;
    const text = icon.getAttribute("data-info-text") || "";
    if (!text) return;
    // Update aria-describedby on the icon so the shared tooltip is
    // correctly associated with the currently focused/hovered icon
    // only. Reusing the same id across icons is the common bug; we
    // set it on the icon and reset on the previous one.
    document
      .querySelectorAll("[data-info-icon][data-info-active]")
      .forEach((el) => {
        delete el.dataset.infoActive;
        el.removeAttribute("aria-describedby");
      });
    icon.dataset.infoActive = "true";
    icon.setAttribute("aria-describedby", "info-tooltip");
    infoTooltip.textContent = text;
    infoTooltip.hidden = false;
    // Position the tooltip below (or above) the icon. Compute
    // coordinates after making it visible so we can measure its size.
    const iconRect = icon.getBoundingClientRect();
    infoTooltip.style.left = "0px";
    infoTooltip.style.top = "0px";
    const tooltipRect = infoTooltip.getBoundingClientRect();
    const margin = 8;
    let top = iconRect.bottom + margin;
    if (top + tooltipRect.height > window.innerHeight) {
      top = iconRect.top - tooltipRect.height - margin;
    }
    let left = iconRect.left;
    if (left + tooltipRect.width > window.innerWidth - margin) {
      left = window.innerWidth - tooltipRect.width - margin;
    }
    if (left < margin) left = margin;
    infoTooltip.style.left = `${window.scrollX + left}px`;
    infoTooltip.style.top = `${window.scrollY + top}px`;
  }

  function hideInfoTooltip(icon) {
    if (!infoTooltip) return;
    infoTooltip.hidden = true;
    infoTooltip.textContent = "";
    if (icon) {
      delete icon.dataset.infoActive;
      icon.removeAttribute("aria-describedby");
    }
  }

  // Wire up info icons. Idempotent: re-running it on a freshly
  // rendered synthesis panel attaches listeners to the new buttons
  // without duplicating listeners on the static ones (the static ones
  // are skipped because they carry a "wired" sentinel).
  function initInfoIcons() {
    if (!infoTooltip) return;
    const icons = document.querySelectorAll("[data-info-icon]:not([data-info-wired])");
    icons.forEach((icon) => {
      icon.dataset.infoWired = "true";
      icon.addEventListener("mouseenter", () => showInfoTooltip(icon));
      icon.addEventListener("focus", () => showInfoTooltip(icon));
      icon.addEventListener("mouseleave", () => hideInfoTooltip(icon));
      icon.addEventListener("blur", () => hideInfoTooltip(icon));
    });
  }

  // ---------------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------------

  function initThemeToggle() {
    const root = document.documentElement;
    const button = el("theme-toggle");
    // PR-0 / Bug 12: the glyph used to stay ``◐`` regardless of
    // theme. The button now swaps between ☀ (light, meaning
    // "click to go dark") and ☾ (dark, meaning "click to go
    // light") so the affordance matches the state. We seed the
    // glyph from the current ``data-theme`` so the first paint is
    // already consistent — important on browsers that re-hydrate
    // the page mid-session.
    const setGlyph = () => {
      const isDark = root.dataset.theme === "dark";
      button.textContent = isDark ? "☾" : "☀";
      button.setAttribute(
        "aria-label",
        isDark ? "Switch to light theme" : "Switch to dark theme",
      );
    };
    setGlyph();
    button.addEventListener("click", () => {
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
      setGlyph();
    });
  }

  function initModelSlotSelection() {
    modelInputs.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLSelectElement)) {
        return;
      }
      // PR-0.1 / F3: the model-slot selects are the only ``<select>``
      // children of ``modelInputs`` and they all have ids
      // ``model-1`` .. ``model-4`` (set by ``renderModelInputs``).
      // Filter on the id prefix rather than the ``data-model-slot``
      // attribute so a future rename of the dataset key cannot
      // silently break Bug 9's drift re-evaluation or Bug 10's
      // mutual-exclusion re-render.
      if (!target.id.startsWith("model-")) {
        return;
      }
      renderModelInputs(getModelIds());
      // PR-0 / Bug 9: re-evaluate the drift banner against the
      // new selection. If the user just moved off the drifted
      // default, the banner should disappear on this change
      // rather than waiting for the next ``/ready`` poll.
      renderDriftBanner();
    });
  }

  function initQueryValidation() {
    queryTextarea.addEventListener("input", updateQueryValidation);
    updateQueryValidation();
  }

  function initKeyboardShortcuts() {
    document.addEventListener("keydown", (event) => {
      const isCmdEnter = (event.metaKey || event.ctrlKey) && event.key === "Enter";
      if (isCmdEnter) {
        event.preventDefault();
        // Primary action is now "Run now" — skip the estimate, fall
        // back to the cost callout only if the server requires it.
        if (runNowButton && !runNowButton.disabled) {
          runNow();
        } else if (!estimateButton.disabled) {
          startRun();
        }
        return;
      }
      if (event.key === "Escape") {
        // If a tooltip is open, hide it first and stop here.
        if (infoTooltip && !infoTooltip.hidden) {
          const active = document.querySelector("[data-info-icon][data-info-active]");
          if (active instanceof HTMLElement) {
            event.preventDefault();
            hideInfoTooltip(active);
            active.focus();
            return;
          }
        }
        if (state.isRunning && !cancelButton.disabled) {
          event.preventDefault();
          cancelRun();
        }
        return;
      }
    });
  }

  function initBannerDismiss() {
    errorDismiss.addEventListener("click", clearError);
  }

  function initWorkflowKeyboard() {
    workflowSteps.forEach((step) => {
      step.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "Home" && event.key !== "End") {
          return;
        }
        const focused = document.activeElement;
        const steps = Array.from(workflowSteps);
        const currentIndex = steps.indexOf(focused);

        if (event.key === "ArrowRight") {
          event.preventDefault();
          const next = steps[(currentIndex + 1) % steps.length];
          next.focus();
        } else if (event.key === "ArrowLeft") {
          event.preventDefault();
          const prev = steps[(currentIndex - 1 + steps.length) % steps.length];
          prev.focus();
        } else if (event.key === "Home") {
          event.preventDefault();
          steps[0].focus();
        } else if (event.key === "End") {
          event.preventDefault();
          steps[steps.length - 1].focus();
        }
      });
    });
  }

  async function boot() {
    initThemeToggle();
    initModelSlotSelection();
    initQueryValidation();
    initKeyboardShortcuts();
    initBannerDismiss();
    initWorkflowKeyboard();
    initInfoIcons();
    // Workstream 3: seed the readiness + drift caches from the
    // page-load data islands and render the banners. This paints
    // the offline / drift disclosure before the first
    // session-initiated fetch completes, so a misconfigured
    // deployment does not flash a clean composer on first paint.
    seedReadinessFromPageLoad();
    applyReadinessState();
    estimateButton.addEventListener("click", () => {
      startRun();
    });
    if (runNowButton) {
      runNowButton.addEventListener("click", () => {
        runNow();
      });
    }
    if (copyCorrelationButton) {
      copyCorrelationButton.addEventListener("click", async () => {
        const target = el("correlation-meta");
        const value = (target?.textContent || "").trim();
        if (!value || value === "Not started") return;
        try {
          await navigator.clipboard.writeText(value);
          copyCorrelationButton.dataset.copied = "true";
          copyCorrelationButton.title = "Copied!";
          setTimeout(() => {
            delete copyCorrelationButton.dataset.copied;
            copyCorrelationButton.title = "Copy run ID — include it if you report an issue.";
          }, 1500);
        } catch (_) {
          copyCorrelationButton.title = "Copy failed — select and copy manually.";
        }
      });
    }
    if (proceedButton) {
      proceedButton.addEventListener("click", () => {
        proceedWithRun();
      });
    }
    if (cancelEstimateButton) {
      cancelEstimateButton.addEventListener("click", () => {
        cancelEstimate();
      });
    }
    cancelButton.addEventListener("click", () => {
      cancelRun();
    });
    setConnectionPill("connecting", "Connecting");
    try {
      await initSession();
      await refreshDefaults();
      renderProgress(null);
      renderDebateAndSynthesis(null);
      renderNotices(null);
      // PR-0 / Bug 8: on a fresh page load with no run in flight,
      // the "Current time" card should read "Not started" rather
      // than the wall-clock at the moment ``boot()`` ran.
      resetRunTime();
      // Pull the live readiness snapshot. ``/ready`` is
      // unauthenticated so this works even if the session bootstrap
      // were to fail. Best-effort: errors are logged to a toast
      // inside ``refreshReadiness`` and the page-load seed stays
      // visible.
      await refreshReadiness();
    } catch (error) {
      handleError(error);
      setConnectionPill("error", "Disconnected");
    }
  }

  boot();
})();
