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
  // Slice 1 (02 Composer): the composer collapses to a single ink CTA
  // ("See the estimate →", the ``estimate-run`` button), which routes the
  // run through the separate cost gate. The legacy fast-path "Run now"
  // button and its ``runNow`` handler are gone; Ctrl/Cmd+Enter falls
  // through to the estimate-first ``startRun`` flow.
  const highStakesGate = el("high-stakes-gate");
  const highStakesAckCheckbox = el("high-stakes-ack");
  const composerTotalEstimate = el("composer-total-estimate");
  const costConfirmationSecondary = el("cost-confirmation-secondary");
  const copyCorrelationButton = el("copy-correlation");
  // Slice 3 (04 Live run): the visible live-run heading. Focus lands here when
  // entering the live view (setRunning focuses the now-hidden #cancel-run).
  const liveRunHeading = el("live-run-heading");
  // Slice 4a (05 Result): focus lands on this h1 when entering the result view.
  const resultHeading = el("result-heading");
  const cancelButton = el("cancel-run");
  const cancelContainer = el("cancel-run-container");
  const connectionPill = el("connection-pill");
  const connectionPillText = el("connection-pill-text");
  const statusMeta = el("status-meta");
  const workflowSteps = qsa(".workflow-step");
  const demoModeBanner = el("demo-mode-banner");
  const demoModeTarget = demoModeBanner ? demoModeBanner.querySelector("[data-demo-mode-target]") : null;
  const infoTooltip = el("info-tooltip");
  // Screen 03 (cost gate) elements. ``renderCostGate`` fills these from
  // ``cost_estimate.breakdown``; the confirm button reuses ``proceedWithRun``.
  const gateHeading = el("cost-gate-heading");
  const gateQuestion = el("cost-gate-question");
  const gateTotal = el("cost-gate-total");
  const gateRange = el("cost-gate-range");
  const gateRangeWrap = el("cost-gate-range-wrap");
  const gateRail = el("cost-gate-rail");
  const gateRailMarker = el("cost-rail-marker");
  const gateByModel = el("cost-by-model");
  const gateByStage = el("cost-by-stage");
  const gateReason = el("cost-gate-reason");
  const gateBandLabel = el("cost-review-band-label");
  const gateCard = el("cost-review-card");
  const gateConfirmButton = el("gate-confirm");
  const gateBackButton = el("gate-back");
  const gateCapNote = el("cost-gate-cap-note");
  const gateHintConfirm = el("cost-gate-hint-confirm");
  const gateLive = el("cost-gate-live");
  const costGateContainer = document.querySelector('[data-view="cost-gate"]');

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
    // Slice 3 (04 Live run): live-run view state.
    // ``liveQueryText`` is the submitted question, captured at run start so the
    // running-query band can echo it (the poll payload carries no query_text).
    // ``lastLiveStatus`` short-circuits SR announcements on the live status
    // pill. The ``liveElapsed*`` triple drives a local ~1s ticker: on each poll
    // we store the server ``elapsed_time_ms`` (REAL, whole-run) plus a local
    // timestamp, and the ticker displays ``base + (now - stamp)``. The ticker
    // is CLEARED (never runs after the run ends) and frozen at the final
    // elapsed on any terminal transition.
    liveQueryText: null,
    lastLiveStatus: null,
    // Slice 4a (05 Result): the plain-text summary (question + verdict +
    // agreement line) built ONCE by ``renderResult`` at the terminal
    // transition; the Copy/Export buttons read it. ``lastResultRunId`` names
    // the exported file. Kept as textContent-safe strings (no HTML).
    lastResultSummary: null,
    lastResultRunId: null,
    // Slice 4a (05 Result): guards the terminal poll branch so a re-entrant
    // slow poll response cannot double-fire the completion toast + focus (C-A).
    // Reset to false on every run start (proceedWithRun, C-C).
    terminalHandled: false,
    liveElapsedBaseMs: 0,
    liveElapsedStamp: 0,
    liveElapsedTimer: null,
    // Slice 3 (04 Live run): per-block render signatures. ``renderLiveRun``
    // runs every 750ms; without a change guard each helper rebuilds identical
    // nodes (text-selection loss, animation restart, and — since #live-fallback
    // is role=status — an SR re-announcement every tick). Each helper stores a
    // lightweight signature of the exact data it renders and skips the
    // ``replaceChildren`` when unchanged. ``null`` forces a render (reset per
    // new run in ``proceedWithRun``). Mirrors the ``lastLiveStatus`` guard.
    liveSig: {
      stage: null,
      debate: null,
      models: null,
      fallback: null,
      notices: null,
    },
    // Slice 1 (02 Composer): the high-stakes gate. ``highStakesRequired``
    // is set from ``POST /v1/query-runs/warnings`` (a ``high_stakes``
    // warning in the response). While it is true and the user has not
    // checked the acknowledgement (``highStakesAck``), the primary CTA
    // stays disabled. The acknowledgement itself is still sent as
    // ``safety_acknowledgements[]`` by the existing run flow.
    highStakesRequired: false,
    highStakesAck: false,
    // Per-SLOT USD estimate keyed by slot position (array index),
    // populated from the estimate response's
    // ``cost_estimate.breakdown.by_model`` (the ``kind === "synthesis"``
    // writer row is excluded — it is not a slot). ``by_model`` is emitted
    // one row per slot in slot order (costs.py loops ``model_slots``), so
    // keying by position — NOT by model_id — keeps duplicate models in
    // different slots from collapsing/misattributing. Consumed by
    // ``renderModelInputs`` to label each slot card.
    perModelEstimates: [],
  };

  // ---------------------------------------------------------------------------
  // View switch (Slice 0 scaffold)
  // ---------------------------------------------------------------------------

  // Show exactly one ``[data-view]`` element and hide its siblings.
  // Names: "composer", "cost-gate", "live-run", "result". This is a
  // safe scaffold — later slices fill the placeholder views and wire
  // real transitions. No-ops gracefully if the view container or the
  // requested view is absent (e.g. a trimmed template), so it can be
  // called unconditionally on load.
  function setView(name) {
    const views = qsa("[data-view]");
    if (!views.length) return;
    const target = views.find((view) => view.dataset.view === name);
    if (!target) return;
    for (const view of views) {
      view.hidden = view !== target;
    }
    // Slice 3 (04 Live run): stamp the active view on the ``<main>`` shell so
    // CSS can go full-width and hide the persistent "Run controls" aside while
    // the live-run card is on screen (its status/cancel/run-id function is
    // subsumed by the live card). The aside element stays in the DOM — it is
    // only visually hidden via CSS — so the existing ``#cancel-run`` /
    // ``#status-meta`` render targets remain valid.
    const shell = document.getElementById("main-content");
    if (shell) shell.dataset.activeView = name;
  }

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
    // Bring the banner into view if it is below the fold (honour reduced motion).
    errorRegion.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "center",
    });
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
  // ``suffix:false`` drops the trailing " USD" for compact cells (the cost
  // gate's table/total/big number). Passing the option through here is the
  // single source of truth for money formatting — callers must never
  // string-strip the suffix themselves.
  function formatUsd(usdAmount, { suffix = true } = {}) {
    const tail = suffix ? " USD" : "";
    const num = Number(usdAmount);
    if (!Number.isFinite(num)) return `$0.00${tail}`;
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
    return `$${withCents}${tail}`;
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
    // Slice 1 (02 Composer): free model choice from the live catalog.
    // The approved design ("swap from live catalog", "Duplicates allowed
    // but visibly flagged") lets any slot pick ANY catalog model. We do
    // NOT scope a slot's dropdown to a vendor family, and we do NOT
    // remove a model just because another slot already selected it —
    // cross-slot duplicates are permitted and ``renderModelInputs``
    // surfaces a small inline "duplicate" flag when the same model is
    // chosen in >= 2 slots. ``selectedModelIds``/``currentIndex`` are
    // retained in the signature for call-site compatibility (and future
    // cross-slot awareness) even though no filtering is applied.
    void selectedModelIds;
    void currentIndex;
    const catalogHasDefault = modelCatalog.some(
      (option) => option.model_id === currentModelId,
    );
    const options = [];
    if (!catalogHasDefault) {
      // The curated default is no longer in the live catalog: keep it
      // reachable as a synthetic, pre-selected option so the slot does
      // not silently jump to a different model.
      const synthetic = document.createElement("option");
      synthetic.value = currentModelId;
      synthetic.textContent = `${currentModelId} (curated default — not in live catalog)`;
      synthetic.selected = true;
      options.push(synthetic);
    }
    for (const option of modelCatalog) {
      // Every catalog model is offered for every slot, regardless of
      // vendor. Duplicates across slots are permitted (and flagged).
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

  // Human-friendly display name for a model id. The catalog data island
  // carries the full label ("OpenAI: GPT-4o mini"); we strip the
  // "Vendor: " prefix to get the short display name ("GPT-4o mini") the
  // design uses on the slot cards. Falls back to the raw id.
  function displayNameForModel(modelId) {
    const entry = modelCatalog.find((option) => option.model_id === modelId);
    const label = entry ? entry.label : modelId;
    const short = label.includes(":")
      ? label.slice(label.indexOf(":") + 1).trim()
      : label;
    return short || modelId;
  }

  // Avatar initial: first letter of the display name, uppercased.
  function avatarInitialForModel(modelId) {
    const name = displayNameForModel(modelId).trim();
    return (name[0] || "?").toUpperCase();
  }

  // Per-slot estimate label. Returns a mono "~$0.034" once an estimate
  // exists for this slot position, otherwise an em-dash placeholder.
  // Keyed by slot index (not model_id) so two slots with the same model
  // each show their own positional estimate.
  function perModelEstimateText(slotIndex) {
    const usd = Array.isArray(state.perModelEstimates)
      ? state.perModelEstimates[slotIndex]
      : undefined;
    if (usd === undefined || usd === null) return "—";
    const num = Number(usd);
    if (!Number.isFinite(num)) return "—";
    return `~$${num.toFixed(3)}`;
  }

  // Slice 1 (02 Composer): the four model slots render as a 2x2 grid of
  // cards — avatar, display name, mono OpenRouter id, per-model mono
  // estimate, and a compact ▾ swap ``<select>`` (kept as a real select
  // so the ``aria-label`` + keyboard affordance survive). Duplicates are
  // allowed but flagged with a small amber "duplicate" pill.
  function renderModelInputs(modelIds) {
    const counts = {};
    for (const id of modelIds) counts[id] = (counts[id] || 0) + 1;

    const cards = modelIds.map((modelId, index) => {
      const card = document.createElement("div");
      card.className = "model-slot";
      card.dataset.slotIndex = String(index);

      const avatar = document.createElement("span");
      avatar.className = "model-slot-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = avatarInitialForModel(modelId);

      const info = document.createElement("div");
      info.className = "model-slot-info";
      const nameRow = document.createElement("div");
      nameRow.className = "model-slot-name";
      const nameText = document.createElement("span");
      nameText.textContent = displayNameForModel(modelId);
      nameRow.appendChild(nameText);
      if (counts[modelId] > 1) {
        const dup = document.createElement("span");
        dup.className = "model-slot-dup";
        dup.textContent = "duplicate";
        nameRow.appendChild(dup);
      }
      const idEl = document.createElement("div");
      idEl.className = "model-slot-id mono";
      idEl.textContent = modelId;
      info.append(nameRow, idEl);

      const estimate = document.createElement("span");
      estimate.className = "model-slot-estimate mono";
      estimate.textContent = perModelEstimateText(index);

      // The swap control: a compact ▾ affordance whose native <select>
      // is overlaid transparently so a click opens the vendor-scoped
      // model list. ``id`` (``model-N``) and ``data-model-slot`` are
      // preserved for the change handler and ``getModelIds``; the
      // ``aria-label`` names the control for assistive tech.
      const swap = document.createElement("span");
      swap.className = "model-slot-swap";
      const caret = document.createElement("span");
      caret.className = "model-slot-swap-caret";
      caret.setAttribute("aria-hidden", "true");
      caret.textContent = "▾";
      const select = document.createElement("select");
      select.id = `model-${index + 1}`;
      select.dataset.modelSlot = "";
      select.dataset.slotIndex = String(index);
      select.setAttribute("aria-label", `Model for slot ${index + 1}`);
      for (const option of renderModelOptions(modelId, index, modelIds)) {
        select.appendChild(option);
      }
      swap.append(caret, select);

      card.append(avatar, info, estimate, swap);
      return card;
    });
    modelInputs.replaceChildren(...cards);
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

  // ---------------------------------------------------------------------------
  // Slice 3 (04 Live run)
  // ---------------------------------------------------------------------------
  //
  // ``renderLiveRun`` paints the dedicated live-run view from a poll result
  // (or the create response, which has no ``.result`` projection — every
  // nested read is guarded). HONESTY: this view renders ONLY server-backed
  // fields. There is NO per-model debate stance, NO token streaming, NO
  // per-stage accrued cost, and NO live spend accrual — those are mock-only
  // in the pixel spec and have no backing field. Debate is shown at ROUND
  // granularity; cost is shown as the approved CAP with the real auto-stop
  // guarantee; model status is pending → done/failed (+ search-fallback tag).
  // GREEN RULE: nothing here is green (green is the verdict, Slice 4a). Running
  // is blue (--info); done is ink; failed is --danger; caution is --warning.

  const LIVE_PIPELINE_STAGES = [
    { key: "initial_answers", label: "Initial answers" },
    { key: "debate_round_1", label: "Debate round 1" },
    { key: "debate_round_2", label: "Debate round 2" },
    { key: "synthesis", label: "Synthesis" },
  ];

  const LIVE_TERMINAL = new Set([
    "completed",
    "partial",
    "failed",
    "timed_out",
    "cancelled",
  ]);

  const LIVE_ROUND_PLACEHOLDER_STATE = {
    running: "in progress",
    pending: "pending",
    failed: "failed",
    skipped: "skipped",
  };

  const LIVE_ROUND_PLACEHOLDER_BODY = {
    running:
      "Models are exchanging critiques for this round. The round-level critique appears here once it completes.",
    pending: "This round has not started yet.",
    failed: "This round did not complete.",
    skipped: "This round was skipped.",
  };

  // Map a run status to the header pill's visible text + colour state. The
  // state feeds ``data-state`` (CSS colours it): "running" = blue, "completed"
  // = ink (NOT green — green is the verdict only), "partial" = amber, "failed"/
  // "cancelled" = red. Text derived honestly from status/round position.
  function liveStatusPresentation(status) {
    switch (status) {
      case "accepted":
        return { text: "Starting…", state: "running" };
      case "initial_answers_running":
        return { text: "Running · initial answers", state: "running" };
      case "debate_round_1_running":
        return { text: "Running · debate round 1 of 2", state: "running" };
      case "debate_round_2_running":
        return { text: "Running · debate round 2 of 2", state: "running" };
      case "synthesis_running":
        return { text: "Running · synthesis", state: "running" };
      case "completed":
        return { text: "Completed", state: "completed" };
      case "partial":
        return { text: "Partial result", state: "partial" };
      case "failed":
        return { text: "Failed", state: "failed" };
      case "timed_out":
        return { text: "Timed out", state: "failed" };
      case "cancelled":
        return { text: "Cancelled", state: "cancelled" };
      default:
        return { text: STATUS_LABELS[status] || "Running", state: "running" };
    }
  }

  // Format whole-run elapsed. Sub-minute → "28.7s elapsed"; ≥60s → "1m 05s
  // elapsed". Driven by the REAL server ``elapsed_time_ms``.
  function formatElapsed(ms) {
    if (!Number.isFinite(ms)) return "—";
    const clamped = Math.max(0, Math.round(ms));
    // Branch on the ROUNDED ms, not the sub-minute float: [59.95s, 60s) rounds
    // to 60000ms and must read "1m 00s elapsed", never "60.0s elapsed".
    if (clamped >= 60000) {
      const whole = Math.floor(clamped / 1000);
      const minutes = Math.floor(whole / 60);
      const seconds = whole % 60;
      return `${minutes}m ${String(seconds).padStart(2, "0")}s elapsed`;
    }
    return `${(clamped / 1000).toFixed(1)}s elapsed`;
  }

  function tickLiveElapsed() {
    const elapsedEl = el("live-elapsed");
    if (!elapsedEl) return;
    const shown = state.liveElapsedBaseMs + (Date.now() - state.liveElapsedStamp);
    elapsedEl.textContent = formatElapsed(shown);
  }

  function startLiveElapsedTicker() {
    if (state.liveElapsedTimer) return;
    tickLiveElapsed();
    state.liveElapsedTimer = window.setInterval(tickLiveElapsed, 1000);
  }

  // Stop the ticker so it never runs after the run ends. Callers: terminal
  // renderLiveRun, stopPolling, setRunning(false).
  function stopLiveElapsedTicker() {
    if (state.liveElapsedTimer) {
      window.clearInterval(state.liveElapsedTimer);
      state.liveElapsedTimer = null;
    }
  }

  // Freeze the elapsed readout at the final value and stop ticking.
  function freezeLiveElapsed(finalMs) {
    stopLiveElapsedTicker();
    const elapsedEl = el("live-elapsed");
    if (elapsedEl && Number.isFinite(finalMs)) {
      elapsedEl.textContent = formatElapsed(finalMs);
    }
  }

  function liveStageDotGlyph(stageState, index) {
    if (stageState === "completed") return "✓";
    if (stageState === "failed") return "!";
    if (stageState === "running") return "●";
    if (stageState === "skipped") return "–";
    return String(index + 1); // pending
  }

  // Honest per-stage meta: initial answers shows the REAL "N/4 answers"
  // (answers received vs 4) while running/complete; every other stage shows
  // its state label + the server ``detail`` if any. NO fabricated time/cost.
  function liveStageMeta(def, stage, stageState, answersReceived) {
    const detail = stage && stage.detail ? String(stage.detail) : "";
    if (def.key === "initial_answers") {
      if (stageState === "running" || stageState === "completed") {
        const base = `${Math.min(answersReceived, 4)}/4 answers`;
        return detail ? `${base} · ${detail}` : base;
      }
      return detail ? `${stageState} · ${detail}` : stageState;
    }
    return detail ? `${stageState} · ${detail}` : stageState;
  }

  function renderLiveStageStrip(result, answersReceived) {
    const strip = el("live-stage-strip");
    if (!strip) return;
    const stages = (result.progress && result.progress.stages) || [];
    const byKey = new Map(stages.map((s) => [s.stage, s]));
    // Fix 3: skip the rebuild when nothing this strip renders has changed.
    const sig = JSON.stringify({
      answersReceived,
      stages: LIVE_PIPELINE_STAGES.map((def) => {
        const s = byKey.get(def.key);
        return s ? [s.state, s.detail || ""] : null;
      }),
    });
    if (sig === state.liveSig.stage) return;
    state.liveSig.stage = sig;
    const items = LIVE_PIPELINE_STAGES.map((def, index) => {
      const stage = byKey.get(def.key);
      const stageState = stage ? stage.state : "pending";
      const item = document.createElement("div");
      item.className = "live-stage";
      item.dataset.state = stageState;

      const head = document.createElement("div");
      head.className = "live-stage-head";
      const dot = document.createElement("span");
      dot.className = "live-stage-dot";
      dot.setAttribute("aria-hidden", "true");
      dot.textContent = liveStageDotGlyph(stageState, index);
      const label = document.createElement("span");
      label.className = "live-stage-label";
      label.textContent = def.label;
      head.append(dot, label);

      const bar = document.createElement("div");
      bar.className = "live-stage-bar";
      bar.dataset.state = stageState;
      const fill = document.createElement("span");
      fill.className = "live-stage-bar-fill";
      if (def.key === "initial_answers" && stageState === "running") {
        // REAL fraction: answers landed out of 4.
        fill.style.width = `${(Math.min(answersReceived, 4) / 4) * 100}%`;
      } else if (stageState === "running") {
        // No honest fraction exists for debate/synthesis — show an
        // indeterminate blue bar (static under reduced-motion).
        bar.dataset.indeterminate = "true";
      }
      bar.appendChild(fill);

      const meta = document.createElement("div");
      meta.className = "live-stage-meta mono";
      meta.textContent = liveStageMeta(def, stage, stageState, answersReceived);

      item.append(head, bar, meta);
      return item;
    });
    strip.replaceChildren(...items);
  }

  function renderLiveDebateCard(round) {
    const card = document.createElement("article");
    card.className = "live-round-card";
    card.dataset.state = "complete";
    const header = document.createElement("div");
    header.className = "live-round-header";
    const pill = document.createElement("span");
    pill.className = "live-round-pill";
    pill.textContent = `Round ${round.round_number}`;
    const focus = document.createElement("span");
    focus.className = "live-round-focus";
    focus.textContent = `Focus: ${
      (round.focus_areas || []).join(", ") || "general critique"
    }`;
    const stateEl = document.createElement("span");
    stateEl.className = "live-round-state";
    stateEl.textContent = "complete";
    header.append(pill, focus, stateEl);
    const body = document.createElement("p");
    body.className = "live-round-body";
    body.textContent = round.critique_text || "";
    card.append(header, body);
    return card;
  }

  function renderLiveDebatePlaceholder(roundNo, stageState) {
    const card = document.createElement("article");
    card.className = "live-round-card live-round-placeholder";
    card.dataset.state = stageState;
    const header = document.createElement("div");
    header.className = "live-round-header";
    const pill = document.createElement("span");
    pill.className = "live-round-pill";
    pill.textContent = `Round ${roundNo}`;
    const stateEl = document.createElement("span");
    stateEl.className = "live-round-state";
    stateEl.textContent = LIVE_ROUND_PLACEHOLDER_STATE[stageState] || "pending";
    header.append(pill, stateEl);
    const body = document.createElement("p");
    body.className = "live-round-body muted";
    body.textContent =
      LIVE_ROUND_PLACEHOLDER_BODY[stageState] || "This round has not started yet.";
    card.append(header, body);
    return card;
  }

  // Debate at ROUND granularity from ``debate_outputs`` (one critique_text per
  // round). Rounds not yet written show a pending/running placeholder driven by
  // the matching ``debate_round_N`` stage state. There is NO per-model debate
  // data to render.
  function renderLiveDebate(result) {
    const host = el("live-debate");
    if (!host) return;
    const debate = (result.result && result.result.debate_outputs) || [];
    const byRound = new Map(debate.map((r) => [r.round_number, r]));
    const stages = (result.progress && result.progress.stages) || [];
    const stageByKey = new Map(stages.map((s) => [s.stage, s]));
    // Fix 3: skip the rebuild when neither the round critiques nor the
    // debate-round stage states have changed since the last render.
    const sig = JSON.stringify({
      debate: debate.map((r) => [
        r.round_number,
        r.focus_areas || [],
        r.critique_text || "",
      ]),
      stages: [1, 2].map((n) => {
        const s = stageByKey.get(`debate_round_${n}`);
        return s ? s.state : "pending";
      }),
    });
    if (sig === state.liveSig.debate) return;
    state.liveSig.debate = sig;
    const cards = [1, 2].map((roundNo) => {
      const round = byRound.get(roundNo);
      if (round) return renderLiveDebateCard(round);
      const stage = stageByKey.get(`debate_round_${roundNo}`);
      return renderLiveDebatePlaceholder(roundNo, stage ? stage.state : "pending");
    });
    host.replaceChildren(...cards);
  }

  // Honest model status: a slot NOT yet in model_answers = "pending"; present
  // = "done" (completed, with real latency) or "failed"; a fallback answer is
  // tagged "search fallback". Nothing else (no "queued"/"responding"/"live").
  function renderLiveModelStatus(slots, answers) {
    const host = el("live-model-status");
    if (!host) return;
    const bySlot = new Map(answers.map((a) => [a.slot_number, a]));
    const slotList = slots.length
      ? slots
      : defaultModelIds.map((mid, i) => ({ slot_number: i + 1, model_id: mid }));
    // Fix 3: skip the rebuild when the slot set and every answer field this
    // row renders are unchanged.
    const sig = JSON.stringify({
      slots: slotList.map((s) => [s.slot_number, s.model_id]),
      answers: answers.map((a) => [
        a.slot_number,
        a.model_id,
        a.display_name,
        a.status,
        a.latency_ms,
        a.fallback_used,
        a.provider_path,
      ]),
    });
    if (sig === state.liveSig.models) return;
    state.liveSig.models = sig;
    const rows = slotList.map((slot) => {
      const answer = bySlot.get(slot.slot_number);
      const modelId = (answer && answer.model_id) || slot.model_id;
      const name = (answer && answer.display_name) || displayNameForModel(modelId);
      const row = document.createElement("div");
      row.className = "live-model-row";
      const avatar = document.createElement("span");
      avatar.className = "live-model-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = avatarInitialForModel(modelId);
      const nameEl = document.createElement("span");
      nameEl.className = "live-model-name";
      nameEl.textContent = name;
      const stateEl = document.createElement("span");
      stateEl.className = "live-model-state mono";

      let stateKey;
      let stateText;
      if (!answer) {
        stateKey = "pending";
        stateText = "pending";
      } else if (answer.status === "failed") {
        stateKey = "failed";
        stateText = "failed";
      } else {
        stateKey = "done";
        stateText =
          answer.latency_ms != null ? `done · ${answer.latency_ms} ms` : "done";
      }
      row.dataset.state = stateKey;
      stateEl.textContent = stateText;
      row.append(avatar, nameEl, stateEl);

      if (
        answer &&
        (answer.fallback_used || answer.provider_path === "fallback_search")
      ) {
        const tag = document.createElement("span");
        tag.className = "live-model-tag";
        tag.textContent = "search fallback";
        row.appendChild(tag);
      }
      return row;
    });
    host.replaceChildren(...rows);
  }

  // Amber search-fallback disclosure — hidden unless some answer used a
  // fallback. Prefers the server ``provider_notice`` text, else an honest
  // default (no provider brand names fabricated).
  function renderLiveFallback(answers) {
    const host = el("live-fallback");
    if (!host) return;
    const fallbackAnswer = answers.find(
      (a) => a.fallback_used || a.provider_path === "fallback_search",
    );
    // Fix 3: this block is role=status — skipping the rebuild when the
    // disclosure is unchanged avoids an SR re-announcement every poll tick.
    const sig = JSON.stringify(
      fallbackAnswer ? [true, fallbackAnswer.provider_notice || ""] : [false],
    );
    if (sig === state.liveSig.fallback) return;
    state.liveSig.fallback = sig;
    if (!fallbackAnswer) {
      host.hidden = true;
      host.replaceChildren();
      return;
    }
    const title = document.createElement("div");
    title.className = "live-fallback-title";
    const dot = document.createElement("span");
    dot.className = "live-fallback-dot";
    dot.setAttribute("aria-hidden", "true");
    const titleText = document.createElement("span");
    titleText.textContent = "Search fallback in use";
    title.append(dot, titleText);
    const body = document.createElement("div");
    body.className = "live-fallback-body";
    body.textContent =
      fallbackAnswer.provider_notice ||
      "Primary search didn't return enough source support for a model, so a fallback search is providing citations. Informational — the run continues, and it's disclosed on the receipt.";
    host.replaceChildren(title, body);
    host.hidden = false;
  }

  // Approved-cap panel. Shows the APPROVED CAP (estimated_cost_usd) labelled as
  // a cap, the REAL auto-stop guarantee, and the receipt reconciliation note.
  // NO spend bar, NO accruing "so far" figure — none exists.
  function renderLiveCap(result) {
    const host = el("live-cap");
    if (!host) return;
    const cap =
      result.cost_estimate && result.cost_estimate.estimated_cost_usd;
    const head = document.createElement("div");
    head.className = "live-cap-head";
    const label = document.createElement("span");
    label.className = "live-cap-label";
    label.textContent = "Approved cap";
    const value = document.createElement("span");
    value.className = "live-cap-value mono";
    value.textContent = cap != null ? formatUsd(cap, { suffix: false }) : "—";
    head.append(label, value);
    const guarantee = document.createElement("p");
    guarantee.className = "live-cap-note";
    guarantee.textContent =
      "The run stops itself if spend would pass the approved figure.";
    const reconcile = document.createElement("p");
    reconcile.className = "live-cap-note muted";
    reconcile.textContent = "Final cost reconciles on the receipt.";
    host.replaceChildren(head, guarantee, reconcile);
  }

  // Fix 1: surface failure notices inside the live-run card. While the live
  // view is active the "Run controls" aside (and its ``#notice-list``) is
  // hidden, so on a partial/failed run the REASON it degraded would otherwise
  // be invisible. This mirrors the HONESTY-SAFE fields ``renderNotices``
  // surfaces — never innerHTML, never provider keys/secrets — and shows the
  // block only when at least one field is non-empty.
  // Single source of truth for "does the live-run card have failure-disclosure
  // content to show". Used by ``renderLiveNotices`` (to show/hide the block)
  // AND by the terminal toast/hint copy, so the copy can never point at a
  // "run notices" block that is actually hidden.
  function liveNoticesHaveContent(result) {
    if (!result) return false;
    return Boolean(
      result.partial_failure_notice ||
        (result.provider_failure_notices &&
          result.provider_failure_notices.length) ||
        (result.failed_steps && result.failed_steps.length) ||
        (result.missing_steps && result.missing_steps.length),
    );
  }

  function renderLiveNotices(result) {
    const host = el("live-notices");
    const list = el("live-notices-list");
    if (!host || !list) return;
    const partialNotice = (result && result.partial_failure_notice) || "";
    const providerNotices = (result && result.provider_failure_notices) || [];
    const failedSteps = (result && result.failed_steps) || [];
    const missingSteps = (result && result.missing_steps) || [];
    // Fix 3: skip the rebuild when nothing this block renders has changed.
    const sig = JSON.stringify({
      partialNotice,
      providerNotices,
      failedSteps,
      missingSteps,
    });
    if (sig === state.liveSig.notices) return;
    state.liveSig.notices = sig;
    const hasContent = liveNoticesHaveContent(result);
    if (!hasContent) {
      host.hidden = true;
      list.replaceChildren();
      return;
    }
    const fragment = document.createDocumentFragment();
    if (partialNotice) {
      const item = document.createElement("div");
      item.className = "notice notice-warn";
      item.textContent = partialNotice;
      fragment.appendChild(item);
    }
    for (const notice of providerNotices) {
      const item = document.createElement("div");
      item.className = "notice notice-warn";
      item.textContent = notice;
      fragment.appendChild(item);
    }
    if (failedSteps.length || missingSteps.length) {
      fragment.appendChild(renderStageDiagnostics(failedSteps, missingSteps));
    }
    list.replaceChildren(fragment);
    host.hidden = false;
  }

  function renderLiveRun(result) {
    if (!result) return;
    const status = result.status || "accepted";
    const isTerminal = LIVE_TERMINAL.has(status);

    // Header status pill.
    const pill = el("live-status-pill");
    const statusText = el("live-status-text");
    const present = liveStatusPresentation(status);
    if (pill) pill.dataset.state = present.state;
    // Only reassign textContent on a real change so the polite live region
    // announces coarse status transitions, not every 750ms poll tick.
    if (statusText && present.text !== state.lastLiveStatus) {
      state.lastLiveStatus = present.text;
      statusText.textContent = present.text;
    }

    // Stop button — available while running, removed once terminal.
    const stopBtn = el("live-stop");
    if (stopBtn) stopBtn.hidden = isTerminal;

    // Correlation id (the live card subsumes the aside's run-id readout).
    const corr = el("live-corr");
    if (corr) {
      const corrId = result.correlation_id || "";
      corr.textContent = corrId ? `run ${corrId}` : "";
      // Fix 6: stash the RAW id so the copy handler copies exactly what is
      // shown here (without the "run " prefix).
      if (corrId) {
        corr.dataset.correlationId = corrId;
      } else {
        delete corr.dataset.correlationId;
      }
    }

    // Running-query echo. The poll payload carries no query_text, so use the
    // value captured at run start (falling back to the composer field).
    const queryEl = el("live-query");
    if (queryEl) {
      const queryText =
        state.liveQueryText ||
        (queryTextarea ? queryTextarea.value.trim() : "") ||
        "";
      queryEl.textContent = queryText || "—";
    }

    // Live elapsed ticker. Store the REAL server elapsed + a local timestamp;
    // the ~1s ticker shows base + drift. On terminal, freeze at the final
    // elapsed and stop ticking (it must never run after the run ends).
    const elapsedMs = Number.isFinite(result.elapsed_time_ms)
      ? result.elapsed_time_ms
      : null;
    if (isTerminal) {
      const finalMs =
        elapsedMs != null
          ? elapsedMs
          : state.liveElapsedBaseMs + (Date.now() - state.liveElapsedStamp);
      freezeLiveElapsed(finalMs);
    } else {
      if (elapsedMs != null) {
        state.liveElapsedBaseMs = elapsedMs;
        state.liveElapsedStamp = Date.now();
      }
      startLiveElapsedTicker();
    }

    // Guarded reads: ``created`` has no ``.result`` projection; model_answers /
    // debate_outputs may be undefined; model_slots is present on both.
    const answers = (result.result && result.result.model_answers) || [];
    const slots = result.model_slots || [];
    // HONESTY: a failed slot returned no answer, so it must NOT inflate the
    // "N/4 answers" text or the initial-answers progress fraction. Count only
    // slots that actually completed.
    const answersReceived = answers.filter(
      (a) => a.status === "completed",
    ).length;

    renderLiveStageStrip(result, answersReceived);
    renderLiveDebate(result);
    renderLiveModelStatus(slots, answers);
    renderLiveFallback(answers);
    renderLiveCap(result);
    renderLiveNotices(result);
  }

  // ---------------------------------------------------------------------------
  // Slice 4a (05 Result): verdict band + trust triangle
  // ---------------------------------------------------------------------------

  // Small element factory (textContent only — never innerHTML).
  function mkEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  const RESULT_SVG_NS = "http://www.w3.org/2000/svg";
  const RESULT_RING_RADIUS = 40;
  const RESULT_RING_CIRC = 2 * Math.PI * RESULT_RING_RADIUS;

  // Duration without the " elapsed" suffix, e.g. "41.2s" / "1m 05s".
  function formatDuration(ms) {
    return formatElapsed(ms).replace(/ elapsed$/, "");
  }

  // Format the finished-at UTC timestamp as "Jul 7, 2026 · finished 09:41:44
  // UTC" (UTC-anchored — the receipt time is authoritative in UTC). Guards a
  // missing/invalid value and any ICU rejection.
  function formatFinishedUtc(raw) {
    if (!raw) return "";
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return "";
    try {
      const datePart = new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      }).format(date);
      const timePart = new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: "UTC",
      }).format(date);
      return `${datePart} · finished ${timePart} UTC`;
    } catch (_) {
      try {
        return date.toISOString();
      } catch (_e) {
        return "";
      }
    }
  }

  function truncateText(text, max) {
    const value = String(text || "").trim();
    if (value.length <= max) return value;
    return `${value.slice(0, max - 1).trimEnd()}…`;
  }

  // Append " · " separated children to the meta row.
  function appendMetaSep(container) {
    container.appendChild(mkEl("span", "result-meta-sep", "·"));
  }

  // Draw the aligned/total trust ring. ``fraction`` is 0..1; total===0 draws
  // an empty ring (guarded upstream). Colours are set in CSS off the band's
  // ``data-consensus`` attribute; the draw animation is reduced-motion-guarded
  // in CSS. Returns the ring wrapper element.
  function buildTrustRing(aligned, total) {
    const fraction = total > 0 ? Math.max(0, Math.min(1, aligned / total)) : 0;
    const offset = RESULT_RING_CIRC * (1 - fraction);

    const wrap = mkEl("div", "result-ring");
    const svg = document.createElementNS(RESULT_SVG_NS, "svg");
    svg.setAttribute("width", "104");
    svg.setAttribute("height", "104");
    svg.setAttribute("viewBox", "0 0 104 104");
    svg.setAttribute("aria-hidden", "true");

    const track = document.createElementNS(RESULT_SVG_NS, "circle");
    track.setAttribute("class", "result-ring-track");
    track.setAttribute("cx", "52");
    track.setAttribute("cy", "52");
    track.setAttribute("r", String(RESULT_RING_RADIUS));
    track.setAttribute("fill", "none");
    track.setAttribute("stroke-width", "9");

    const value = document.createElementNS(RESULT_SVG_NS, "circle");
    value.setAttribute("class", "result-ring-value");
    value.setAttribute("cx", "52");
    value.setAttribute("cy", "52");
    value.setAttribute("r", String(RESULT_RING_RADIUS));
    value.setAttribute("fill", "none");
    value.setAttribute("stroke-width", "9");
    value.style.setProperty("--ring-circ", `${RESULT_RING_CIRC}`);
    value.style.setProperty("--ring-offset", `${offset}`);

    svg.append(track, value);

    const center = mkEl("div", "result-ring-center");
    center.appendChild(mkEl("span", "result-ring-count", `${aligned}/${total}`));
    center.appendChild(mkEl("span", "result-ring-label", "agree"));

    wrap.append(svg, center);
    return wrap;
  }

  // Build one trust-triangle card. ``value``/``valueSub`` are optional (the
  // uncertainty card carries prose only). ``accent`` drives the CSS role.
  function buildTrustCard({ accent, kicker, value, valueSub, caption, consensus }) {
    const card = mkEl("div", "result-trust-card");
    card.dataset.accent = accent;
    if (accent === "agreement") card.dataset.consensus = consensus ? "true" : "false";

    const head = mkEl("div", "result-trust-head");
    head.appendChild(mkEl("span", "result-trust-kicker", kicker));
    head.appendChild(mkEl("span", "result-trust-chip"));
    card.appendChild(head);

    if (value != null) {
      const valueEl = mkEl("div", "result-trust-value");
      valueEl.appendChild(mkEl("strong", null, value));
      if (valueSub) valueEl.appendChild(mkEl("span", "result-trust-value-sub", ` ${valueSub}`));
      card.appendChild(valueEl);
    }
    if (caption) card.appendChild(mkEl("div", "result-trust-caption", caption));
    return card;
  }

  // Populate the result view from a TERMINAL poll result. Called ONCE at the
  // terminal transition (never per 750ms poll), so no aria-live spam. Every
  // nested field is guarded. The green treatment is GATED behind
  // ``isConsensus`` (AC-019 "no false consensus").
  function renderResult(result) {
    if (!result) return;
    const res = result.result || {};
    const fs = res.final_synthesis || null;
    const agreement = res.agreement || null;
    const aligned =
      agreement && Number.isFinite(Number(agreement.aligned))
        ? Number(agreement.aligned)
        : 0;
    const total =
      agreement && Number.isFinite(Number(agreement.total))
        ? Number(agreement.total)
        : 0;
    const failedSteps = Array.isArray(result.failed_steps) ? result.failed_steps : [];

    // GREEN GATE (AC-019): green must reflect REAL, complete agreement — never
    // merely the presence of a recommendation (which exists even on a divided
    // panel). Requires: a real agreement signal, every model aligned, the
    // synthesis explicitly NOT preserving a false consensus, and no failed steps.
    const isConsensus = Boolean(
      agreement &&
        total > 0 &&
        aligned === total &&
        fs &&
        fs.quality_checks &&
        fs.quality_checks.false_consensus_preserved === false &&
        failedSteps.length === 0 &&
        String(result.status) === "completed",
    );

    // Revised count — INFERRED from position_movements' ``revised`` flag.
    const movements = Array.isArray(res.position_movements)
      ? res.position_movements
      : [];
    const revisedCount = movements.filter((m) => m && m.revised === true).length;

    // "You asked" question echo (poll payload has no query_text). Only the
    // submitted question is echoed — never the live textarea, which on a
    // rehydrated run holds unrelated in-progress text (C-B).
    const question = state.liveQueryText || "";
    const questionEl = el("result-question");
    if (questionEl) questionEl.textContent = question || "—";

    // Completion status pill (INK — never green).
    const status = result.status || "completed";
    const durationText = formatDuration(result.elapsed_time_ms);
    const completionEl = el("result-completion-text");
    if (completionEl) {
      let completionText;
      if (status === "completed") {
        completionText = `Completed in ${durationText}`;
      } else if (status === "partial") {
        completionText = `Finished with gaps in ${durationText}`;
      } else {
        completionText = `${STATUS_LABELS[status] || status} · ${durationText}`;
      }
      completionEl.textContent = completionText;
    }

    renderResultMeta(result, status, durationText);
    renderVerdictBand(result, fs, { isConsensus, aligned, total, revisedCount, movements });
    renderTrustTriangle(result, res, fs, { isConsensus, aligned, total });

    // Build the plain-text Copy/Export summary ONCE (textContent-safe).
    const summaryLines = [];
    if (question) summaryLines.push(question, "");
    const recommendation = fs && fs.recommendation ? String(fs.recommendation).trim() : "";
    if (recommendation) {
      // Mirror the on-screen eyebrow: a divided panel has no unified "verdict".
      summaryLines.push(`${isConsensus ? "Verdict" : "Leaning"}: ${recommendation}`);
    } else {
      summaryLines.push("Verdict: No synthesis was produced for this run.");
    }
    summaryLines.push(
      isConsensus
        ? `Agreement: ${aligned} of ${total} models aligned.`
        : `Agreement: ${aligned} of ${total} models aligned; the rest are preserved as disagreement.`,
    );
    if (result.correlation_id) summaryLines.push(`Run: ${result.correlation_id}`);
    state.lastResultSummary = summaryLines.join("\n");
    state.lastResultRunId = result.query_run_id || result.correlation_id || "run";
  }

  function renderResultMeta(result, status, durationText) {
    const meta = el("result-meta");
    if (!meta) return;
    meta.textContent = "";

    // Status label (ink dot — not green).
    const statusWrap = mkEl("span", "result-meta-status");
    statusWrap.appendChild(mkEl("span", "result-meta-status-dot"));
    statusWrap.appendChild(mkEl("span", null, STATUS_LABELS[status] || status));
    meta.appendChild(statusWrap);

    appendMetaSep(meta);
    meta.appendChild(mkEl("span", "mono", durationText));

    const finished = formatFinishedUtc(result.result_generated_at_utc);
    if (finished) {
      appendMetaSep(meta);
      const finishedEl = mkEl("span", null, finished);
      finishedEl.style.whiteSpace = "nowrap";
      meta.appendChild(finishedEl);
    }

    // actual $X (approved $Y).
    const actual = Number(result.actual_cost_usd);
    // Guard the field's PRESENCE explicitly so a missing estimate coerces to
    // NaN (rendered as "—" / omitted) rather than a bogus "$0.00" (C-D).
    const approved =
      result.cost_estimate && result.cost_estimate.estimated_cost_usd != null
        ? Number(result.cost_estimate.estimated_cost_usd)
        : NaN;
    if (Number.isFinite(actual)) {
      appendMetaSep(meta);
      const moneyWrap = mkEl("span", null);
      moneyWrap.appendChild(document.createTextNode("actual "));
      moneyWrap.appendChild(
        mkEl("span", "mono result-meta-money-actual", formatUsd(actual, { suffix: false })),
      );
      if (Number.isFinite(approved)) {
        moneyWrap.appendChild(
          document.createTextNode(` (approved ${formatUsd(approved, { suffix: false })})`),
        );
      }
      meta.appendChild(moneyWrap);
    }

    if (result.correlation_id) {
      appendMetaSep(meta);
      meta.appendChild(mkEl("span", "mono", result.correlation_id));
    }
  }

  function renderVerdictBand(result, fs, ctx) {
    const band = el("result-verdict");
    if (!band) return;
    band.textContent = "";
    delete band.dataset.empty;

    // No synthesis (failed/blocked run reached here defensively) — NEVER green.
    if (!fs) {
      band.dataset.consensus = "false";
      band.dataset.empty = "true";
      band.textContent = "No synthesis was produced for this run.";
      return;
    }

    const { isConsensus, aligned, total, revisedCount } = ctx;
    band.dataset.consensus = isConsensus ? "true" : "false";

    band.appendChild(buildTrustRing(aligned, total));

    const content = mkEl("div", "result-verdict-content");
    content.appendChild(
      mkEl(
        "span",
        "result-verdict-eyebrow",
        isConsensus ? "The panel's verdict" : "The panel's leaning",
      ),
    );

    const recommendation = fs.recommendation ? String(fs.recommendation).trim() : "";
    content.appendChild(
      mkEl("div", "result-verdict-text", recommendation || "No recommendation was recorded for this run."),
    );

    // Honest summary line — derived from real fields, no banned verbs.
    let summary;
    if (isConsensus) {
      summary = `${aligned} of ${total} models aligned`;
      if (revisedCount > 0) {
        summary += ` · ${revisedCount} revised their position`;
      }
    } else {
      summary = `${aligned} of ${total} models aligned — the rest are preserved as disagreement below.`;
    }
    content.appendChild(mkEl("span", "result-verdict-summary", summary));

    // High-stakes caveat, if the synthesis carries one.
    if (fs.high_stakes_notice) {
      content.appendChild(
        mkEl("span", "result-verdict-caveat", String(fs.high_stakes_notice).trim()),
      );
    }

    // Inferred-narration caption for anything derived from position_movements.
    if (isConsensus && revisedCount > 0) {
      content.appendChild(
        mkEl(
          "span",
          "result-verdict-caption",
          "Revision counts are inferred from the panel's position movements, not quoted.",
        ),
      );
    }

    band.appendChild(content);
  }

  function renderTrustTriangle(result, res, fs, ctx) {
    const trust = el("result-trust");
    if (!trust) return;
    trust.textContent = "";
    const { isConsensus, aligned, total } = ctx;

    // Agreement — green accent ONLY when isConsensus.
    trust.appendChild(
      buildTrustCard({
        accent: "agreement",
        consensus: isConsensus,
        kicker: "Agreement",
        value: `${aligned} of ${total}`,
        valueSub: "aligned",
        caption: isConsensus
          ? "How many models the final synthesis places in agreement — inferred, not a tallied vote."
          : "How many models the final synthesis places in agreement — inferred, not a tallied vote; the panel did not fully align, so the disagreement is preserved below.",
      }),
    );

    // Source support — BLUE. Percentage from citation_coverage; source count is
    // NON-fallback sources across model_answers. Degrade gracefully if absent.
    const coverage = fs && fs.citation_coverage ? fs.citation_coverage : null;
    let coveragePct = null;
    if (coverage) {
      const ratio = Number(coverage.coverage_ratio);
      if (Number.isFinite(ratio)) coveragePct = Math.round(ratio * 100);
    }
    const answers = Array.isArray(res.model_answers) ? res.model_answers : [];
    // Count DISTINCT non-fallback sources (de-dupe by url/title) so two
    // models citing the same page don't inflate "N sources cited".
    const sourceKeys = new Set();
    for (const answer of answers) {
      const sources = answer && Array.isArray(answer.sources) ? answer.sources : [];
      for (const s of sources) {
        if (!s || s.is_fallback) continue;
        const key = s.url || s.title;
        if (key) sourceKeys.add(key);
      }
    }
    const sourceCount = sourceKeys.size;
    const sourceSub = `· ${sourceCount} source${sourceCount === 1 ? "" : "s"} cited`;
    trust.appendChild(
      buildTrustCard({
        accent: "source",
        kicker: "Source support",
        value: coveragePct != null ? `${coveragePct}%` : "—",
        valueSub: sourceSub,
        caption: "Material claims scored against citations.",
      }),
    );

    // Open uncertainty — AMBER. Prose only; NO fabricated numeric flag count.
    const uncertaintyText = fs && fs.uncertainty ? String(fs.uncertainty).trim() : "";
    trust.appendChild(
      buildTrustCard({
        accent: "uncertainty",
        kicker: "Open uncertainty",
        caption: uncertaintyText
          ? truncateText(uncertaintyText, 180)
          : "No open uncertainty was flagged for this run.",
      }),
    );
  }

  function focusResultHeading() {
    if (!resultHeading) return;
    resultHeading.focus({ preventScroll: true });
    resultHeading.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
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
    // Slice 3 (04 Live run): the live-elapsed ticker only runs while a run is
    // in flight. Terminal freezing of the readout is handled by renderLiveRun
    // (which sets the final value before this clear); here we just guarantee
    // the interval is gone once the run is no longer running.
    if (!isRunning) stopLiveElapsedTicker();
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
    // The cost gate's "Approve & run" CTA is disabled during a run for the
    // same double-submit reason.
    if (gateConfirmButton) {
      gateConfirmButton.disabled = isRunning || !state.currentEstimate;
    }
    if (isRunning && !state.hasScrolledToRunControls) {
      // Scroll once on the transition into running. The poll loop
      // would otherwise scroll the page aggressively every 750ms.
      state.hasScrolledToRunControls = true;
      if (cancelButton) {
        cancelButton.scrollIntoView({
          behavior: prefersReducedMotion() ? "auto" : "smooth",
          block: "center",
        });
        cancelButton.focus({ preventScroll: true });
      }
    } else if (!isRunning && state.hasScrolledToRunControls) {
      // Reset for the next run so the scroll-once fires again.
      state.hasScrolledToRunControls = false;
    }
    // Re-assert the high-stakes gate on top of the run-state disabling so
    // an un-acknowledged safety topic keeps the CTA disabled after a run
    // finishes.
    applyHighStakesGate();
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
    // wrappers from ``proceedWithRun`` / ``pollRun``.
    // A status update in the middle of a run is not a time
    // change, so we do not touch the time card from here.
    // Surface the citation coverage denominator so users can audit the
    // ratio itself. ``material_claim_count`` is the sum of the four
    // models' material-claim counts. We avoid displaying this when the
    // run has no initial answers yet (cost-blocked, pending, etc.).
    const claimMeta = el("claim-meta");
    if (claimMeta) {
      const rawCount = result?.material_claim_count ?? 0;
      const count = Number.isFinite(Number(rawCount)) ? Number(rawCount) : 0;
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
    charCount.textContent = `${length.toLocaleString()} / 20,000`;
    // Keep the visible "N / 20,000" but give assistive tech an
    // unambiguous reading ("N of 20,000 characters") — the bare "/"
    // is unit-ambiguous to a screen reader.
    charCount.setAttribute(
      "aria-label",
      `${length.toLocaleString()} of 20,000 characters`,
    );
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

  // ---------------------------------------------------------------------------
  // Screen 03 — Cost gate (``cost_review`` state)
  // ---------------------------------------------------------------------------

  // COPY-003 (verbatim, docs/33-content-design.md). Shown in the confirm
  // band above the server's first ``reasons[]`` line.
  const COPY_003_COST_WARNING =
    "This run may cost more than the normal target because of selected " +
    "models, query length, search, or debate rounds. Review the estimate " +
    "before continuing.";

  // The hard block boundary ($0.25) — the rail's full-scale value. The
  // confirm tick sits at $0.15 (60% of scale, matched by the CSS segment
  // widths). Numbers are the design's fixed guardrail labels; the ACTIVE
  // band is driven by the server ``threshold_action``, never re-derived
  // from these constants.
  const COST_HARD_LIMIT_USD = 0.25;

  // Width of the illustrative planning band shown as "estimated range". The
  // server returns a point estimate with no confidence interval, so this ±
  // band is presentational only — the upper bound is clamped to
  // ``COST_HARD_LIMIT_USD`` in ``renderCostGate`` so it can never print
  // above the "blocked, no override" ceiling on the same card.
  const PLANNING_RANGE_PCT = 0.15;

  // Partition a ``cost_estimate.breakdown`` into the two labelled row
  // lists the gate renders — by model AND by stage — plus the shared
  // total. Pure (no DOM, no closures) so it is unit-testable in node.
  //   * by_model: the ``kind === "synthesis"`` row renders as "Synthesis
  //     writer"; every other row uses its ``display_name``.
  //   * by_stage: the server ``stage`` enum maps to friendly labels; an
  //     unknown stage falls back to its raw key.
  // Both lists re-sum to ``total`` by construction (the reconciliation
  // invariant), so each column's Total row shows the same figure.
  function costGatePartitions(breakdown) {
    const stageLabels = {
      initial_answers: "Initial answers × 4",
      debate_round_1: "Debate round 1",
      debate_round_2: "Debate round 2",
      synthesis: "Synthesis",
    };
    const byModelRows = Array.isArray(breakdown && breakdown.by_model)
      ? breakdown.by_model
      : [];
    const byStageRows = Array.isArray(breakdown && breakdown.by_stage)
      ? breakdown.by_stage
      : [];
    return {
      byModel: byModelRows.map((row) => ({
        label: row.kind === "synthesis" ? "Synthesis writer" : row.display_name,
        usd: row.usd,
      })),
      byStage: byStageRows.map((row) => ({
        label: stageLabels[row.stage] || row.stage,
        usd: row.usd,
      })),
      total: breakdown ? breakdown.total : undefined,
    };
  }

  // Format a USD amount for the gate's mono cells — reuses ``formatUsd``
  // (the single money-formatting source of truth) with the " USD" suffix
  // off so the compact table/total read as "$0.19", not "$0.19 USD".
  function gateUsd(usdAmount) {
    return formatUsd(usdAmount, { suffix: false });
  }

  // A fixed 2-decimal USD render for the presentational planning-range
  // endpoints. The range is an illustrative ±band (see ``renderCostGate``),
  // NOT a server-provided interval, so it is shown at whole-cent precision
  // to avoid implying sub-cent accuracy on a derived figure.
  function gateUsd2dp(usdAmount) {
    const num = Number(usdAmount);
    if (!Number.isFinite(num)) return "$0.00";
    return `$${num.toFixed(2)}`;
  }

  // Choose ONE decimal count for a whole itemized column so every cell
  // aligns. Driven by the SMALLEST magnitude present (< $0.01 → 4 dp;
  // < $1 → 3 dp; else 2 dp) and applied to every row AND the Total —
  // tiering each cell independently (as an earlier version did) misaligns a
  // column that spans a magnitude boundary (e.g. a sub-cent row beside a
  // cent-scale total). Matches the mock's aligned "$0.034 … $0.190".
  function columnDecimals(amounts) {
    const finite = amounts.map(Number).filter(Number.isFinite).map(Math.abs);
    if (!finite.length) return 2;
    const smallest = Math.min(...finite);
    return smallest < 0.01 ? 4 : smallest < 1 ? 3 : 2;
  }

  function gateUsdFixed(usdAmount, decimals) {
    const num = Number(usdAmount);
    if (!Number.isFinite(num)) return "$0.00";
    return `$${num.toFixed(decimals)}`;
  }

  // Render a list of {label, usd} rows plus a bold Total row into a
  // container. Built with createElement + textContent (never innerHTML)
  // so a catalog display name can never inject markup.
  function renderCostRows(container, rows, total) {
    if (!container) return;
    const decimals = columnDecimals(rows.map((r) => r.usd).concat([total]));
    const frag = document.createDocumentFragment();
    for (const row of rows) {
      frag.appendChild(
        costRowNode(row.label, gateUsdFixed(row.usd, decimals), false),
      );
    }
    frag.appendChild(costRowNode("Total", gateUsdFixed(total, decimals), true));
    container.replaceChildren(frag);
  }

  function costRowNode(labelText, amountText, isTotal) {
    const row = document.createElement("div");
    row.className = isTotal ? "cost-row cost-row-total" : "cost-row";
    const label = document.createElement("span");
    label.className = "cost-row-label";
    label.textContent = labelText;
    const amount = document.createElement("span");
    amount.className = "cost-row-amount";
    amount.textContent = amountText;
    row.append(label, amount);
    return row;
  }

  // Populate the cost gate (screen 03) from an estimate response. Called
  // for the ``require_confirmation`` and ``block`` bands only; the
  // ``allow`` band skips this screen entirely. Does NOT switch the view —
  // the caller does that after rendering so the DOM is ready when it shows.
  // Populate the cost gate and RETURN its live-region announcement string.
  // The announcement is deliberately NOT written here: this runs while the
  // gate is still ``hidden``, and an ``aria-live`` mutation on a
  // non-rendered node is not reliably announced — the caller writes it via
  // ``revealCostGate`` AFTER the view is shown. Throws when the estimate
  // carries no usable cost figure so the caller surfaces an error instead
  // of rendering a "$0.00" spend-approval button (worst-case money bug).
  function renderCostGate(estimate) {
    const ce = estimate.cost_estimate;
    const action = ce.threshold_action;
    const total = Number(ce.estimated_cost_usd);
    if (!Number.isFinite(total)) {
      throw new Error(
        "The estimate response did not include a usable cost figure. " +
          "Please run the estimate again.",
      );
    }
    const breakdown = ce.breakdown || {};
    const reasons = Array.isArray(ce.reasons) ? ce.reasons : [];

    // Question echo (from the composer).
    if (gateQuestion) gateQuestion.textContent = queryTextarea.value.trim();

    // Big mono total. The estimated range is band-specific and is set only
    // in the confirm branch below (it is hidden in the block band, where a
    // range for a run that will not execute is both meaningless and — since
    // the total is above the ceiling — liable to invert past it).
    if (gateTotal) gateTotal.textContent = gateUsd(total);

    // Threshold rail: marker at estimate/hard-limit, clamped to [0,100]%.
    const pct = Math.max(0, Math.min(100, (total / COST_HARD_LIMIT_USD) * 100));
    if (gateRailMarker) gateRailMarker.style.left = `${pct}%`;
    if (gateRail) gateRail.dataset.band = action;
    if (gateCard) gateCard.dataset.band = action;

    // Itemized table — both partitions of the SAME breakdown total.
    const partitions = costGatePartitions(breakdown);
    renderCostRows(gateByModel, partitions.byModel, partitions.total);
    renderCostRows(gateByStage, partitions.byStage, partitions.total);

    if (action === "block") {
      // BLOCK (> $0.25). Screen 07 (cost-blocked) with the full COPY-004
      // treatment lands in Slice 6; for now this is a minimal inline
      // blocked state: server reasons + the hard-limit note, no proceed.
      // TODO(Slice 6 / COPY-004): replace with the dedicated 07 edge state.
      if (gateBandLabel) gateBandLabel.textContent = "Cost review — run blocked";
      if (gateReason) {
        const reasonText = reasons.length ? `${reasons.join(" ")} ` : "";
        gateReason.textContent =
          `${reasonText}This run is above the $0.25 hard limit — execution is blocked, no override.`;
      }
      if (gateConfirmButton) gateConfirmButton.hidden = true;
      if (gateCapNote) gateCapNote.hidden = true;
      // Ctrl+Enter confirms nothing in the block band — hide that hint.
      if (gateHintConfirm) gateHintConfirm.hidden = true;
      // No planning range for a run that will not execute.
      if (gateRangeWrap) gateRangeWrap.hidden = true;
      return `Run blocked. Estimated ${gateUsd(total)} is above the $0.25 hard limit.`;
    }

    // REQUIRE_CONFIRMATION ($0.15–$0.25).
    // Illustrative ±``PLANNING_RANGE_PCT`` planning band (NOT a server
    // interval). Only shown in this band, where total ≤ the hard limit so
    // ``lo < hi`` always holds; ``hi`` is still clamped to the ceiling and
    // both endpoints render at whole-cent precision (no false sub-cent).
    if (gateRangeWrap) gateRangeWrap.hidden = false;
    if (gateRange) {
      const lo = total * (1 - PLANNING_RANGE_PCT);
      const hi = Math.min(total * (1 + PLANNING_RANGE_PCT), COST_HARD_LIMIT_USD);
      gateRange.textContent = `${gateUsd2dp(lo)}–${gateUsd2dp(hi)}`;
    }
    if (gateBandLabel) {
      gateBandLabel.textContent = "Cost review — your confirmation required";
    }
    if (gateReason) {
      const firstReason = reasons.length ? ` ${reasons[0]}` : "";
      gateReason.textContent = `${COPY_003_COST_WARNING}${firstReason}`;
    }
    if (gateConfirmButton) {
      gateConfirmButton.hidden = false;
      const label = gateConfirmButton.querySelector(".button-label");
      if (label) label.textContent = `Approve ${gateUsd(total)} & run`;
    }
    if (gateCapNote) gateCapNote.hidden = false;
    if (gateHintConfirm) gateHintConfirm.hidden = false;
    return `Cost review: your confirmation required. Estimated ${gateUsd(total)}.`;
  }

  // ``true`` when the user has asked the OS to minimise motion.
  function prefersReducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (_) {
      return false;
    }
  }

  // Land focus on the live-run heading AND bring it into view. ``setRunning``
  // may have just smooth-scrolled toward the (now display:none) #cancel-run;
  // an explicit scrollIntoView here wins (last scroll target) so the h1 is not
  // left off-screen for a sighted keyboard user. Reduced-motion honoured.
  function focusLiveHeading() {
    if (!liveRunHeading) return;
    liveRunHeading.focus({ preventScroll: true });
    liveRunHeading.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
  }

  // Post-reveal choreography for the cost gate. Call AFTER ``setView`` so
  // the region is in the rendered accessibility tree. Moves focus into the
  // gate (WCAG 2.4.3 — never strand focus on the now-hidden composer),
  // fires the live-region announcement (set here, not in ``renderCostGate``,
  // because aria-live only queues mutations made while rendered), and scrolls
  // the card into view honouring ``prefers-reduced-motion``.
  function revealCostGate(action, announcement) {
    if (gateLive && announcement) {
      gateLive.textContent = "";
      // Announce after the next frame (post-layout) so the empty→text change
      // is observed by AT as a discrete update. The region is persistent
      // (outside the swapped views), so it is always a registered live region.
      const announce = () => {
        gateLive.textContent = announcement;
      };
      if (typeof requestAnimationFrame === "function") {
        requestAnimationFrame(announce);
      } else {
        announce();
      }
    }
    // Focus the heading (SR reads the gate from the top, cost context first)
    // rather than the CTA. The heading is present in both bands, incl. block
    // where the confirm button is hidden.
    const focusTarget =
      gateHeading ||
      (action === "block" ? gateBackButton : gateConfirmButton);
    if (focusTarget) focusTarget.focus({ preventScroll: true });
    if (gateCard) {
      gateCard.scrollIntoView({
        behavior: prefersReducedMotion() ? "auto" : "smooth",
        block: "center",
      });
    }
  }

  // "Change models" / "Back to edit": return to the composer to adjust the
  // query or model slots. The next estimate re-opens the gate fresh.
  function gateBackToComposer() {
    setView("composer");
    if (queryTextarea) queryTextarea.focus({ preventScroll: true });
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
      // Slice 1: fan the itemized ``by_model`` breakdown out onto the
      // slot cards and surface the grand total in the composer footer.
      // ``by_model`` is emitted one row per slot in slot order, so we map
      // the (non-synthesis) rows to slots BY POSITION — keying by
      // model_id would collapse two slots that pick the same model. The
      // ``kind === "synthesis"`` writer row is NOT a slot, so it is
      // excluded before the positional mapping.
      state.perModelEstimates = [];
      const byModel =
        estimate.cost_estimate.breakdown &&
        estimate.cost_estimate.breakdown.by_model;
      if (Array.isArray(byModel)) {
        state.perModelEstimates = byModel
          .filter((row) => row.kind !== "synthesis")
          .map((row) => row.usd);
      }
      renderModelInputs(getModelIds());
      if (composerTotalEstimate) {
        composerTotalEstimate.textContent = gateUsd(
          estimate.cost_estimate.estimated_cost_usd,
        );
      }
      const { primary: usdPrimary, secondary: usdSecondary } = formatCostWithLocal(
        estimate.cost_estimate.estimated_cost_usd,
      );
      const action = estimate.cost_estimate.threshold_action;
      // Slice 2 (03 Cost gate): route by the server ``threshold_action``.
      //   allow                → skip the gate, run straight away.
      //   require_confirmation  → show the itemized cost gate (screen 03).
      //   block                → show the gate's inline blocked state.
      // The legacy inline composer callout (``#cost-confirmation``) is no
      // longer surfaced here; its confirm role moved to the dedicated
      // gate. The element stays in the template (hidden) for its contract.
      // PR-0 / Bug 2: wrap the success-path DOM work in its own try/catch
      // so a broken render surfaces a message instead of a blank screen;
      // the outer finally always resets the estimate button.
      try {
        if (usdSecondary) renderCostSecondary(estimate.cost_estimate.estimated_cost_usd);
        renderNotices(null);
        if (action === "allow") {
          // ≤ $0.15: nothing to confirm — go straight to the run.
          await proceedWithRun();
        } else {
          // require_confirmation ($0.15–$0.25) or block (> $0.25):
          // render, switch to the gate, THEN move focus + announce + scroll.
          const announcement = renderCostGate(estimate);
          setView("cost-gate");
          revealCostGate(action, announcement);
          toast({
            message: `Cost estimate ready: ${usdPrimary}.`,
            tone: "success",
          });
        }
      } catch (renderError) {
        // The estimate itself succeeded — the response is valid — but the
        // gate render (or the auto-proceed) blew up. Surface it rather
        // than leaving the composer silent.
        handleError(
          renderError instanceof ApiError
            ? renderError
            : new Error(
                `Got the estimate (${usdPrimary}) but could not open the cost review. ` +
                  `${renderError && renderError.message ? renderError.message : "Unknown error."}`,
              ),
        );
      }
      return estimate;
    } finally {
      setButtonLoading(estimateButton, false);
      // ``setButtonLoading`` clears ``disabled``; re-assert the gate so a
      // high-stakes topic detected mid-compose keeps the CTA disabled.
      applyHighStakesGate();
    }
  }

  function warningAcknowledgements(warnings) {
    return warnings.map((warning) => ({
      warning_type: warning.warning_type,
      version: warning.version,
    }));
  }

  // ---------------------------------------------------------------------------
  // High-stakes gate (COPY-002)
  // ---------------------------------------------------------------------------
  // The gate appears only when ``POST /v1/query-runs/warnings`` reports a
  // ``high_stakes`` warning for the current query. While it is showing and
  // the acknowledgement checkbox is unchecked, the primary CTA stays
  // disabled. The acknowledgement itself is still delivered to the server as
  // ``safety_acknowledgements[]`` by the existing run flow.

  // Re-derive the primary CTA's disabled state from the run + gate state.
  function applyHighStakesGate() {
    const blocked = state.highStakesRequired && !state.highStakesAck;
    if (estimateButton) {
      estimateButton.disabled = state.isRunning || blocked;
      estimateButton.dataset.gateBlocked = blocked ? "true" : "false";
    }
  }

  // Show or hide the gate; hiding resets the acknowledgement so a later
  // high-stakes query re-requires an explicit check.
  function setHighStakesRequired(required) {
    state.highStakesRequired = required;
    if (highStakesGate) highStakesGate.hidden = !required;
    if (!required) {
      state.highStakesAck = false;
      if (highStakesAckCheckbox) highStakesAckCheckbox.checked = false;
    }
    applyHighStakesGate();
  }

  // Probe the warnings endpoint for the current query text. A
  // ``high_stakes`` warning raises the gate; anything else (or a probe
  // failure) leaves the user un-gated. Best-effort: a network error must
  // never block composing.
  // Monotonically increasing token stamped on every warnings probe. The
  // debounced probes are fired without ordering guarantees, so an older
  // request can resolve AFTER a newer one and clobber the gate state
  // (stranding the CTA disabled over empty text, or — worse — hiding the
  // gate so a run proceeds with the high-stakes ack unchecked). Each
  // probe captures the token it was issued with before awaiting and
  // ignores its own response unless it is still the latest token issued.
  let highStakesProbeToken = 0;
  async function checkHighStakesWarning() {
    const token = ++highStakesProbeToken;
    const queryText = queryTextarea.value.trim();
    if (!queryText) {
      // Empty text resolves synchronously via the latest probe.
      if (token === highStakesProbeToken) setHighStakesRequired(false);
      return;
    }
    try {
      const response = await api("/v1/query-runs/warnings", {
        method: "POST",
        body: JSON.stringify({ query_text: queryText }),
      });
      // Drop a stale response: a newer probe was issued while this one
      // was in flight, so its (fresher) result must win.
      if (token !== highStakesProbeToken) return;
      const required =
        Array.isArray(response.warnings) &&
        response.warnings.some((w) => w.warning_type === "high_stakes");
      setHighStakesRequired(required);
    } catch (_) {
      // Non-fatal: leave the gate as-is rather than surfacing an error.
    }
  }

  let highStakesProbeTimer = null;
  function scheduleHighStakesCheck() {
    if (highStakesProbeTimer) clearTimeout(highStakesProbeTimer);
    highStakesProbeTimer = setTimeout(() => {
      highStakesProbeTimer = null;
      checkHighStakesWarning();
    }, 500);
  }

  // Returns ``true`` when the high-stakes gate is satisfied (not required,
  // or acknowledged). When it blocks, it nudges the user to the checkbox.
  function highStakesGateSatisfied() {
    if (!state.highStakesRequired || state.highStakesAck) return true;
    toast({
      message:
        "Acknowledge the decision-support notice before running this query.",
      tone: "warn",
    });
    if (highStakesAckCheckbox) highStakesAckCheckbox.focus();
    return false;
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
    if (!highStakesGateSatisfied()) return;
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
      // ``setButtonLoading`` clears ``disabled``; re-assert the run/gate
      // state so the CTA stays disabled when a run is now in flight (the
      // ``allow`` band auto-proceeds inside ``estimateRun``) or a
      // high-stakes topic is unacknowledged.
      applyHighStakesGate();
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
    // Defense-in-depth for the money boundary: a ``block`` estimate must
    // never POST a create. The confirm button is hidden and the keyboard
    // path is guarded in the block band, and the server rejects it with
    // COST_LIMIT_EXCEEDED — this early return closes the last direct-call
    // gap so no client path can spend past the $0.25 hard limit.
    if (
      state.currentEstimate.cost_estimate.threshold_action === "block"
    ) {
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
    // The visible confirm CTA is now the cost gate's "Approve $X & run"
    // (``gateConfirmButton``); fall back to the legacy composer proceed
    // button if the gate markup is absent (trimmed template).
    const confirmBtn = gateConfirmButton || proceedButton;
    if (!checkMagicPhraseAck(queryText, confirmBtn)) {
      return;
    }
    setButtonLoading(confirmBtn, true);
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
      // Slice 3 (04 Live run): capture the submitted question so the live-run
      // running-query band can echo it (the poll payload has no query_text),
      // and reset the live view's SR/elapsed state for a fresh run.
      state.liveQueryText = queryText;
      state.lastLiveStatus = null;
      // Slice 4a (05 Result): a new run must never serve the previous run's
      // Copy/Export text, and the terminal-branch guard must start fresh (C-C).
      state.lastResultSummary = null;
      state.lastResultRunId = null;
      state.terminalHandled = false;
      // Fix 3: a NEW run must re-render every live block even if its first
      // payload is byte-identical to the previous run's — reset the guards.
      state.liveSig = {
        stage: null,
        debate: null,
        models: null,
        fallback: null,
        notices: null,
      };
      state.liveElapsedBaseMs = 0;
      state.liveElapsedStamp = Date.now();
      setRunning(true);
      updateRunMeta(created);
      renderProgress(created.progress);
      // PR-0 / Bug 8: capture the run start time once, on the
      // first run-create response, so later poll ticks do not
      // overwrite the displayed time until a terminal state.
      setRunStartTime(created.result_generated_at_utc);
      // The estimate is now consumed; collapse the cost callout until
      // the next estimate.
      hideCostConfirmation();
      // Slice 3 (04 Live run): swap to the dedicated live-run view and seed it
      // from the create response (which has no ``.result`` projection — every
      // nested read in ``renderLiveRun`` is guarded).
      setView("live-run");
      // Fix 2: setRunning(true) above focused the now-hidden #cancel-run;
      // land focus on the visible live-run heading instead (one h1 per view).
      focusLiveHeading();
      renderLiveRun(created);
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
      setButtonLoading(confirmBtn, false);
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
      // Fix 11: a run discovered here never went through proceedWithRun, so it
      // has not switched to the live card. Show it (otherwise we poll a hidden
      // view) and land focus on the heading, matching the proceed path.
      setView("live-run");
      focusLiveHeading();
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
    renderLiveRun(result);
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
      // C-A: a slow poll response (server latency > the 750ms poll interval)
      // can re-enter this terminal branch after it already ran, double-firing
      // the completion toast + focus move. Handle the transition exactly once.
      if (state.terminalHandled) {
        return;
      }
      state.terminalHandled = true;
      stopPolling();
      setRunning(false);
      // PR-0 / Bug 8: replace the displayed time with the
      // completion time on the first terminal transition. Polling
      // has already stopped, so this is the last time we touch
      // the card for this run.
      finalizeRunTime(result.result_generated_at_utc);
      // Slice 4a (05 Result): if a real synthesis exists, transition to the
      // result view (verdict band + trust triangle) and move focus to its
      // heading. ``renderResult`` is called ONCE here (not per 750ms poll —
      // polling has already stopped) so there is no aria-live spam. If there is
      // NO final_synthesis (failed/timed_out/cancelled/blocked), STAY on the
      // live-run view: its terminal error state + ``#live-notices`` handle that.
      if (result.result && result.result.final_synthesis) {
        renderResult(result);
        setView("result");
        focusResultHeading();
      }
      if (result.status === "completed") {
        toast({ message: "Run completed. See the synthesis below.", tone: "success" });
      } else if (result.status === "partial") {
        toast({
          message: liveNoticesHaveContent(result)
            ? "Run finished with partial results. See the run notices above."
            : "Run finished with partial results — some steps did not complete.",
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
            : liveNoticesHaveContent(result)
              ? 'The run notices above explain what went wrong.'
              : 'Copy the run ID above and contact support if this persists.',
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
    // Slice 3 (04 Live run): the elapsed ticker must never outlive polling.
    stopLiveElapsedTicker();
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
      // Slice 3 (04 Live run): reflect the cancelled state in the live-run
      // card (pill → "Cancelled", Stop hidden, elapsed frozen).
      renderLiveRun(result);
      renderNotices(result);
      // PR-0 / Bug 8: cancel is a terminal transition; finalize
      // the run time once so the card shows the cancel time
      // rather than the start time.
      finalizeRunTime(result.result_generated_at_utc);
      stopPolling();
      setRunning(false);
      // Slice 4a (05 Result): cancelled runs almost always have no synthesis, so
      // we stay on the live-run view. Transition only if one somehow exists.
      if (result.result && result.result.final_synthesis) {
        renderResult(result);
        setView("result");
        focusResultHeading();
      }
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
    // Slice 1: probe the warnings endpoint (debounced) so the COPY-002
    // high-stakes gate appears as soon as the query looks like a safety
    // topic. Also re-probe on blur to catch a paste that skipped input.
    queryTextarea.addEventListener("input", scheduleHighStakesCheck);
    queryTextarea.addEventListener("blur", checkHighStakesWarning);
    updateQueryValidation();
  }

  function initHighStakesGate() {
    if (!highStakesAckCheckbox) return;
    highStakesAckCheckbox.addEventListener("change", () => {
      state.highStakesAck = highStakesAckCheckbox.checked;
      applyHighStakesGate();
    });
  }

  function initKeyboardShortcuts() {
    document.addEventListener("keydown", (event) => {
      const gateActive = costGateContainer && !costGateContainer.hidden;
      const isCmdEnter = (event.metaKey || event.ctrlKey) && event.key === "Enter";
      if (isCmdEnter) {
        event.preventDefault();
        // On the cost gate, Ctrl/Cmd+Enter confirms the estimate (unless
        // the confirm CTA is absent/disabled — e.g. the block band).
        if (gateActive) {
          if (gateConfirmButton && !gateConfirmButton.hidden && !gateConfirmButton.disabled) {
            proceedWithRun();
          }
          return;
        }
        // Single-CTA design: Ctrl/Cmd+Enter runs the estimate-first
        // flow (``startRun``), which routes through the cost gate. The
        // high-stakes gate keeps the CTA disabled until acknowledged.
        if (!estimateButton.disabled) {
          startRun();
        }
        return;
      }
      if (event.key === "Escape") {
        // On the cost gate, Esc returns to the composer ("Back to edit").
        if (gateActive && !state.isRunning) {
          event.preventDefault();
          gateBackToComposer();
          return;
        }
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
    // Slice 0 scaffold: start on the composer view. Later slices drive
    // ``setView`` from the run lifecycle; for now it just asserts the
    // initial state and no-ops if the view container is absent.
    setView("composer");
    initThemeToggle();
    initModelSlotSelection();
    initQueryValidation();
    initHighStakesGate();
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
    // Shared run-id clipboard helper (Fix 6): both the aside's #copy-correlation
    // button and the live card's #live-corr button copy a run id and show the
    // same copied-title feedback. Extracted so both stay in lockstep.
    async function copyRunIdToClipboard(button, value, idleTitle) {
      if (!button || !value) return;
      try {
        await navigator.clipboard.writeText(value);
        button.dataset.copied = "true";
        button.title = "Copied!";
        setTimeout(() => {
          delete button.dataset.copied;
          button.title = idleTitle;
        }, 1500);
      } catch (_) {
        button.title = "Copy failed — select and copy manually.";
      }
    }
    if (copyCorrelationButton) {
      copyCorrelationButton.addEventListener("click", () => {
        const target = el("correlation-meta");
        const value = (target?.textContent || "").trim();
        if (!value || value === "Not started") return;
        copyRunIdToClipboard(
          copyCorrelationButton,
          value,
          "Copy run ID — include it if you report an issue.",
        );
      });
    }
    // Fix 6: the live card's run id is copyable too (the aside copy button is
    // hidden during a live run). It copies the SAME id shown, stashed on the
    // button's dataset by ``renderLiveRun``.
    const liveCorrButton = el("live-corr");
    if (liveCorrButton) {
      liveCorrButton.addEventListener("click", () => {
        const value = (liveCorrButton.dataset.correlationId || "").trim();
        if (!value) return;
        copyRunIdToClipboard(liveCorrButton, value, "Copy run ID");
      });
    }
    if (proceedButton) {
      proceedButton.addEventListener("click", () => {
        proceedWithRun();
      });
    }
    // Cost gate (screen 03) actions. "Approve $X & run" reuses the same
    // confirmation-token create path as the legacy proceed button; "Change
    // models" returns to the composer.
    if (gateConfirmButton) {
      gateConfirmButton.addEventListener("click", () => {
        proceedWithRun();
      });
    }
    if (gateBackButton) {
      gateBackButton.addEventListener("click", () => {
        gateBackToComposer();
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
    // Slice 3 (04 Live run): the live card's "Stop run" button reuses the same
    // cancel path as the aside's cancel button.
    const liveStopButton = el("live-stop");
    if (liveStopButton) {
      liveStopButton.addEventListener("click", () => {
        cancelRun();
      });
    }
    // Slice 4a (05 Result): Copy + Export the result summary. Both read the
    // plain-text ``state.lastResultSummary`` built by ``renderResult`` (question
    // + verdict + agreement line) — textContent-safe, no HTML.
    const resultCopyButton = el("result-copy");
    if (resultCopyButton) {
      resultCopyButton.addEventListener("click", async () => {
        const summary = state.lastResultSummary;
        if (!summary) return;
        try {
          await navigator.clipboard.writeText(summary);
          resultCopyButton.dataset.copied = "true";
          resultCopyButton.textContent = "Copied";
          window.setTimeout(() => {
            delete resultCopyButton.dataset.copied;
            resultCopyButton.textContent = "Copy";
          }, 1500);
          toast({ message: "Result summary copied.", tone: "success" });
        } catch (_) {
          resultCopyButton.textContent = "Copy failed";
          window.setTimeout(() => {
            resultCopyButton.textContent = "Copy";
          }, 1500);
        }
      });
    }
    const resultExportButton = el("result-export");
    if (resultExportButton) {
      resultExportButton.addEventListener("click", () => {
        const summary = state.lastResultSummary;
        if (!summary) return;
        try {
          const blob = new Blob([summary], { type: "text/markdown;charset=utf-8" });
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = `quorum-${state.lastResultRunId || "run"}.md`;
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
          window.setTimeout(() => URL.revokeObjectURL(url), 0);
          toast({ message: "Result exported.", tone: "success" });
        } catch (_) {
          toast({ message: "Export failed. Copy the summary instead.", tone: "error" });
        }
      });
    }
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
    } catch (error) {
      handleError(error);
      setConnectionPill("error", "Disconnected");
    }
    // Pull the live readiness snapshot. ``/ready`` is
    // unauthenticated so this works even if the session bootstrap
    // were to fail. Best-effort: errors are logged to a toast
    // inside ``refreshReadiness`` and the page-load seed stays
    // visible. This runs outside the session try/catch so the
    // readiness banner always appears even when session init fails,
    // but is itself guarded so a throw in ``applyReadinessState``
    // can never reject ``boot()`` unhandled.
    try {
      await refreshReadiness();
    } catch (error) {
      handleError(error);
    }
  }

  boot();
})();
