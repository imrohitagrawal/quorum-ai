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

  // Per-model price index for the honest per-slot pre-run estimate (design-comp
  // parity, item 3). Built from the catalog island's ``input_price_per_1k`` /
  // ``output_price_per_1k`` (USD per 1K tokens). Models missing from the map
  // fall back to ``COST_MODEL`` defaults — exactly like the server's ``_price``.
  const catalogPriceIndex = new Map();
  for (const option of modelCatalog) {
    if (option && option.model_id) {
      catalogPriceIndex.set(option.model_id, {
        input: Number(option.input_price_per_1k),
        output: Number(option.output_price_per_1k),
      });
    }
  }

  const el = (id) => document.getElementById(id);
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) =>
    Array.from(root.querySelectorAll(selector));

  const errorRegion = el("error-region");
  const errorIcon = el("error-region-icon");
  const errorActag = el("error-region-actag");
  const errorTitle = el("error-region-title");
  const errorMessage = el("error-region-message");
  const errorDetail = el("error-region-detail");
  const errorActions = el("error-region-actions");
  const errorFooter = el("error-region-footer");
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
  // Composer (02) offers two paths to a run:
  //   ``estimate-run`` ("See the estimate →") ALWAYS opens the cost gate so
  //     the user can review the itemized estimate before approving — even a
  //     cheap ``allow``-band run (``estimateRun`` with ``autoProceed:false``).
  //   ``run-now`` ("Run now") starts straight away for the ``allow`` band and
  //     otherwise falls into the same gate (``autoProceed:true``); the money
  //     guardrail still pauses any ``require_confirmation``/``block`` run.
  // Ctrl/Cmd+Enter maps to the estimate-first path (see the keydown handler).
  const runNowButton = el("run-now");
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
  const gateBlockNote = el("cost-gate-block-note");
  const gateBlockFooter = el("cost-gate-block-footer");
  const gateBandLabel = el("cost-review-band-label");
  const gateCard = el("cost-review-card");
  const gateConfirmButton = el("gate-confirm");
  const gateBackButton = el("gate-back");
  const gateBlockModelsButton = el("gate-block-models");
  const gateBlockShortenButton = el("gate-block-shorten");
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
    // Slice 5 (06 Transcript): the last terminal poll result, captured in the
    // pollRun terminal branch alongside ``renderResult``. The transcript view
    // (an audit drill-down of opening positions + round-level critiques) is
    // rendered from this snapshot on demand. ``null`` until a run completes;
    // the transcript link + ``renderTranscript`` both guard the null.
    lastResult: null,
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
    // Clear the landing's transient state on EVERY view change so it never
    // persists across a round-trip: the empty-submit error (which used to
    // survive a How-it-works round-trip) AND the one-shot transition note (shown
    // on page A during the hand-off, then left behind once we navigate away).
    const landingErr = el("landing-query-error");
    if (landingErr) landingErr.hidden = true;
    const landingRunbarEl = qs(".landing-runbar");
    if (landingRunbarEl) delete landingRunbarEl.dataset.invalid;
    const landingQ = el("landing-query");
    if (landingQ) landingQ.setAttribute("aria-invalid", "false");
    const landingNote = el("landing-handoff-note");
    if (landingNote) landingNote.hidden = true;
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
    AUTH_REQUIRED: "Start a session to run a query",
    SESSION_EXPIRED: "Session expired",
    CSRF_INVALID: "Security check failed",
    INVALID_MODEL_SLOT: "One model slot needs a fix",
    SAFETY_ACK_REQUIRED: "Acknowledgement required",
    VALIDATION_ERROR: "Please check the form",
    COST_CONFIRMATION_REQUIRED: "Cost confirmation required",
    COST_LIMIT_EXCEEDED: "Over the hard cap — this run won't start",
    ACTIVE_QUERY_EXISTS: "You already have a run in progress",
    QUERY_RUN_NOT_FOUND: "You don't have access to this",
    QUERY_TOO_LONG: "Question is too long",
    QUERY_REQUIRED: "Question is required",
    NETWORK_UNREACHABLE: "Can't reach the server",
    RUN_FAILED: "One model didn't finish",
    TIMEOUT: "Run timed out",
  };

  // Some error codes have a CTA the user can take. Each entry has a
  // label + an onClick callback. We render them in the error banner.
  // Slice 6 (07 edge states): only actions the backend can ACTUALLY
  // perform are wired here (see ``edgeStateFromError`` for the
  // per-state builders). No fabricated per-step retry / "continue with
  // N models" buttons — there is no backend endpoint for either.
  const ERROR_ACTIONS = {
    SESSION_EXPIRED: [{ label: "Refresh session", action: () => location.reload() }],
    CSRF_INVALID: [{ label: "Refresh session", action: () => location.reload() }],
  };

  // Slice 6 (07 edge states): the error banner doubles as the seven
  // first-class honest edge cards. ``showError`` accepts optional
  // ``acTag`` (the "… · AC-0NN" pill), ``severity`` (error / warning /
  // info / neutral), ``detailRows`` (an itemized key→value block), and
  // ``footer`` (a mono correlation/ID line). Every field is server-data
  // driven at the call site — nothing here fabricates provider status,
  // slot suggestions, or "why" reasons.
  function showError({
    code,
    message,
    hint,
    fieldErrors,
    acTag,
    severity,
    detailRows,
    footer,
    actions,
  } = {}) {
    const title = (code && ERROR_TITLES[code]) || "Something went wrong";
    const sev = severity || "error";
    errorRegion.dataset.severity = sev;
    if (errorIcon) {
      errorIcon.textContent =
        sev === "info" || sev === "neutral" ? "i" : "!";
    }
    if (errorActag) {
      if (acTag) {
        errorActag.textContent = acTag;
        errorActag.hidden = false;
      } else {
        errorActag.textContent = "";
        errorActag.hidden = true;
      }
    }
    errorTitle.textContent = title;
    errorMessage.textContent = message || "An unexpected error occurred. Please try again.";
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
    // Itemized detail block (failed step, bad slot id, hard cap, …).
    if (errorDetail) {
      errorDetail.replaceChildren();
      const rows = Array.isArray(detailRows) ? detailRows : [];
      if (rows.length) {
        for (const row of rows) {
          const wrap = document.createElement("div");
          wrap.className = "status-banner-detail-row";
          const dt = document.createElement("dt");
          dt.textContent = row.label;
          const dd = document.createElement("dd");
          dd.textContent = row.value;
          if (row.mono) dd.classList.add("mono");
          if (row.tone) dd.dataset.tone = row.tone;
          // Any sub-line belongs INSIDE the <dd> (valid <dl> content model);
          // a bare <div> child of <dl> is invalid and confuses some AT.
          if (row.sub) {
            const sub = document.createElement("div");
            sub.className = "status-banner-detail-sub";
            sub.textContent = row.sub;
            dd.appendChild(sub);
          }
          wrap.append(dt, dd);
          errorDetail.appendChild(wrap);
        }
        errorDetail.hidden = false;
      } else {
        errorDetail.hidden = true;
      }
    }
    // Action buttons. Prefer explicit per-call ``actions``; otherwise
    // fall back to the static registry. Each action may be sync or async.
    errorActions.replaceChildren();
    const resolvedActions =
      (Array.isArray(actions) && actions.length
        ? actions
        : (code && ERROR_ACTIONS[code]) || []);
    resolvedActions.forEach(({ label, action, primary }, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = primary
        ? "button button-primary button-compact"
        : "button button-secondary button-compact";
      button.textContent = label;
      button.addEventListener("click", () => {
        try {
          const maybePromise = action();
          if (maybePromise && typeof maybePromise.catch === "function") {
            maybePromise.catch((err) => {
              toast({
                message: (err && err.message) || "That action could not complete.",
                tone: "error",
                timeout: 6000,
              });
            });
          }
        } catch (err) {
          toast({
            message: (err && err.message) || "That action could not complete.",
            tone: "error",
            timeout: 6000,
          });
        }
      });
      errorActions.appendChild(button);
    });
    // Mono correlation / ID footer.
    if (errorFooter) {
      if (footer) {
        errorFooter.textContent = footer;
        errorFooter.hidden = false;
      } else {
        errorFooter.textContent = "";
        errorFooter.hidden = true;
      }
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
    errorRegion.dataset.severity = "error";
    errorTitle.textContent = "";
    errorMessage.textContent = "";
    errorActions.replaceChildren();
    if (errorActag) {
      errorActag.textContent = "";
      errorActag.hidden = true;
    }
    if (errorDetail) {
      errorDetail.replaceChildren();
      errorDetail.hidden = true;
    }
    if (errorFooter) {
      errorFooter.textContent = "";
      errorFooter.hidden = true;
    }
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

  // Design-comp parity (item 2): the connected session pill mirrors the comp's
  // "Session active · provider configured" wording — but HONESTLY. The comp
  // depicts the live-provider happy path; we only claim "provider configured"
  // when the seeded readiness probe reports live execution. When the process is
  // degraded to local simulation (no provider key / live execution disabled) we
  // say so plainly rather than overstating capability.
  function connectedPillLabel() {
    const readiness = window.LIVE_READINESS;
    const live = readiness && readiness.state === "live";
    return live
      ? "Session active · provider configured"
      : "Session active · local simulation";
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
    constructor({ status, code, message, slotErrors, fieldErrors, partial, correlationId }) {
      super(message || STATUS_COPY[status] || "Unexpected error");
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.slotErrors = slotErrors;
      this.fieldErrors = fieldErrors;
      this.partial = partial;
      // Slice 6 (07 edge states): surface a server correlation_id on the
      // error when the envelope carries one, so honest edge states can
      // quote it in their footer. Never invented — undefined when absent.
      this.correlationId = correlationId;
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
        correlationId: (detail && detail.correlation_id) || (payload && payload.correlation_id) || undefined,
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
    if (entry) {
      const label = entry.label;
      const short = label.includes(":") ? label.slice(label.indexOf(":") + 1).trim() : label;
      return short || modelId;
    }
    // Not in the catalog (offline / drifted id): derive a friendly label from
    // the ``vendor/model`` slug rather than leaking the raw slug into the UI.
    // Purely presentational — no data is invented.
    return prettifyModelSlug(modelId);
  }

  // "deepseek/deepseek-v3.1" -> "Deepseek v3.1". Strips the vendor prefix,
  // turns separators into spaces, and title-cases alpha words while leaving
  // version-y tokens that contain a digit (v3.1, 4o, 2.5) untouched.
  function prettifyModelSlug(modelId) {
    const raw = String(modelId || "").trim();
    if (!raw) return "";
    const tail = raw.includes("/") ? raw.slice(raw.indexOf("/") + 1) : raw;
    const words = tail.replace(/[-_]+/g, " ").split(/\s+/).filter(Boolean);
    if (!words.length) return raw;
    return words
      .map((w) => (/[0-9]/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
      .join(" ");
  }

  // Avatar initial: first letter of the display name, uppercased.
  function avatarInitialForModel(modelId) {
    const name = displayNameForModel(modelId).trim();
    return (name[0] || "?").toUpperCase();
  }

  // Map a model id to its vendor key for the per-model avatar tint. Derived
  // from the ``vendor/model`` id prefix; unknown vendors fall back to the
  // neutral ink tint. Purely presentational — never affects run behaviour.
  function vendorForModel(modelId) {
    const prefix = String(modelId || "").split("/")[0].toLowerCase();
    if (prefix === "openai") return "openai";
    if (prefix === "anthropic") return "anthropic";
    if (prefix === "google") return "google";
    if (prefix === "deepseek") return "deepseek";
    if (prefix === "meta-llama" || prefix === "meta") return "meta";
    if (prefix === "mistralai" || prefix === "mistral") return "mistral";
    return "generic";
  }

  // Per-slot estimate label. Returns a mono "~$0.034" once an estimate
  // exists for this slot position, otherwise an em-dash placeholder.
  // Keyed by slot index (not model_id) so two slots with the same model
  // each show their own positional estimate.
  //
  // Honesty: a paid model must NEVER read "$0.000". For a positive estimate
  // that rounds below the 3-decimal display resolution (very short queries),
  // show "<$0.001" rather than "$0.000" (which would claim the model is free).
  function perModelEstimateText(slotIndex) {
    const usd = Array.isArray(state.perModelEstimates)
      ? state.perModelEstimates[slotIndex]
      : undefined;
    if (usd === undefined || usd === null) return "—";
    const num = Number(usd);
    if (!Number.isFinite(num) || num <= 0) return "—";
    const rounded = num.toFixed(3);
    return rounded === "0.000" ? "<$0.001" : `~$${rounded}`;
  }

  // Honest per-slot pre-run cost estimate (design-comp parity, item 3).
  //
  // Mirrors the server's per-slot ``by_model`` row EXACTLY
  // (``CostEstimationService._estimate_breakdown``, issue #16): each row is that
  // slot's own initial-answer charge — ``input × prompt_tokens + output ×
  // output_tokens`` — where the prompt is the fixed system-prompt overhead plus
  // the injected web-search context plus the query, and the output is a floor
  // that grows modestly with query length. The debate + synthesis calls are a
  // SEPARATE by_model row (server-only, on dedicated models) that the client
  // renders from the server breakdown, not from these scalars — so this
  // function prices only the four initial answers. Prices come from the catalog
  // island; the scalars come from ``window.COST_MODEL`` (single source of
  // truth, no hard-coded figures). The parity e2e suite cross-checks this
  // against the real ``/v1/query-runs/estimate`` by_model rows, so any drift is
  // caught. Returns one USD number per slot, or ``null`` when there is no query.
  function computePerSlotEstimatesUsd(modelIds, queryText, searchFlags) {
    const cm = window.COST_MODEL;
    const chars = (queryText || "").length;
    if (!cm || chars === 0) return modelIds.map(() => null);

    const charsPerToken = Number(cm.chars_per_token);
    const systemTokens = Number(cm.system_prompt_tokens);
    const searchTokens = Number(cm.web_search_context_tokens);
    const searchRequestFee = Number(cm.web_search_request_fee_usd) || 0;
    const initialOutputTokens = Number(cm.initial_output_tokens);
    const outputPerQueryToken = Number(cm.output_tokens_per_query_token);
    const defaultInput = Number(cm.default_input_price_per_1k);
    const defaultOutput = Number(cm.default_output_price_per_1k);

    const priceFor = (modelId) =>
      catalogPriceIndex.get(modelId) || { input: defaultInput, output: defaultOutput };

    const queryTokens = chars / charsPerToken;
    const outputTokens = initialOutputTokens + outputPerQueryToken * queryTokens;

    // Per-slot search flag. The composer today searches every slot (the server
    // default ``ModelSlot.search=True`` when the estimate omits ``slot_search``),
    // so ``searchFlags`` defaults to all-ON — but keying off it per slot means
    // this stays exact if a per-slot search toggle ever ships (issue #20). A
    // searching slot's prompt carries the injected web-search context AND the
    // flat per-request web-search plugin fee (issue #18); a non-searching slot
    // pays neither. Both terms mirror the server's ``_estimate_from_slots``.
    const searchOn = (i) => (searchFlags ? !!searchFlags[i] : true);

    return modelIds.map((modelId, i) => {
      const price = priceFor(modelId);
      const promptTokens = systemTokens + (searchOn(i) ? searchTokens : 0) + queryTokens;
      const fee = searchOn(i) ? searchRequestFee : 0;
      return (
        price.input * (promptTokens / 1000) + price.output * (outputTokens / 1000) + fee
      );
    });
  }

  // Recompute the pre-run per-slot estimates from the current query + model
  // selection and paint them onto the slot cards' estimate cells. Updates only
  // the ``.model-slot-estimate`` text (never rebuilds the cards) so a focused
  // ``<select>`` or the user's typing is never disrupted. A live estimate
  // response later overwrites ``state.perModelEstimates`` with the authoritative
  // server figures (see ``estimateRun``); this owns the composer pre-run view.
  function updatePerSlotEstimates() {
    if (!modelInputs) return;
    const modelIds = getModelIds();
    state.perModelEstimates = computePerSlotEstimatesUsd(
      modelIds,
      queryTextarea ? queryTextarea.value : "",
    );
    const cells = modelInputs.querySelectorAll(".model-slot-estimate");
    cells.forEach((cell, index) => {
      cell.textContent = perModelEstimateText(index);
    });
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
      // Per-model vendor tint (design parity): the avatar carries the vendor's
      // brand colour pair (see .model-slot-avatar[data-vendor=…] in app.css).
      card.dataset.vendor = vendorForModel(modelId);

      const avatar = document.createElement("span");
      avatar.className = "model-slot-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.dataset.vendor = vendorForModel(modelId);
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

  // Monotonic clock for the elapsed ticker. ``performance.now()`` never steps
  // backward, unlike ``Date.now()`` which an NTP correction / manual wall-clock
  // change can move — so the readout stays monotonic across a system clock step,
  // not only against server-reported skew (#29). Falls back to ``Date.now()``
  // only where ``performance`` is unavailable. All stamp writes AND drift reads
  // MUST use this same clock so ``now - stamp`` is always a real elapsed delta.
  function nowMs() {
    return typeof performance !== "undefined" && performance.now
      ? performance.now()
      : Date.now();
  }

  function tickLiveElapsed() {
    const elapsedEl = el("live-elapsed");
    if (!elapsedEl) return;
    const shown = state.liveElapsedBaseMs + (nowMs() - state.liveElapsedStamp);
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
    const body = document.createElement("div");
    body.className = "live-round-body";
    setProse(body, round.critique_text);
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
      // Label it "Run ID" (not a bare "run …") so the value reads as a
      // meaningful, quotable handle rather than opaque text.
      corr.textContent = corrId ? `Run ID ${corrId}` : "";
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
    // Elapsed already projected on the local clock from the last accepted base.
    // Used as the monotonic floor: the readout must never tick BELOW this. (#29)
    const projectedElapsedMs = state.liveElapsedStamp
      ? state.liveElapsedBaseMs + (nowMs() - state.liveElapsedStamp)
      : 0;
    if (isTerminal) {
      // Freeze at the final elapsed, clamped so the frozen value never snaps
      // below what the running ticker already displayed.
      const serverFinal = elapsedMs != null ? elapsedMs : projectedElapsedMs;
      freezeLiveElapsed(Math.max(serverFinal, projectedElapsedMs));
    } else {
      if (elapsedMs != null) {
        // MONOTONIC CLAMP (#29): a poll reporting a LOWER server elapsed
        // (clock skew / out-of-order poll) must not rewind the display. Clamp
        // the new base UP to what we've already shown, then re-anchor the stamp
        // so the ~1s ticker keeps advancing smoothly from there.
        state.liveElapsedBaseMs = Math.max(elapsedMs, projectedElapsedMs);
        state.liveElapsedStamp = nowMs();
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

  // UTC wall-clock only, e.g. "09:41:44 UTC" — used by the run-receipt
  // Started/Finished rows. Accepts a Date or an ISO string; guards a
  // missing/invalid value and any ICU rejection.
  function formatClockUtc(dateOrRaw) {
    if (!dateOrRaw) return "";
    const date = dateOrRaw instanceof Date ? dateOrRaw : new Date(dateOrRaw);
    if (Number.isNaN(date.getTime())) return "";
    try {
      const t = new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: "UTC",
      }).format(date);
      return `${t} UTC`;
    } catch (_) {
      return "";
    }
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
    if (caption) card.appendChild(setInlineProse(mkEl("div", "result-trust-caption"), caption));
    return card;
  }

  // Populate the result view from a TERMINAL poll result. Called ONCE at the
  // terminal transition (never per 750ms poll), so no aria-live spam. Every
  // nested field is guarded. The green treatment is GATED behind
  // ``isConsensus`` (AC-019 "no false consensus").
  // #26: surface a degraded/simulated banner on the PRIMARY result view. A
  // production run whose live provider is unavailable silently falls back to
  // local simulation (or the fallback-search stub); the response marks that via
  // ``live_count``/``local_count``/``demo_mode``, but the result view rendered
  // the verdict/synthesis as if real. This makes the fallback visible so
  // simulated output can never be mistaken for a real model panel. Shown
  // whenever fewer than all answers were live (any local/fallback answer).
  function renderResultDegraded(result) {
    const banner = el("result-degraded");
    if (!banner) return;
    const liveCount = Number.isFinite(result.live_count) ? result.live_count : null;
    const localCount = Number.isFinite(result.local_count) ? result.local_count : null;
    const total = liveCount != null && localCount != null ? liveCount + localCount : null;
    // Degraded when any answer was NOT live. Prefer the explicit counts; fall
    // back to the ``demo_mode`` boolean when counts are absent (older payload).
    const degraded =
      localCount != null ? localCount > 0 : result.demo_mode === true;
    if (!degraded) {
      banner.hidden = true;
      return;
    }
    const titleEl = el("result-degraded-title");
    const msgEl = el("result-degraded-message");
    const allLocal = liveCount === 0 || liveCount == null;
    if (titleEl) {
      titleEl.textContent = allLocal
        ? "Simulated result — not from real models"
        : "Partly simulated result";
    }
    if (msgEl) {
      msgEl.textContent = allLocal
        ? "Live execution was unavailable, so this whole result — the answers, the debate, and the synthesis — comes from Quorum's local simulation, not from GPT, Claude, Gemini, or Deepseek. Treat it as a demo, not a real model panel."
        : `Only ${liveCount} of ${total ?? 4} answers came from a live provider; the rest are from Quorum's local simulation. The verdict and synthesis below mix real and simulated output — do not rely on them as a fully live result.`;
    }
    banner.hidden = false;
  }

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
    // GREEN GATE (AC-019): the single source of truth is ``isConsensusResult``
    // (below), shared with the transcript view so the two green surfaces can
    // never drift out of lockstep.
    const isConsensus = isConsensusResult(result);

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

    renderResultDegraded(result);
    renderResultMeta(result, status, durationText);
    renderResultReceipt(result, res);
    renderVerdictBand(result, fs, { isConsensus, aligned, total, revisedCount, movements });
    renderTrustTriangle(result, res, fs, { isConsensus, aligned, total });
    renderResultPositions(res);
    renderResultSynthesis(fs, res);

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

  // Return the normalised URL string only when it is a real http(s) URL;
  // otherwise null. Untrusted source URLs must pass this before becoming an
  // anchor href (blocks javascript:/data:/vbscript: XSS vectors). Mirrors the
  // ``createSafeLink`` allow-list.
  function safeHttpUrl(url) {
    if (!url) return null;
    try {
      const parsed = new URL(String(url));
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        return parsed.toString();
      }
    } catch (_e) {
      /* not a parseable absolute URL → not linkable */
    }
    return null;
  }

  // Hostname (without www.) for a source chip label. Falls back to the raw
  // string if the URL will not parse.
  function sourceHost(url) {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch (_e) {
      return String(url || "").replace(/^https?:\/\//, "").split("/")[0] || "source";
    }
  }

  // Aggregate the unique cited sources across every model answer, in order of
  // first appearance. Real backend data only — never fabricated.
  function collectResultSources(res) {
    const answers = Array.isArray(res.model_answers) ? res.model_answers : [];
    const seen = new Set();
    const out = [];
    for (const a of answers) {
      for (const s of Array.isArray(a && a.sources) ? a.sources : []) {
        const url = s && s.url ? String(s.url) : "";
        const key = url || (s && s.title) || "";
        if (!key || seen.has(key)) continue;
        seen.add(key);
        out.push({ title: s && s.title ? String(s.title) : sourceHost(url), url });
      }
    }
    return out;
  }

  // The synthesis card (design comp screen 05). Labelled rows + attribution +
  // numbered source chips. Every value is a real backend value from
  // ``final_synthesis`` / the model answers; when the backend produced nothing
  // the card stays hidden rather than inventing content.
  function renderResultSynthesis(fs, res) {
    const host = el("result-synthesis");
    if (!host) return;
    const rows = fs
      ? [
          ["Consensus", fs.consensus, "consensus"],
          ["Disagreement", fs.disagreement, "disagreement"],
          ["Uncertainty", fs.uncertainty, "uncertainty"],
          ["Recommendation", fs.recommendation, "recommendation"],
        ].filter(([, v]) => v && String(v).trim())
      : [];
    const sources = collectResultSources(res || {});
    if (!rows.length && !sources.length) {
      host.hidden = true;
      host.replaceChildren();
      return;
    }
    host.hidden = false;

    const head = mkEl("div", "result-synthesis-head");
    head.appendChild(mkEl("h2", "result-synthesis-title", "The synthesis"));
    head.appendChild(
      mkEl(
        "span",
        "result-synthesis-attr",
        "from the four refined answers",
      ),
    );

    const grid = mkEl("div", "result-synthesis-grid");
    const addRow = (label, sectionKey, bodyContent) => {
      const row = mkEl("div", "result-synth-row");
      row.dataset.section = sectionKey;
      row.appendChild(mkEl("span", "result-synth-label", label));
      const body = mkEl("div", "result-synth-body");
      // A string is provider PROSE → render as block markdown; an element
      // (the Sources wrap) is appended as-is.
      if (typeof bodyContent === "string") {
        setProse(body, bodyContent);
      } else {
        body.appendChild(bodyContent);
      }
      row.appendChild(body);
      grid.appendChild(row);
    };
    for (const [label, value, key] of rows) {
      addRow(label, key, String(value).trim());
    }
    // SOURCES row — numbered chips built from the models' real citations, with
    // the synthesis' own ``source_support`` prose as a caption beneath them.
    // Shown when either exists so no real backend content is dropped.
    const sourceSupport = fs && fs.source_support ? String(fs.source_support).trim() : "";
    if (sources.length || sourceSupport) {
      const wrap = mkEl("div", "result-synth-sources");
      if (sources.length) {
        const chipRow = mkEl("div", "result-synth-source-chips");
        const shown = sources.slice(0, 3);
        shown.forEach((s, i) => {
          // SECURITY: source URLs come from external search providers (untrusted).
          // Only make the chip a link when the URL is http(s) — mirrors the
          // ``createSafeLink`` scheme allow-list so a ``javascript:`` URL can never
          // become a clickable anchor. Otherwise render a plain, non-link chip.
          const safe = safeHttpUrl(s.url);
          const chip = safe ? mkEl("a", "result-source-chip") : mkEl("span", "result-source-chip");
          if (safe) {
            chip.href = safe;
            chip.target = "_blank";
            chip.rel = "noopener noreferrer";
          }
          chip.appendChild(mkEl("span", "result-source-num", String(i + 1)));
          const host = sourceHost(s.url);
          const title = s.title && s.title !== host ? String(s.title) : "";
          // Combine host + title when both are meaningful; otherwise show
          // whichever exists (no "host · host", no leading " · " when a
          // non-http URL yields an empty host).
          const label = host && title ? `${host} · ${title}` : host || title || "source";
          chip.appendChild(mkEl("span", "result-source-label", label));
          chipRow.appendChild(chip);
        });
        if (sources.length > shown.length) {
          chipRow.appendChild(mkEl("span", "result-source-more", `+ ${sources.length - shown.length} more`));
        }
        wrap.appendChild(chipRow);
      }
      if (sourceSupport) {
        wrap.appendChild(setInlineProse(mkEl("p", "result-source-support"), sourceSupport));
      }
      addRow("Sources", "sources", wrap);
    }

    host.replaceChildren(head, grid);
  }

  // Fix 8: cached reference to the static "Run details" toggle. Once grabbed,
  // the node reference survives being detached from the DOM (when
  // ``renderResultMeta`` clears ``#result-meta``), so we can always re-append
  // the SAME element — with its click listener intact — on a re-render.
  let resultDetailsToggleNode = null;

  // The Run ID's support copy + tooltip text, shared verbatim by the result
  // header and the receipt so the two never drift.
  const RUN_ID_COPY_TITLE = "Copy run ID — quote it if you report a problem to support.";
  const RUN_ID_INFO_TEXT =
    "A unique audit handle for this run. Copy it and quote it if you report a " +
    "problem to support — it lets them pull up every log line for this exact " +
    "request. It is not a link and has no meaning outside support.";

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
      // A bare ``qr_…`` value is meaningless to a user on its own. Label it
      // "Run ID", make it click-to-copy, and attach a compact info icon that
      // explains what it is for — the aside's "Run controls" readout (which
      // carried this affordance) is hidden in the parity design, so the result
      // header is the only place the user sees the id.
      const runIdWrap = mkEl("span", "result-meta-runid");
      runIdWrap.appendChild(mkEl("span", "result-meta-runid-label", "Run ID"));
      const idValue = String(result.correlation_id);
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "mono result-meta-runid-copy";
      copyBtn.textContent = idValue;
      copyBtn.title = RUN_ID_COPY_TITLE;
      copyBtn.setAttribute("aria-label", `Copy run ID ${idValue}`);
      // Reuse the shared helper so the header copy stays in lockstep with the
      // receipt / aside / live-card buttons (success AND failure feedback,
      // visible + screen-reader).
      copyBtn.addEventListener("click", () => {
        copyRunIdToClipboard(copyBtn, idValue, RUN_ID_COPY_TITLE);
      });
      runIdWrap.appendChild(copyBtn);
      runIdWrap.appendChild(
        buildInfoIcon(RUN_ID_INFO_TEXT, { ariaLabel: "What is the run ID?", inline: true }),
      );
      meta.appendChild(runIdWrap);
      // Wire the freshly-created info icon into the shared tooltip system
      // (idempotent — keyed off ``data-info-wired``).
      initInfoIcons();
    }

    // Slice 4b: move the static "Run details" disclosure toggle into the meta
    // row (it lives in the HTML so its click listener is wired once; moving the
    // node keeps the listener). ``renderResultMeta`` cleared ``meta`` above,
    // which detaches the toggle on a re-render — after which
    // ``getElementById`` can no longer find it. Fix 8: use the cached node
    // reference (which survives detachment) so the toggle + listener always
    // return on every terminal render.
    if (!resultDetailsToggleNode) resultDetailsToggleNode = el("result-details-toggle");
    if (resultDetailsToggleNode) meta.appendChild(resultDetailsToggleNode);
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
      setProse(
        mkEl("div", "result-verdict-text"),
        recommendation,
        "No recommendation was recorded for this run.",
      ),
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
        setInlineProse(mkEl("span", "result-verdict-caveat"), String(fs.high_stakes_notice).trim()),
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

  // --- Slice 4b: run receipt + cost reconciliation -----------------------
  //
  // Friendly labels for the four pipeline stages. Keys mirror the backend
  // ``progress.stages[].stage`` vocabulary and ``CostLineByStage.stage``.
  const RECEIPT_STAGE_LABELS = {
    initial_answers: "Initial answers",
    debate_round_1: "Debate round 1",
    debate_round_2: "Debate round 2",
    synthesis: "Synthesis",
  };
  const RECEIPT_STAGE_SHORT = {
    initial_answers: "Initial",
    debate_round_1: "Round 1",
    debate_round_2: "Round 2",
    synthesis: "Synthesis",
  };
  const RECEIPT_PIPELINE_ORDER = [
    "initial_answers",
    "debate_round_1",
    "debate_round_2",
    "synthesis",
  ];

  // Map a backend stage state onto a completion marker. NOTE: the response
  // carries NO per-stage duration (``progress.stages[]`` is {stage,state,detail}
  // only), so the pipeline column renders completion STATE, never a fabricated
  // per-stage time. The mock's "8.2s / 11.4s" are mock-only and dropped.
  function receiptStageMarker(state) {
    switch (state) {
      case "completed":
        return { glyph: "✓", label: "Completed", tone: "done" };
      case "failed":
        return { glyph: "✕", label: "Failed", tone: "failed" };
      case "skipped":
        return { glyph: "–", label: "Skipped", tone: "skipped" };
      case "running":
        return { glyph: "…", label: "Running", tone: "running" };
      default:
        return { glyph: "·", label: "Pending", tone: "pending" };
    }
  }

  function buildReceiptTextRow(label, value, { mono = false } = {}) {
    const row = mkEl("div", "result-receipt-row");
    row.appendChild(mkEl("span", "result-receipt-label", label));
    row.appendChild(
      mkEl("span", mono ? "result-receipt-value mono" : "result-receipt-value", value),
    );
    return row;
  }

  // Copyable ID row (Run ID / internal reference). The ⧉ button carries the
  // value on its dataset; a single delegated click handler on ``#result-receipt``
  // (wired once in boot) reuses the shared ``copyRunIdToClipboard`` helper. When
  // ``infoText`` is given, a compact info icon is appended to the label so the
  // receipt explains the id the same way the result header does.
  function buildReceiptIdRow(label, value, idleTitle, infoText) {
    const row = mkEl("div", "result-receipt-row");
    const labelEl = mkEl("span", "result-receipt-label", label);
    if (infoText) {
      labelEl.appendChild(document.createTextNode(" "));
      labelEl.appendChild(
        buildInfoIcon(infoText, { ariaLabel: `What is the ${label}?`, inline: true }),
      );
    }
    row.appendChild(labelEl);
    const valWrap = mkEl("span", "result-receipt-id");
    valWrap.appendChild(mkEl("span", "mono", value));
    const copy = mkEl("button", "result-receipt-copy", "⧉");
    copy.type = "button";
    copy.dataset.copyValue = value;
    copy.dataset.idleTitle = idleTitle;
    copy.setAttribute("aria-label", idleTitle);
    copy.title = idleTitle;
    valWrap.appendChild(copy);
    row.appendChild(valWrap);
    return row;
  }

  // One "est → actual" money row. When ``actualUsd`` is not finite (no actual
  // breakdown) the actual side renders "—" — NEVER a fabricated number.
  function buildReceiptCostRow(label, estUsd, actualUsd, { total = false } = {}) {
    const row = mkEl(
      "div",
      total ? "result-receipt-row result-receipt-cost-total" : "result-receipt-row",
    );
    row.appendChild(mkEl("span", "result-receipt-label", label));
    const estText = Number.isFinite(estUsd) ? formatUsd(estUsd, { suffix: false }) : "—";
    const actText = Number.isFinite(actualUsd)
      ? formatUsd(actualUsd, { suffix: false })
      : "—";
    // Fix 6: the "→" is decorative (SR would read "rightwards arrow"). Hide it
    // and give SR a spoken "to" so the pair reads "$0.034 to $0.031".
    const valueEl = mkEl("span", "result-receipt-value mono");
    valueEl.appendChild(mkEl("span", null, estText));
    const arrow = mkEl("span", null, " → ");
    arrow.setAttribute("aria-hidden", "true");
    valueEl.appendChild(arrow);
    valueEl.appendChild(mkEl("span", "sr-only", "to"));
    valueEl.appendChild(mkEl("span", null, actText));
    row.appendChild(valueEl);
    return row;
  }

  // Cost reconciliation footer. delta = approved − actual.
  //  · no actual breakdown / missing actual → "Actual cost … pending" (no delta)
  //  · demo_mode OR actual ≈ approved       → "Matched estimate" (neutral)
  //  · actual < approved (real savings)     → "Under approval −$X" (ink, money)
  //  · actual > approved (real overage)     → "Over approval +$X" (ink)
  // Green is reserved for the verdict band; the delta is money, so it moves on
  // ink per the money-on-ink rule — never green (see report for the rationale).
  function buildReconciliationRow(result) {
    const row = mkEl("div", "result-receipt-row result-receipt-recon");
    const approved =
      result.cost_estimate && result.cost_estimate.estimated_cost_usd != null
        ? Number(result.cost_estimate.estimated_cost_usd)
        : NaN;
    const actual = Number(result.actual_cost_usd);
    const hasActual = result.actual_breakdown != null && Number.isFinite(actual);
    // ``cost_source`` marks whether the "actual" figure is measured provider
    // billing or the pre-run estimate standing in for it. Today the backend
    // only ever emits "estimated" (per-call usage capture is not yet plumbed),
    // so we must NOT present the est→actual delta as a real reconciliation —
    // that would imply the figure was checked against provider billing. A
    // "measured" source (future) flows through the delta branches below.
    const measured = result.cost_source === "measured";
    const label = mkEl("span", "result-receipt-recon-label");
    const value = mkEl("span", "result-receipt-recon-value mono");
    if (!hasActual || !Number.isFinite(approved)) {
      row.dataset.state = "pending";
      label.textContent = "Actual cost";
      value.textContent = "pending";
    } else if (!measured) {
      row.dataset.state = "estimated";
      label.textContent = "Actual cost (estimated)";
      value.textContent = formatUsd(actual, { suffix: false });
    } else {
      const delta = approved - actual;
      const eps = 0.0005;
      if (result.demo_mode || Math.abs(delta) <= eps) {
        row.dataset.state = "matched";
        label.textContent = "Matched estimate";
        value.textContent = formatUsd(actual, { suffix: false });
      } else if (delta > eps) {
        row.dataset.state = "under";
        label.textContent = "Under approval";
        value.textContent = `−${formatUsd(delta, { suffix: false })}`;
      } else {
        row.dataset.state = "over";
        label.textContent = "Over approval";
        value.textContent = `+${formatUsd(-delta, { suffix: false })}`;
      }
    }
    row.append(label, value);
    return row;
  }

  // Populate the collapsed run-receipt panel. Idempotent: clears + resets to
  // collapsed on every call. Every nested field is guarded; the actual columns
  // null-guard ``actual_breakdown`` and never fabricate an actual figure.
  function renderResultReceipt(result, res) {
    const receipt = el("result-receipt");
    if (!receipt) return;
    receipt.textContent = "";
    receipt.hidden = true;
    const toggle = el("result-details-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", "false");
      const caret = toggle.querySelector(".result-details-caret");
      if (caret) caret.textContent = "▾";
    }

    const est =
      result.cost_estimate && result.cost_estimate.breakdown
        ? result.cost_estimate.breakdown
        : null;
    const actual = result.actual_breakdown || null;
    const answers = Array.isArray(res.model_answers) ? res.model_answers : [];

    const grid = mkEl("div", "result-receipt-grid");

    // --- Col 1: Run receipt ------------------------------------------------
    const c1 = mkEl("div", "result-receipt-col");
    // Fix 7: label each receipt column as a semantic group so SR announces the
    // column's purpose (the kicker spans alone are non-semantic).
    c1.setAttribute("role", "group");
    c1.setAttribute("aria-label", "Run receipt");
    c1.appendChild(mkEl("span", "result-receipt-kicker", "Run receipt"));
    // ONE user-facing "Run ID" = the friendly ``qr_``/correlation form, matching
    // the result header and live-run card. The raw ``query_run_id`` (a UUID) is
    // the SAME id in another format (``correlation_id`` is ``"qr_" + uuid.hex``),
    // so surfacing it as a second row only added a competing ID-looking value with
    // no user benefit — it is intentionally NOT shown on the receipt. (Support can
    // still resolve the raw form from the friendly id server-side.)
    if (result.correlation_id) {
      c1.appendChild(
        buildReceiptIdRow(
          "Run ID",
          String(result.correlation_id),
          RUN_ID_COPY_TITLE,
          RUN_ID_INFO_TEXT,
        ),
      );
    }
    c1.appendChild(buildReceiptTextRow("Session", "Secure cookie"));

    const finishedDate = result.result_generated_at_utc
      ? new Date(result.result_generated_at_utc)
      : null;
    const finishedValid = finishedDate && !Number.isNaN(finishedDate.getTime());
    const elapsedMs = Number(result.elapsed_time_ms);
    if (finishedValid && Number.isFinite(elapsedMs) && elapsedMs > 0) {
      const startedClock = formatClockUtc(new Date(finishedDate.getTime() - elapsedMs));
      if (startedClock) {
        c1.appendChild(buildReceiptTextRow("Started", startedClock, { mono: true }));
      }
    }
    if (finishedValid) {
      const finishedClock = formatClockUtc(finishedDate);
      if (finishedClock) {
        c1.appendChild(buildReceiptTextRow("Finished", finishedClock, { mono: true }));
      }
    }

    // Search: "OpenRouter" plus "· Fallback search ×N" only when N>0 (N =
    // answers that fell back to the LOCAL search stub). We name what actually
    // ran: the fallback emits synthetic stub citations and never reaches a real
    // web-search provider (OQ-008 / DEBT-002), so naming one would be a
    // fabricated integration claim.
    const fallbackCount = answers.filter(
      (a) => a && (a.fallback_used === true || a.provider_path === "fallback_search"),
    ).length;
    c1.appendChild(
      buildReceiptTextRow(
        "Search",
        fallbackCount > 0
          ? `OpenRouter · Fallback search ×${fallbackCount}`
          : "OpenRouter",
      ),
    );
    c1.appendChild(
      mkEl(
        "p",
        "result-receipt-note",
        "Quote the run ID when you report an issue — support can pull every log line. Ephemeral: this receipt is gone when the session ends.",
      ),
    );
    grid.appendChild(c1);

    // --- Col 2: Cost by model · est → actual -------------------------------
    const c2 = mkEl("div", "result-receipt-col result-receipt-col-div");
    c2.setAttribute("role", "group");
    c2.setAttribute("aria-label", "Cost by model, estimate to actual");
    c2.appendChild(mkEl("span", "result-receipt-kicker", "Cost by model · est → actual"));
    if (est && Array.isArray(est.by_model) && est.by_model.length) {
      const actualByModel =
        actual && Array.isArray(actual.by_model) ? actual.by_model : null;
      est.by_model.forEach((line) => {
        // Fix 10: null-entry guard (parity with the positions loop).
        if (!line) return;
        // Fix 9: pair est→actual by model key, not array index, so a real
        // (reordered/partial) actual breakdown can never be misattributed.
        const key = line.model_id || line.display_name;
        let actUsd = NaN;
        if (actualByModel) {
          const match = actualByModel.find(
            (a) => a && (a.model_id || a.display_name) === key,
          );
          if (match) actUsd = Number(match.usd);
        }
        c2.appendChild(
          buildReceiptCostRow(
            line.display_name || line.model_id || "—",
            Number(line.usd),
            actUsd,
          ),
        );
      });
      c2.appendChild(
        buildReceiptCostRow(
          "Total",
          Number(est.total),
          actual ? Number(actual.total) : NaN,
          { total: true },
        ),
      );
    } else {
      c2.appendChild(
        mkEl("p", "result-receipt-note", "Itemized cost breakdown is not available for this run."),
      );
    }
    grid.appendChild(c2);

    // --- Col 3: Cost by stage · est → actual + reconciliation --------------
    const c3 = mkEl("div", "result-receipt-col result-receipt-col-div");
    c3.setAttribute("role", "group");
    c3.setAttribute("aria-label", "Cost by stage, estimate to actual");
    c3.appendChild(mkEl("span", "result-receipt-kicker", "Cost by stage · est → actual"));
    if (est && Array.isArray(est.by_stage) && est.by_stage.length) {
      const actualByStage =
        actual && Array.isArray(actual.by_stage) ? actual.by_stage : null;
      est.by_stage.forEach((line) => {
        // Fix 10: null-entry guard (parity with the positions loop).
        if (!line) return;
        // Fix 9: pair est→actual by stage key, not array index.
        let actUsd = NaN;
        if (actualByStage) {
          const match = actualByStage.find((a) => a && a.stage === line.stage);
          if (match) actUsd = Number(match.usd);
        }
        c3.appendChild(
          buildReceiptCostRow(
            RECEIPT_STAGE_SHORT[line.stage] || line.stage,
            Number(line.usd),
            actUsd,
          ),
        );
      });
    } else {
      c3.appendChild(
        mkEl("p", "result-receipt-note", "Itemized stage breakdown is not available for this run."),
      );
    }
    c3.appendChild(buildReconciliationRow(result));
    grid.appendChild(c3);

    // --- Col 4: Pipeline (completion states, NO fabricated durations) ------
    const c4 = mkEl("div", "result-receipt-col result-receipt-col-div");
    c4.setAttribute("role", "group");
    c4.setAttribute("aria-label", "Pipeline");
    c4.appendChild(mkEl("span", "result-receipt-kicker", "Pipeline"));
    const stages =
      result.progress && Array.isArray(result.progress.stages)
        ? result.progress.stages
        : [];
    const stateByStage = {};
    for (const s of stages) {
      if (s && s.stage) stateByStage[s.stage] = String(s.state || "");
    }
    let allCompleted = true;
    for (const key of RECEIPT_PIPELINE_ORDER) {
      const st = stateByStage[key];
      if (st !== "completed") allCompleted = false;
      const marker = receiptStageMarker(st);
      const row = mkEl("div", "result-receipt-row");
      const lbl = mkEl("span", "result-receipt-stage");
      const glyph = mkEl("span", "result-receipt-stage-glyph", marker.glyph);
      glyph.dataset.tone = marker.tone;
      glyph.setAttribute("aria-hidden", "true");
      lbl.append(glyph, mkEl("span", null, RECEIPT_STAGE_LABELS[key]));
      row.append(lbl, mkEl("span", "result-receipt-stage-state", marker.label));
      c4.appendChild(row);
    }
    // The ONLY real timing the response exposes is the whole-run elapsed.
    if (Number.isFinite(elapsedMs) && elapsedMs > 0) {
      const totalRow = mkEl("div", "result-receipt-row result-receipt-cost-total");
      totalRow.append(
        mkEl("span", "result-receipt-label", "Total"),
        mkEl("span", "result-receipt-value mono", formatDuration(elapsedMs)),
      );
      c4.appendChild(totalRow);
    }
    const failedSteps = Array.isArray(result.failed_steps) ? result.failed_steps : [];
    if (allCompleted && failedSteps.length === 0) {
      c4.appendChild(
        mkEl("p", "result-receipt-note", "All stages completed."),
      );
    }
    grid.appendChild(c4);

    receipt.appendChild(grid);
    // Wire the receipt's ID info icons into the shared tooltip system
    // (idempotent — keyed off ``data-info-wired``).
    initInfoIcons();
  }

  // One position <td>. ``data-label`` carries the column name so the mobile
  // stacked layout can re-label each cell via CSS ``::before``.
  function mkPositionsCell(label, text) {
    const cell = mkEl("td", "result-positions-cell");
    cell.dataset.label = label;
    if (text) cell.appendChild(setInlineProse(mkEl("span", "result-pos-text"), String(text)));
    return cell;
  }

  // "How positions moved" table. The caption is ALWAYS rendered (not demo-gated)
  // because the per-model movement is INFERRED from opening answers + panel
  // consensus in both demo and live modes. Empty movements → hide the section.
  //
  // Fix 4: rendered as a NATIVE <table> so screen readers associate each model
  // with its cells. The model is a ``<th scope="row">``; each phase is a
  // ``<td>``; the column headers are ``<th scope="col">``. The table is
  // labelled (the "Inferred from…" caption stays a separate visible element in
  // the head) and wrapped in an ``overflow-x:auto`` scroller so it never pushes
  // the page body sideways.
  function renderResultPositions(res) {
    const container = el("result-positions");
    if (!container) return;
    container.textContent = "";
    const movements = Array.isArray(res.position_movements)
      ? res.position_movements
      : [];
    if (movements.length === 0) {
      container.hidden = true;
      return;
    }
    container.hidden = false;

    const head = mkEl("div", "result-positions-head");
    head.appendChild(mkEl("span", "result-positions-title", "How positions moved"));
    head.appendChild(
      mkEl(
        "span",
        "result-positions-caption",
        "Inferred from opening answers and panel consensus — not a quoted transcript.",
      ),
    );
    container.appendChild(head);

    const scroller = mkEl("div", "result-positions-scroll");
    const table = mkEl("table", "result-positions-table");
    table.setAttribute("aria-label", "How positions moved");

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const text of ["Model", "Opening", "After round 1", "Final"]) {
      const th = mkEl("th", "result-positions-colhead", text);
      th.setAttribute("scope", "col");
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const m of movements) {
      if (!m) continue;
      const row = mkEl("tr", "result-positions-row");

      const name = String(m.display_name || m.model_id || "Model");
      const modelCell = mkEl("th", "result-positions-cell result-pos-model");
      modelCell.setAttribute("scope", "row");
      const avatar = mkEl("span", "result-pos-avatar", name.trim().charAt(0).toUpperCase() || "?");
      avatar.setAttribute("aria-hidden", "true");
      // Carry the SAME per-vendor tint the composer slots and transcript openings
      // use, so a model keeps its colour identity across every surface (two "G"
      // initials — GPT and Gemini — are otherwise indistinguishable here).
      if (m.model_id) avatar.dataset.vendor = vendorForModel(m.model_id);
      modelCell.append(avatar, mkEl("span", "result-pos-name", name));
      row.appendChild(modelCell);

      row.appendChild(mkPositionsCell("Opening", m.opening));
      row.appendChild(mkPositionsCell("After round 1", m.after_round_1));

      const finalCell = mkEl("td", "result-positions-cell");
      finalCell.dataset.label = "Final";
      if (m.final) finalCell.appendChild(setInlineProse(mkEl("span", "result-pos-text"), String(m.final)));
      if (m.revised === true) {
        // Fix 12: this "✓ Revised" chip is GREEN ON PURPOSE — it is the
        // sanctioned agreement/revision semantic (the model changed its
        // position) and is pixel-mandated by the mock. Do NOT retint it to a
        // neutral tone; unlike the done glyph / copied-state, green here maps
        // to a real, verified signal.
        const chip = mkEl("span", "result-pos-chip", "✓ Revised");
        const note = m.revision_note ? String(m.revision_note) : "";
        if (note) {
          chip.title = note;
          finalCell.appendChild(chip);
          finalCell.appendChild(mkEl("span", "result-pos-note", note));
        } else {
          finalCell.appendChild(chip);
        }
      }
      row.appendChild(finalCell);
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    scroller.appendChild(table);
    container.appendChild(scroller);
  }

  function focusResultHeading() {
    if (!resultHeading) return;
    resultHeading.focus({ preventScroll: true });
    resultHeading.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
  }

  // ---------------------------------------------------------------------------
  // Slice 5 (06 Transcript) — the debate audit trail
  // ---------------------------------------------------------------------------
  //
  // The transcript is the ONLY drill-down: real per-model OPENING positions
  // (from ``model_answers``) followed by the ROUND-LEVEL debate critiques
  // (from ``debate_outputs``). HONESTY (non-negotiable): the backend records
  // ONE ``critique_text`` per round with NO per-model attribution — there is
  // no "who challenged whom", no per-model stance/concession, no line-by-line
  // transcript. This view therefore renders round-level critiques only, with an
  // explicit caption saying so, and NEVER fabricates the mock's per-model
  // exchange cards. GREEN RULE: the status chip + footer go green ONLY on real,
  // complete consensus (the same gate as the verdict band); otherwise neutral.

  // The consensus gate — the SINGLE SOURCE OF TRUTH for the AC-019 "no false
  // consensus" green rule, shared by both ``renderResult`` (verdict band /
  // trust triangle) and ``renderTranscript`` (status chip / footer) so the two
  // green surfaces can never drift apart. Green requires: a real agreement
  // signal, every model aligned, the synthesis explicitly NOT preserving a
  // false consensus, no failed steps, and a ``completed`` status.
  function isConsensusResult(result) {
    const res = (result && result.result) || {};
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
    const failedSteps = Array.isArray(result && result.failed_steps)
      ? result.failed_steps
      : [];
    return Boolean(
      agreement &&
        total > 0 &&
        aligned === total &&
        fs &&
        fs.quality_checks &&
        fs.quality_checks.false_consensus_preserved === false &&
        failedSteps.length === 0 &&
        String(result && result.status) === "completed",
    );
  }

  // Honest provider tag for an opening position. OPENROUTER_SEARCH = a live
  // provider call; FALLBACK_SEARCH / LOCAL_SIMULATION are NOT live (the answer
  // came from Quorum's local helpers) so they are never labelled "live".
  function transcriptProviderTag(answer) {
    const path = String((answer && answer.provider_path) || "");
    // Even on the live path, honor an explicit ``fallback_used`` flag — never
    // claim "live" for an answer the server marked as a fallback.
    if (path === "openrouter_search" && !(answer && answer.fallback_used)) {
      return { text: "live", fallback: false };
    }
    if (path === "openrouter_search") return { text: "fallback", fallback: true };
    if (path === "fallback_search") return { text: "fallback", fallback: true };
    if (path === "local_simulation") return { text: "simulated", fallback: true };
    // Unknown path: stay conservative and never claim "live".
    return { text: answer && answer.fallback_used ? "fallback" : "unverified", fallback: true };
  }

  // A single opening-position card — REAL per-model data: display name, a
  // non-fallback source count, the honest provider tag, and the model's
  // ``answer_text`` (its opening answer), all via textContent.
  function buildTranscriptOpening(answer) {
    const card = mkEl("article", "transcript-opening");
    const head = mkEl("div", "transcript-opening-head");
    // Prefer the friendly display name (matches the positions table + slots);
    // fall back to catalog resolution, then the raw id.
    const modelId = (answer && answer.model_id) || "";
    const name = String(
      (answer && answer.display_name) || displayNameForModel(modelId) || modelId || "Model",
    );
    const avatar = mkEl(
      "span",
      "transcript-opening-avatar",
      name.trim().charAt(0).toUpperCase() || "?",
    );
    avatar.setAttribute("aria-hidden", "true");
    avatar.dataset.vendor = vendorForModel(modelId);
    head.append(avatar, mkEl("span", "transcript-opening-name", name));

    const sources = Array.isArray(answer && answer.sources) ? answer.sources : [];
    const primarySrc = sources.filter((s) => s && s.is_fallback !== true).length;
    const tagInfo = transcriptProviderTag(answer);
    const tag = mkEl(
      "span",
      "transcript-opening-tag mono",
      `${tagInfo.text} · ${primarySrc} src`,
    );
    if (tagInfo.fallback) tag.dataset.fallback = "true";
    head.appendChild(tag);
    card.appendChild(head);

    const body = mkEl("div", "transcript-opening-body");
    const text = String((answer && answer.answer_text) || "").trim();
    setProse(body, text, "This model did not return an opening answer.");
    card.appendChild(body);
    return card;
  }

  // A round-level critique block. Header = "Round N" + focus areas; body = the
  // round's ``critique_text``. NO per-model cards/attribution are invented.
  function buildTranscriptRound(round) {
    const card = mkEl("article", "transcript-round");
    const head = mkEl("div", "transcript-round-head");
    head.appendChild(
      mkEl("span", "transcript-round-pill", `Round ${round.round_number}`),
    );
    const focusAreas = Array.isArray(round.focus_areas)
      ? round.focus_areas.filter(Boolean)
      : [];
    if (focusAreas.length) {
      head.appendChild(
        mkEl("span", "transcript-round-focus", `Focus: ${focusAreas.join(", ")}`),
      );
    }
    card.appendChild(head);

    const body = mkEl("div", "transcript-round-body");
    const text = String(round.critique_text || "").trim();
    setProse(body, text, "This round did not produce a critique summary.");
    card.appendChild(body);
    return card;
  }

  // Render the transcript view from a terminal result snapshot
  // (``state.lastResult``). Guards a null/empty snapshot. Called just before
  // ``setView("transcript")``.
  function renderTranscript(result) {
    if (!result) return;
    const res = result.result || {};
    const modelAnswers = Array.isArray(res.model_answers) ? res.model_answers : [];
    const debate = Array.isArray(res.debate_outputs) ? res.debate_outputs : [];
    const isConsensus = isConsensusResult(result);

    // Question echo (serif h1) — the submitted question, never the live
    // textarea (a rehydrated run holds unrelated in-progress text).
    const heading = el("transcript-heading");
    if (heading) heading.textContent = state.liveQueryText || "The debate";

    // Meta line: round count + model count + optional debate-stage ESTIMATE.
    const metaEl = el("transcript-meta");
    if (metaEl) {
      const parts = [];
      parts.push(`${debate.length} round${debate.length === 1 ? "" : "s"}`);
      parts.push(`${modelAnswers.length} model${modelAnswers.length === 1 ? "" : "s"}`);
      const byStage =
        result.cost_estimate &&
        result.cost_estimate.breakdown &&
        Array.isArray(result.cost_estimate.breakdown.by_stage)
          ? result.cost_estimate.breakdown.by_stage
          : [];
      let debateUsd = 0;
      let haveDebate = false;
      for (const line of byStage) {
        if (
          line &&
          (line.stage === "debate_round_1" || line.stage === "debate_round_2")
        ) {
          const v = Number(line.usd);
          if (Number.isFinite(v)) {
            debateUsd += v;
            haveDebate = true;
          }
        }
      }
      if (haveDebate) {
        parts.push(`debate ~${formatUsd(debateUsd, { suffix: false })} est.`);
      }
      metaEl.textContent = parts.join(" · ");
    }

    // Status chip — GREEN only on real consensus (avoids the banned "converged"
    // wording; "Consensus reached" is the sanctioned green status word).
    const statusEl = el("transcript-status");
    if (statusEl) {
      statusEl.textContent = "";
      statusEl.dataset.consensus = isConsensus ? "true" : "false";
      const dot = mkEl("span", "transcript-status-dot");
      dot.setAttribute("aria-hidden", "true");
      statusEl.append(
        dot,
        mkEl("span", null, isConsensus ? "Consensus reached" : "Panel divided"),
      );
    }

    // Opening positions — REAL per-model data.
    const openings = el("transcript-openings");
    if (openings) {
      openings.textContent = "";
      if (modelAnswers.length === 0) {
        openings.appendChild(
          mkEl("p", "transcript-empty muted", "No opening positions were recorded for this run."),
        );
      } else {
        for (const answer of modelAnswers) {
          openings.appendChild(buildTranscriptOpening(answer));
        }
      }
    }

    // The debate — round-level critiques only.
    const rounds = el("transcript-rounds");
    if (rounds) {
      rounds.textContent = "";
      if (debate.length === 0) {
        rounds.appendChild(
          mkEl("p", "transcript-empty muted", "No debate rounds were recorded for this run."),
        );
      } else {
        for (const round of debate) {
          rounds.appendChild(buildTranscriptRound(round));
        }
      }
    }

    // Footer link — green treatment ONLY on real consensus.
    const footer = el("transcript-footer-link");
    if (footer) footer.dataset.consensus = isConsensus ? "true" : "false";
  }

  function focusTranscriptHeading() {
    const heading = el("transcript-heading");
    if (!heading) return;
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
  }

  // Open the transcript drill-down from the last terminal result. If no
  // snapshot exists (defensive — the link is only shown on a completed run),
  // toast and stay put rather than navigating to an empty view.
  function openTranscript() {
    if (!state.lastResult) {
      toast({ message: "The debate transcript is available once a run completes.", tone: "info" });
      return;
    }
    renderTranscript(state.lastResult);
    setView("transcript");
    focusTranscriptHeading();
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
      // Run-level status, scoped to the whole card so both the empty-slot
      // error placeholder and the provider-notice guard below can read it.
      // Previously this was ``const``-declared inside the ``else`` branch,
      // so the ``slot`` branch left it undefined and the provider-notice
      // check threw ``ReferenceError: runStatusValue is not defined`` once
      // per card on every poll tick — a toast storm on any completed run.
      const runStatusValue = result?.status;
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

  function buildInfoIcon(text, { ariaLabel = "More information about this section", inline = false } = {}) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = inline ? "info-icon info-icon-inline" : "info-icon";
    button.setAttribute("data-info-icon", "");
    button.setAttribute("data-info-text", text);
    button.setAttribute("aria-label", ariaLabel);
    button.innerHTML = "&#9432;";
    return button;
  }

  // Shared run-id clipboard helper: copies ``value`` and shows the same feedback
  // on ``button`` both visibly (title + ``data-copied`` colour flip) AND to
  // screen readers (``aria-label`` swap, WCAG 4.1.3), restoring the button's own
  // idle title/aria-label after a beat. Used by the result-header Run ID copy,
  // the receipt copy, the aside ``#copy-correlation``, and the live-card
  // ``#live-corr`` so all four stay in lockstep on both success AND failure.
  async function copyRunIdToClipboard(button, value, idleTitle) {
    if (!button || !value) return;
    // Preserve this button's OWN idle aria-label (callers have different ones).
    const idleAria = button.getAttribute("aria-label");
    const restore = () => {
      button.title = idleTitle;
      if (idleAria != null) button.setAttribute("aria-label", idleAria);
    };
    try {
      await navigator.clipboard.writeText(value);
      button.dataset.copied = "true";
      button.title = "Copied!";
      button.setAttribute("aria-label", "Copied");
      setTimeout(() => {
        delete button.dataset.copied;
        restore();
      }, 1500);
    } catch (_) {
      button.title = "Copy failed — select and copy manually.";
      button.setAttribute("aria-label", "Copy failed — select and copy manually");
      setTimeout(restore, 1500);
    }
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
        // Provider prose (a "**High-stakes:** …" notice) → inline markdown.
        setInlineProse(body, synthesis.high_stakes_notice);
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
    // Blockquote: consecutive lines starting with ">" collapse into one
    // <blockquote> (the marker + one optional space is stripped per line).
    let quoteBuffer = [];
    const flushQuote = () => {
      if (!quoteBuffer.length) return;
      const inner = quoteBuffer
        .map((line) => mdInline(escapeHtml(line)))
        .join("<br>");
      out.push(`<blockquote>${inner}</blockquote>`);
      quoteBuffer = [];
    };
    const listMarker = (line) => /^\s*([-*]|\d+\.)\s+/.test(line);
    const quoteMarker = (line) => /^\s*>\s?/.test(line);
    for (const line of collapsed) {
      if (line.trim() === "") {
        flushParagraph();
        flushList();
        flushQuote();
        continue;
      }
      if (quoteMarker(line)) {
        flushParagraph();
        flushList();
        quoteBuffer.push(line.replace(/^\s*>\s?/, ""));
        continue;
      }
      if (listMarker(line)) {
        flushParagraph();
        flushQuote();
        buffer.push(line);
        continue;
      }
      flushList();
      flushQuote();
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
    flushQuote();
    return out.join("");
  }

  // Render BLOCK-level provider prose (headings, lists, paragraphs, inline
  // emphasis/code/links) into ``el`` via ``formatAnswerText`` — which
  // HTML-escapes every value, so there is no XSS regression vs the old
  // ``textContent`` path. Adds ``q-prose`` for the shared nested-element
  // spacing. Falls back to a muted placeholder when the text is empty.
  // Container must be a block element (div), never a <p>/<span> (formatted
  // output contains <p>/<h*>/<ul>). Returns ``el``.
  function setProse(el, rawText, placeholder) {
    const html = formatAnswerText(rawText);
    if (html) {
      el.classList.add("q-prose");
      el.classList.remove("muted");
      el.innerHTML = html;
    } else if (placeholder != null) {
      el.classList.remove("q-prose");
      el.classList.add("muted");
      el.textContent = placeholder;
    } else {
      el.textContent = "";
    }
    return el;
  }

  // Render INLINE-only provider prose (bold/italic/inline code/links, no block
  // structure) into ``el`` via ``mdInline`` — escaping first so no raw HTML is
  // reintroduced. For single-line span/cell/caption surfaces where block tags
  // would be invalid. Falls back to a muted placeholder. Returns ``el``.
  function setInlineProse(el, rawText, placeholder) {
    const text = rawText == null ? "" : String(rawText).trim();
    if (text) {
      el.classList.remove("muted");
      el.innerHTML = mdInline(escapeHtml(text));
    } else if (placeholder != null) {
      el.classList.add("muted");
      el.textContent = placeholder;
    } else {
      el.textContent = "";
    }
    return el;
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
    // [text](url). The captured ``url`` reaches us HTML-escaped (every
    // caller runs its input through ``escapeHtml`` before mdInline), but we
    // deliberately do NOT rely on that: this replace decodes the URL back,
    // vets its scheme with the shared ``URL()``-based allow-list, and
    // re-escapes it for the attribute itself — so a markdown link is safe by
    // construction here, not by convention at a distant caller. ``URL()``
    // (like the browser's own href resolution) strips tab/CR/LF before
    // reading the scheme, so control-char tricks such as ``java\tscript:``
    // cannot smuggle a scheme past the check.
    s = s.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      (_m, text, url) => {
        const href = safeMarkdownHref(decodeBasicEntities(url));
        if (href == null) {
          // Disallowed scheme (javascript:, data:, vbscript:, tab-obfuscated
          // variants, …): render inert text, never an anchor.
          return `${text} (${url})`;
        }
        // Attribute-encode the vetted href at the interpolation point so a
        // quote in the URL can never break out of href="…".
        return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
      },
    );
    // Underscore emphasis (LLMs emit both ``_x_`` and ``*x*``). Runs LAST and
    // ONLY on text OUTSIDE already-emitted tags (via ``applyOutsideTags``), so a
    // URL underscore inside an ``href="…"`` attribute is never touched. Uses
    // GFM word-boundary rules: the opening marker must follow a non-word char
    // (or start) and the closing marker must NOT be followed by a word char, so
    // intra-word underscores in identifiers (``retention_flag``, ``snake_case``)
    // are left alone. ``__strong__`` before ``_em_``.
    s = applyOutsideTags(s, (seg) =>
      seg
        .replace(/(^|[^\w])__([^\s_](?:[^_]*[^\s_])?)__(?!\w)/g, (_m, lead, t) => `${lead}<strong>${t}</strong>`)
        .replace(/(^|[^\w])_([^\s_](?:[^_]*[^\s_])?)_(?!\w)/g, (_m, lead, t) => `${lead}<em>${t}</em>`),
    );
    return s;
  }

  // Apply ``fn`` only to the plain-text runs of a string that already contains
  // emitted HTML — every ``<…>`` tag (with its attributes) AND every whole
  // ``<code>…</code>`` span is passed through UNTOUCHED. Inline code is verbatim
  // by contract, so emphasis must never fire inside it (`` `__init__` `` must stay
  // literal, not become bold). The split captures either a full code span or a
  // single tag as the delimiter; any part that starts with ``<`` is such a
  // delimiter (all provider ``<`` were escaped to ``&lt;`` upstream, so only our
  // emitted markup begins with a literal ``<``) and is left alone.
  function applyOutsideTags(s, fn) {
    return s
      .split(/(<code>[\s\S]*?<\/code>|<[^>]*>)/)
      .map((part) => (part && part.charAt(0) === "<" ? part : fn(part)))
      .join("");
  }

  // Reverse the five entities ``escapeHtml`` emits, so a URL that was escaped
  // upstream can be scheme-checked and normalised as its real value. ``&amp;``
  // is decoded last so an escaped literal like ``&amp;lt;`` round-trips to
  // ``&lt;`` rather than being double-decoded to ``<``.
  function decodeBasicEntities(text) {
    return String(text)
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&");
  }

  // Return a safe href for a markdown link, or null when the scheme is not
  // allow-listed. Reuses ``safeHttpUrl`` (the same ``URL()`` allow-list the
  // source chips and ``createSafeLink`` use) for http(s); permits inert
  // ``mailto:`` and genuinely scheme-less relative URLs; rejects everything
  // else. Control chars are stripped the way a browser would before the
  // scheme test, so ``java\tscript:`` / ``javascript\n:`` cannot pass as
  // "relative".
  function safeMarkdownHref(rawUrl) {
    // Normalise exactly the way a browser does before it resolves an href's
    // scheme: strip EVERY C0 control char (U+0000–U+001F, incl. TAB/CR/LF) and
    // DEL, then trim surrounding spaces. ``String.trim()`` alone is NOT enough
    // — it drops only JS-whitespace, so a leading ``\x01`` (or interior TAB)
    // would slip a ``javascript:`` scheme past the checks below yet still be
    // stripped by the browser at navigation time. We VET and EMIT this same
    // cleaned string — never the raw input — so there is no vet/emit gap.
    const url = String(rawUrl == null ? "" : rawUrl)
      .replace(/[\u0000-\u001F\u007F]/g, "")
      .trim();
    if (!url) return null;
    // http(s): reuse the shared URL()-based allow-list (returns a normalised,
    // percent-encoded href, or null).
    const http = safeHttpUrl(url);
    if (http) return http;
    // mailto: inert (no script vector); validate the scheme via URL().
    try {
      if (new URL(url).protocol === "mailto:") return url;
    } catch (_e) {
      /* not an absolute URL — fall through to the relative check */
    }
    // Relative URLs (no scheme) are same-origin and safe — EXCEPT protocol-
    // relative ``//host`` and its backslash-folded equivalents ``/\``, ``\/``,
    // ``\\``. Browsers fold backslashes to forward slashes in the authority for
    // an http(s) base, so ANY two leading slash-or-backslash characters form an
    // off-origin authority (open-redirect vector). Reject those; they never
    // appear in trustworthy model output. Everything with a scheme that is not
    // http(s)/mailto is also rejected.
    if (!/^[a-z][a-z0-9+.-]*:/i.test(url) && !/^[/\\]{2}/.test(url)) {
      return url;
    }
    return null;
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
    // The "Run now" CTA is disabled alongside "See the estimate" so a run in
    // flight cannot be double-started from either composer button.
    if (runNowButton) runNowButton.disabled = isRunning;
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
      setConnectionPill("connected", connectedPillLabel());
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
  //   * by_model: the ``kind === "synthesis"`` row renders as "Debate +
  //     synthesis" (it folds in the two debate rounds too — issue #16);
  //     every other row uses its ``display_name``.
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
        label: row.kind === "synthesis" ? "Debate + synthesis" : row.display_name,
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

  // Format a planning band ``lo``–``hi`` at whole-cent precision, but COLLAPSE
  // to a single figure when both endpoints round to the same cents (issue #19):
  // a "$0.15–$0.15" range reads as a broken widget, not a range. Renders the
  // low endpoint as the single value in that case (the band is illustrative, so
  // either endpoint is representative). Assumes ``lo <= hi``.
  function gateRangeText(lo, hi) {
    const loText = gateUsd2dp(lo);
    const hiText = gateUsd2dp(hi);
    return loText === hiText ? loText : `${loText}–${hiText}`;
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

  // Populate the cost gate (screen 03) from an estimate response. Called for
  // the ``require_confirmation`` and ``block`` bands, and for an ``allow`` band
  // reached via "See the estimate" (the gate then shows a plain "Run · $X" CTA).
  // Only a "Run now" click on an allow-band estimate skips this screen entirely
  // and auto-proceeds. Does NOT switch the view —
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
      // BLOCK (> $0.25) — Slice 6 (07 cost-blocked · AC-010 · COPY-004).
      // First-class honest treatment: COPY-004 VERBATIM, the itemized
      // estimate (rendered above), the $0.25 hard-cap disclosure, an honest
      // "nothing ran / nothing charged", and the server ``reasons[]`` (the
      // real "why" — NEVER a fabricated "4 premium slots · 14,600-char
      // question"). Footer surfaces ``threshold_action: blocked`` + the
      // estimate correlation_id. No proceed path exists.
      if (gateBandLabel) gateBandLabel.textContent = "Over the hard cap — this run won't start";
      if (gateReason) {
        // COPY-004 verbatim, then the server's honest reason(s) if present.
        const serverReasons = reasons.length ? ` ${reasons.join(" ")}` : "";
        gateReason.textContent = `${COPY_004_COST_BLOCK}${serverReasons}`;
      }
      if (gateBlockNote) {
        // The guardrail blocks on the WORST-CASE (max_cost_usd), which can
        // exceed the $0.25 cap even when the typical estimate shown above is
        // under it — so the note names the worst case, not the point estimate.
        const maxCost = Number(ce.max_cost_usd);
        const ceiling = Number.isFinite(maxCost) && maxCost > total ? maxCost : total;
        gateBlockNote.textContent =
          `This run's worst-case cost (up to ${gateUsd(ceiling)}) is over the ` +
          "$0.25 hard cap and no override exists in this release. Nothing " +
          "ran and nothing was charged.";
        gateBlockNote.hidden = false;
      }
      if (gateBlockFooter) {
        const corr = estimate && estimate.correlation_id;
        gateBlockFooter.textContent = `threshold_action: blocked${corr ? ` · ${corr}` : ""}`;
        gateBlockFooter.hidden = false;
      }
      // Actions: swap the confirm/change-models pair for the two honest
      // recovery paths (both return to the composer — real, no fabrication).
      if (gateConfirmButton) gateConfirmButton.hidden = true;
      if (gateBackButton) gateBackButton.hidden = true;
      if (gateBlockModelsButton) gateBlockModelsButton.hidden = false;
      if (gateBlockShortenButton) gateBlockShortenButton.hidden = false;
      if (gateCapNote) gateCapNote.hidden = true;
      // Ctrl+Enter confirms nothing in the block band — hide that hint.
      if (gateHintConfirm) gateHintConfirm.hidden = true;
      // No planning range for a run that will not execute.
      if (gateRangeWrap) gateRangeWrap.hidden = true;
      return `Run blocked. Estimated ${gateUsd(total)} is above the $0.25 hard cap. ${COPY_004_COST_BLOCK}`;
    }

    // REQUIRE_CONFIRMATION ($0.15–$0.25).
    // Illustrative ±``PLANNING_RANGE_PCT`` planning band (NOT a server
    // interval). Only shown in this band, where total ≤ the hard limit so
    // ``lo < hi`` always holds; ``hi`` is still clamped to the ceiling and
    // both endpoints render at whole-cent precision (no false sub-cent).
    if (gateRangeWrap) gateRangeWrap.hidden = false;
    if (gateRange) {
      // Show the REAL server range: the typical point estimate → the fail-safe
      // "up to" ceiling (``max_cost_usd``) the guardrail actually evaluated.
      // This makes confirmation legible ("why confirm a $0.10 run?" → because
      // the worst case is $0.22). Fall back to the illustrative ±planning band
      // only when an (older) response omits ``max_cost_usd``.
      const maxCost = Number(ce.max_cost_usd);
      if (Number.isFinite(maxCost) && maxCost > total) {
        const hi = Math.min(maxCost, COST_HARD_LIMIT_USD);
        gateRange.textContent = gateRangeText(total, hi);
      } else {
        const lo = total * (1 - PLANNING_RANGE_PCT);
        const hi = Math.min(total * (1 + PLANNING_RANGE_PCT), COST_HARD_LIMIT_USD);
        gateRange.textContent = gateRangeText(lo, hi);
      }
    }
    // ``allow`` reaches here only via "See the estimate" (a deliberate review
    // of a run the server would let start without confirmation). Its copy must
    // NOT claim "your confirmation required" — nothing is being required; the
    // user asked to look. ``require_confirmation`` keeps the warning framing.
    const isAllowReview = action === "allow";
    if (gateBandLabel) {
      gateBandLabel.textContent = isAllowReview
        ? "Estimate ready — review and run"
        : "Cost review — your confirmation required";
    }
    if (gateReason) {
      const firstReason = reasons.length ? ` ${reasons[0]}` : "";
      gateReason.textContent = isAllowReview
        ? `This run is estimated at ${gateUsd(total)}, within the no-confirmation band — start it when you're ready.${firstReason}`
        : `${COPY_003_COST_WARNING}${firstReason}`;
    }
    if (gateConfirmButton) {
      gateConfirmButton.hidden = false;
      const label = gateConfirmButton.querySelector(".button-label");
      if (label) {
        label.textContent = isAllowReview
          ? `Run · ${gateUsd(total)}`
          : `Confirm & run · ${gateUsd(total)}`;
      }
    }
    // Reset the block-only surfaces so a prior block render never bleeds
    // into the confirm band.
    if (gateBackButton) gateBackButton.hidden = false;
    if (gateBlockModelsButton) gateBlockModelsButton.hidden = true;
    if (gateBlockShortenButton) gateBlockShortenButton.hidden = true;
    if (gateBlockNote) gateBlockNote.hidden = true;
    if (gateBlockFooter) gateBlockFooter.hidden = true;
    if (gateCapNote) gateCapNote.hidden = false;
    if (gateHintConfirm) gateHintConfirm.hidden = false;
    return isAllowReview
      ? `Estimate ready. Estimated ${gateUsd(total)}. Review and run when you're ready.`
      : `Cost review: your confirmation required. Estimated ${gateUsd(total)}.`;
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

  // ``autoProceed`` decides what happens once the server returns an ``allow``
  // band ($ ≤ the no-confirmation threshold): the "Run now" path proceeds
  // straight to the run, while the "See the estimate" path (``false``) opens
  // the gate so the user reviews the itemized estimate first. Higher bands
  // (``require_confirmation``/``block``) always open the gate regardless.
  // ``trigger`` is the button that initiated the flow, so its own spinner is
  // the one shown.
  async function estimateRun({ autoProceed = false, trigger = estimateButton } = {}) {
    clearError();
    hideCostConfirmation();
    setButtonLoading(trigger, true);
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
      // Slice 2 (03 Cost gate): route by the server ``threshold_action`` and
      // whether this is a "Run now" auto-proceed (``autoProceed``).
      //   allow + autoProceed  → skip the gate, run straight away (Run now only).
      //   allow (See estimate) → show the gate with a plain "Run · $X" CTA.
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
        if (action === "allow" && autoProceed) {
          // ≤ $0.15 AND the user chose "Run now": nothing to confirm — go
          // straight to the run. The "See the estimate" path (autoProceed
          // false) skips this branch so it always shows the gate below.
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
      setButtonLoading(trigger, false);
      // ``setButtonLoading`` clears ``disabled``; re-assert the gate so a
      // high-stakes topic detected mid-compose keeps both CTAs disabled.
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
    // Keep both CTAs disabled while an estimate round-trip is in flight
    // (``submittingRun``), not just while a run is (``isRunning``). This runs
    // in ``startRun``/``estimateRun``'s finally, which fires before the run
    // starts; without the ``submittingRun`` term the just-clicked CTA would
    // briefly flicker back to enabled between the estimate returning and the
    // auto-proceed run beginning.
    const busy = state.isRunning || state.submittingRun;
    if (estimateButton) {
      estimateButton.disabled = busy || blocked;
      estimateButton.dataset.gateBlocked = blocked ? "true" : "false";
    }
    // "Run now" is gated identically: an unacknowledged high-stakes topic must
    // block the direct-run path too, not just the estimate-first path.
    if (runNowButton) {
      runNowButton.disabled = busy || blocked;
      runNowButton.dataset.gateBlocked = blocked ? "true" : "false";
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

  // Entry point for both composer CTAs. It always fetches the estimate first
  // (so the cost is known before anything spends), then either opens the cost
  // gate or — for a ``Run now`` click on an ``allow``-band estimate — proceeds
  // straight to the run. ``autoProceed`` selects between the two; ``trigger``
  // is the button that fired so its own spinner is shown.
  async function startRun(autoProceed = false, trigger = estimateButton) {
    // Re-entrancy latch. With two composer CTAs, clicking one only disables
    // THAT button (``setButtonLoading`` below) — the sibling and Ctrl/Cmd+Enter
    // stay live during the estimate round-trip. Without this guard a second
    // click could fire a concurrent ``estimateRun`` (and, on the Run-now
    // allow-band path, yank the view mid-run). ``state.isRunning`` is only set
    // later, after the create POST, so it can't cover this window. Set the latch
    // synchronously (no await before it) and clear it in ``finally``.
    if (state.submittingRun || state.isRunning) return;
    state.submittingRun = true;
    state.submissionAttempted = true;
    clearError();
    if (!highStakesGateSatisfied()) { state.submittingRun = false; return; }
    setButtonLoading(trigger, true);
    // Lock the sibling CTA for the whole estimate window too, so neither the
    // other button nor Ctrl/Cmd+Enter (which keys off ``estimateButton.disabled``)
    // can start a second flow before this one resolves.
    const sibling = trigger === estimateButton ? runNowButton : estimateButton;
    if (sibling) sibling.disabled = true;
    try {
      const queryText = queryTextarea.value.trim();
      if (!queryText) {
        throw new ApiError({
          status: 422,
          code: "QUERY_REQUIRED",
          message: "Please enter a question before starting a run.",
        });
      }
      await estimateRun({ autoProceed, trigger });
    } catch (error) {
      handleError(error);
    } finally {
      state.submittingRun = false;
      setButtonLoading(trigger, false);
      // ``setButtonLoading`` clears ``disabled``; re-assert the run/gate
      // state so both CTAs stay disabled when a run is now in flight (a
      // ``Run now`` allow-band click auto-proceeds inside ``estimateRun``)
      // or a high-stakes topic is unacknowledged. This also re-derives the
      // sibling CTA's disabled state that was force-locked above.
      applyHighStakesGate();
    }
  }

  // User clicked "Proceed with this run" inside the cost callout.
  // Sends the create-run POST. For the REQUIRE_CONFIRMATION band the
  // server is sent the matching confirmation token; for ALLOW no
  // token is needed; for BLOCK the button is disabled and this path
  // cannot fire.
  async function proceedWithRun() {
    // Synchronous single-create latch. ``setRunning(true)`` (which disables
    // every run CTA) only fires AFTER the create POST returns, so between two
    // concurrent entry points — a Run-now auto-proceed still awaiting its
    // create, and a cost-gate "Run · $X" click — both would otherwise pass to a
    // second create. This latch (set before the first await, cleared in
    // ``finally``) guarantees at most one create is ever in flight, enforcing
    // the "one run at a time per session" invariant on the client.
    if (state.creatingRun) return;
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
    // Commit to the create: latch now (synchronously, before any await) so a
    // concurrent proceedWithRun bails at the guard above.
    state.creatingRun = true;
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
      // Slice 5 (06 Transcript): drop the previous run's transcript snapshot so
      // the drill-down can never render stale openings/critiques for a new run.
      state.lastResult = null;
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
      state.liveElapsedStamp = nowMs();
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
      // Release the single-create latch. On the success path the run is now in
      // flight and ``setRunning(true)`` keeps every CTA disabled anyway; on the
      // failure path this re-opens the create for a genuine retry.
      state.creatingRun = false;
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
        // Slice 5 (06 Transcript): stash the terminal result so the transcript
        // drill-down renders honest per-model openings + round critiques
        // without a re-fetch. Captured only alongside a real synthesis (same
        // guard as the result view), so the transcript link only ever opens a
        // completed audit trail.
        state.lastResult = result;
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
        // Slice 6 (07 provider failure · AC-015). First-class honest
        // treatment driven ENTIRELY by server data: which step(s) failed,
        // the server's user-safe failure notice(s), and the correlation +
        // run ids. The mock's "Retry this step" / "Continue with 3 models"
        // buttons are DROPPED — there is no per-step retry endpoint, so
        // rendering them would be a lie. Only real actions are offered.
        showProviderFailure(result);
        toast({ message: "Run failed. See the banner above.", tone: "error", timeout: 8000 });
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
        state.lastResult = result;
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

  // ---------------------------------------------------------------------------
  // Slice 6 — 07 Edge states (the seven)
  // ---------------------------------------------------------------------------
  //
  // The seven edge states are surfaced IN the existing SPA (not a parallel
  // gallery), each wired to its REAL server trigger:
  //   1. Anonymous · AC-001        → session-establishment FAILURE
  //      (``AUTH_REQUIRED``). The app auto-creates a session on boot, so a
  //      *persistent* anonymous gate is unreachable; the honest analog is
  //      "we couldn't start a session", which is what this state says.
  //   2. Active query exists · AC-003 → 409 ``ACTIVE_QUERY_EXISTS`` on a 2nd
  //      create. Actions ("Go to run" / "Stop it & start new") both hit real
  //      endpoints (``GET`` / ``DELETE /v1/query-runs/{active}``).
  //   3. Provider failure · AC-015 → a failed run (``status==="failed"`` +
  //      ``failed_steps``). Handled at the pollRun terminal branch
  //      (``showProviderFailure``). There is NO per-step retry endpoint, so
  //      the mock's "Retry this step" / "Continue with 3 models" buttons are
  //      DROPPED — only real actions (new run / review results) are offered.
  //   4. Partial result · AC-022  → ``status==="partial"``; the run has a
  //      synthesis, so it lands on the result view with first-class partial
  //      disclosure (``#live-notices`` + the result notices).
  //   5. Invalid model slot · AC-008 → 422 ``INVALID_MODEL_SLOT`` +
  //      ``slot_errors``. Names the exact slot + bad id from server data. The
  //      backend provides NO "did you mean" suggestion, so none is shown.
  //   6. Cost blocked · AC-010 · COPY-004 → the cost-gate block band (see
  //      ``renderCostGate``). Defensive create-time 402 also lands here.
  //   7. Wrong session · AC-032  → the backend returns 404
  //      ``QUERY_RUN_NOT_FOUND`` for a run not owned by this session (the
  //      SAME response as a truly-missing run — it deliberately does NOT
  //      disclose existence, so it is honest to NOT invent a 403). We defend
  //      against both 404-not-found and a raw 403 and disclose NOTHING.

  // Friendly stage labels for failed / missing step keys. Falls back to the
  // raw key (spaces for underscores) for anything unmapped.
  const STEP_LABELS = {
    initial_answers: "Initial answers",
    debate_round_1: "Debate round 1",
    debate_round_2: "Debate round 2",
    synthesis: "Synthesis",
    pipeline: "Pipeline",
  };
  function stepLabel(step) {
    return STEP_LABELS[step] || String(step || "").replace(/_/g, " ");
  }

  // COPY-004 (verbatim, docs/33-content-design.md). Cost block message.
  const COPY_004_COST_BLOCK =
    "This run is above the MVP cost limit. Choose lower-cost models, " +
    "shorten the query, or reduce the workflow before trying again.";

  // Return to the composer and clear the current edge state. Optionally
  // focus a specific field so the fix path is obvious.
  function returnToComposer(focus) {
    clearError();
    setView("composer");
    if (focus === "slot") {
      const firstSlot = document.querySelector("[data-model-slot]");
      if (firstSlot) {
        firstSlot.focus({ preventScroll: true });
        return;
      }
    }
    // Default (and the "question" fix path): land focus on the query box.
    if (queryTextarea) queryTextarea.focus({ preventScroll: true });
  }

  // AC-003 "Go to run": look up the session's OWN active run and switch to
  // the live-run view. Only ever surfaces the caller's own run.
  async function goToActiveRun() {
    const active = await api("/v1/query-runs/active", { method: "GET" });
    if (!active || !active.query_run_id) {
      clearError();
      toast({ message: "No active run found — you can start a new one.", tone: "info" });
      returnToComposer();
      return;
    }
    clearError();
    state.currentRunId = active.query_run_id;
    setRunning(true);
    setView("live-run");
    focusLiveHeading();
    startPolling();
  }

  // AC-003 "Stop it & start new": cancel the session's own active run, then
  // return to the composer. Real DELETE — no fabricated affordance.
  async function stopActiveRunAndCompose() {
    const active = await api("/v1/query-runs/active", { method: "GET" });
    if (active && active.query_run_id) {
      await api(`/v1/query-runs/${active.query_run_id}`, { method: "DELETE" });
      toast({ message: "Previous run stopped. Start a fresh query.", tone: "info" });
    }
    stopPolling();
    state.currentRunId = null;
    setRunning(false);
    returnToComposer();
  }

  // AC-001 "Start a session": retry the session bootstrap in place. Falls
  // back to a full reload if the retry itself fails.
  async function retrySession() {
    try {
      await initSession();
      await refreshDefaults();
      clearError();
      toast({ message: "Session started. You can run a query now.", tone: "success" });
    } catch (_) {
      location.reload();
    }
  }

  // AC-015 Provider failure — a failed run. Surfaced from the pollRun
  // terminal branch (the failure arrives as a run projection, not an
  // ApiError). Renders ONLY server-provided fields: failed step(s), the
  // user-safe provider failure notice(s), "other steps completed", and both
  // ids. NO per-step "Retry" / "Continue with N models" — the backend has
  // no such endpoint, so those mock buttons are deliberately absent.
  function showProviderFailure(result) {
    const failedSteps = Array.isArray(result.failed_steps) ? result.failed_steps : [];
    const missingSteps = Array.isArray(result.missing_steps) ? result.missing_steps : [];
    const providerNotices = Array.isArray(result.provider_failure_notices)
      ? result.provider_failure_notices
      : [];
    const partialNotice = result.partial_failure_notice || "";

    const detailRows = [];
    if (failedSteps.length) {
      detailRows.push({
        label: failedSteps.length === 1 ? "Failed step" : "Failed steps",
        value: failedSteps.map(stepLabel).join(", "),
        tone: "danger",
      });
    }
    // The server's user-safe notice — never a synthesised HTTP code.
    const notice = providerNotices[0] || partialNotice;
    if (notice) {
      detailRows.push({ label: "Provider response", value: notice });
    }
    // "Other steps completed" — only claim it when at least one of the four
    // pipeline stages is NOT in the failed/missing set (honest, derived).
    const brokenSteps = new Set([...failedSteps, ...missingSteps]);
    const pipeline = ["initial_answers", "debate_round_1", "debate_round_2", "synthesis"];
    const completed = pipeline.filter((s) => !brokenSteps.has(s));
    if (completed.length && brokenSteps.size) {
      detailRows.push({
        label: "Other steps",
        value: `${completed.length} completed`,
      });
    }

    // Footer: the ONE friendly Run ID, quoted for support. The raw query_run_id
    // is the SAME run in another format (correlation_id is "qr_" + uuid.hex);
    // quoting two competing ids only confuses the user, so we surface one —
    // matching the result header and receipt. Fall back to the raw id only if
    // the friendly form is absent. No secrets, no provider keys.
    const supportId =
      result.correlation_id || (result.query_run_id ? String(result.query_run_id) : "");
    const footer = supportId ? `Run ID ${supportId} — quote when reporting` : undefined;

    const actions = [
      { label: "Start a new run", primary: true, action: () => returnToComposer("question") },
    ];
    // Only offer "Review available results" when a synthesis actually
    // exists (otherwise the button would open an empty result view).
    if (result.result && result.result.final_synthesis) {
      actions.push({
        label: "Review available results",
        action: () => {
          clearError();
          state.lastResult = result;
          renderResult(result);
          setView("result");
          focusResultHeading();
        },
      });
    }

    showError({
      code: "RUN_FAILED",
      severity: "error",
      acTag: "Provider failure · AC-015",
      message:
        "A model step returned a provider error, so the run couldn't " +
        "finish. This is a provider-side issue, not your query — no keys " +
        "or secrets are exposed.",
      detailRows,
      actions,
      footer,
    });
  }

  // Map a caught error to one of the seven honest edge states, or ``null``
  // when it is an ordinary error (handled by the generic banner). Every
  // field is derived from REAL server data — no fabricated slot suggestion,
  // provider status, or "why" reason.
  function edgeStateFromError(error) {
    if (!(error instanceof ApiError)) return null;
    const code = error.code;
    const status = error.status;

    // AC-032 Wrong session — the ONLY honest signal is 404 QUERY_RUN_NOT_FOUND
    // (the backend returns the SAME 404 for a missing OR a non-owned run, so
    // existence is never disclosed). It never returns 403 for a non-owned run:
    // the only 403s are CSRF_INVALID / SESSION_EXPIRED, which must fall through
    // to their own "Security check failed" / "Refresh session" handlers — NOT
    // be mislabeled as a cross-session access event. Disclose NOTHING here.
    if (code === "QUERY_RUN_NOT_FOUND") {
      return {
        code: "QUERY_RUN_NOT_FOUND",
        severity: "neutral",
        acTag: "Wrong session · AC-032",
        message:
          "This link belongs to a different browser session. Runs are " +
          "private to the session that started them and disappear when it " +
          "ends — so we can't open it for you. That's the extent of what " +
          "we can say about it.",
        actions: [
          { label: "Start your own query", primary: true, action: () => returnToComposer("question") },
          { label: "Start a session", action: retrySession },
        ],
        footer: "error 404 · no run details disclosed",
      };
    }

    // AC-003 Active query exists — 409 on a second create.
    if (code === "ACTIVE_QUERY_EXISTS") {
      return {
        code,
        severity: "info",
        acTag: "Active query exists · AC-003",
        message:
          "One active query per session keeps costs predictable. Jump back " +
          "to your running query, or stop it before starting a new one.",
        actions: [
          { label: "Go to run", primary: true, action: goToActiveRun },
          { label: "Stop it & start new", action: stopActiveRunAndCompose },
        ],
      };
    }

    // AC-008 Invalid model slot — 422 with per-slot errors.
    if (code === "INVALID_MODEL_SLOT") {
      const slotErrors = Array.isArray(error.slotErrors) ? error.slotErrors : [];
      const detailRows = slotErrors.map((se) => ({
        label: se.slot_number ? `Slot ${se.slot_number}` : "Model slots",
        value: se.model_id || "(empty)",
        mono: true,
        tone: "danger",
        // ``se.message`` is the server's exact reason (e.g. "…is not in the
        // catalog") — no client-side "did you mean" is fabricated.
        sub: se.message || undefined,
      }));
      return {
        code,
        severity: "error",
        acTag: "Invalid model slot · AC-008",
        message:
          "That model ID isn't one we can call, so nothing was sent and " +
          "nothing was charged. The error names the exact slot — never a " +
          'generic "invalid input".',
        detailRows,
        actions: [
          { label: "Fix model slots", primary: true, action: () => returnToComposer("slot") },
        ],
        footer: error.correlationId ? `${error.correlationId}` : undefined,
      };
    }

    // AC-010 Cost blocked (defensive create-time 402; the estimate gate is
    // the primary surface — see ``renderCostGate``). COPY-004 verbatim.
    if (code === "COST_LIMIT_EXCEEDED") {
      return {
        code,
        severity: "error",
        acTag: "Cost blocked · AC-010 · COPY-004",
        message: `${COPY_004_COST_BLOCK} Nothing ran and nothing was charged.`,
        detailRows: [
          { label: "Hard cap", value: "$0.25 · no override", mono: true },
        ],
        actions: [
          { label: "Choose cheaper models", primary: true, action: () => returnToComposer("slot") },
          { label: "Shorten the question", action: () => returnToComposer("question") },
        ],
        footer: `threshold_action: blocked${error.correlationId ? ` · ${error.correlationId}` : ""}`,
      };
    }

    // AC-001 Anonymous — session establishment failed on boot.
    if (code === "AUTH_REQUIRED") {
      return {
        code,
        severity: "neutral",
        acTag: "Anonymous · AC-001",
        message:
          "We couldn't start a browser session, so no query can run yet. " +
          "Starting a session is one click — a secure cookie, no signup or " +
          "password. Provider access is configured on the server; you'll " +
          "never enter an API key.",
        actions: [{ label: "Start a session", primary: true, action: retrySession }],
        footer: status ? `session unavailable · error ${status}` : undefined,
      };
    }

    return null;
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
    // Slice 6 (07 edge states): route recognised codes to their honest,
    // first-class edge treatment before the generic fallback.
    const edge = edgeStateFromError(error);
    if (edge) {
      showError(edge);
      return;
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
    // The glyph advertises the ACTION the click performs — the TARGET theme —
    // so it agrees with the ``aria-label``. In light mode the button shows ☾
    // ("click to go dark"); in dark mode it shows ☀ ("click to go light").
    // (Previously it showed the CURRENT state — ☀ while light — which
    // contradicted the "Switch to dark theme" label a screen reader announces.)
    // We seed the glyph from the current ``data-theme`` so the first paint is
    // already consistent — important on browsers that re-hydrate the page
    // mid-session.
    const setGlyph = () => {
      const isDark = root.dataset.theme === "dark";
      button.textContent = isDark ? "☀" : "☾";
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

  // First-visit gate for the marketing landing (screen 01).
  //
  // The landing is the default "front door" ONLY for visitors who have not yet
  // entered the workspace on this device; returning visitors boot straight into
  // the composer (screen 02). The flag is a device-local UX preference — not
  // auth/session state — so ``localStorage`` is the right store. Every access is
  // guarded because ``localStorage`` throws in private-mode / storage-disabled
  // browsers. On read failure we fail toward the workspace (return ``true``): we
  // never want to nag a no-storage user with the landing on every reload, and
  // the landing stays reachable for them via the visible "How it works" link.
  const WORKSPACE_SEEN_KEY = "quorum.workspaceSeen";
  function hasSeenWorkspace() {
    try {
      return window.localStorage.getItem(WORKSPACE_SEEN_KEY) === "1";
    } catch (_) {
      return true;
    }
  }
  function markWorkspaceSeen() {
    try {
      window.localStorage.setItem(WORKSPACE_SEEN_KEY, "1");
    } catch (_) {
      // Best-effort: if we cannot persist, the only cost is the landing
      // reappearing on the next load — harmless, and every CTA still works.
    }
  }

  // Slice 7 (01 Landing) — the marketing front door.
  //
  // HONESTY / WIRING contract:
  //   * The landing is REACHABLE (top-bar "How it works" → ``setView("landing")``)
  //     but is NOT the default view — ``boot()`` still lands on the composer.
  //   * NOTHING on the landing runs a query or fabricates a live estimate. The
  //     "Estimate" and "Run the debate" buttons both just open the composer
  //     (estimate-first flow lives there); "Run" pre-fills nothing.
  //   * The example chips fill the REAL composer textarea via ``.value`` (not
  //     innerHTML) with the chip's own question, dispatch a native ``input``
  //     event so validation/char-count/high-stakes probing run exactly as if
  //     the user typed it, then switch to the composer and focus the field.
  //   * The "Example preview" card is illustrative marketing copy (labelled),
  //     never presented as a result the user produced.
  function initLanding() {
    const showLandingButton = el("show-landing");
    const landingHeading = el("landing-heading");

    // Enter the landing view and move focus to its single h1 (one h1 per view).
    function enterLanding() {
      setView("landing");
      if (landingHeading) {
        landingHeading.focus({ preventScroll: true });
        landingHeading.scrollIntoView({
          behavior: prefersReducedMotion() ? "auto" : "smooth",
          block: "start",
        });
      }
    }

    // Landing question input, its empty-submit guard, and the on-page-A
    // transition message elements.
    const landingQuery = el("landing-query");
    const landingRunbar = qs(".landing-runbar");
    const landingQueryError = el("landing-query-error");
    const landingHandoffNote = el("landing-handoff-note");
    const landingHandoffNoteText = el("landing-handoff-note-text");
    // How long the transition message dwells on page A before the view changes,
    // so the visitor can read WHY they are being moved to the workspace. The note
    // is a ~19-word sentence; at typical reading speed that needs roughly this
    // long to land before the composer takes over.
    const LANDING_HANDOFF_DWELL_MS = 2800;
    let landingHandoffPending = false;
    // Pending landing Estimate/Run dwell timer (so a chip click can cancel it).
    let landingHandoffTimer = null;
    // Timer that clears the composer question's post-hand-off highlight flash.
    let composerHandoffFlashTimer = null;

    // Clear the empty-submit error state (called on typing and on a valid submit).
    function clearLandingError() {
      if (landingRunbar) delete landingRunbar.dataset.invalid;
      if (landingQuery) landingQuery.setAttribute("aria-invalid", "false");
      if (landingQueryError) landingQueryError.hidden = true;
    }

    // Empty-submit guard: show ALL cues together — highlight the runbar (danger
    // ring), reveal the "!" error message, mark the input aria-invalid, move
    // focus to the field, and let ``role="alert"`` announce it. Returns true
    // when a question is present.
    function landingHasQuestion() {
      const value = (landingQuery && landingQuery.value.trim()) || "";
      if (value) {
        clearLandingError();
        return true;
      }
      if (landingRunbar) landingRunbar.dataset.invalid = "true";
      if (landingQuery) landingQuery.setAttribute("aria-invalid", "true");
      if (landingQueryError) {
        // Re-assert the text so ``role="alert"`` announces on each attempt.
        landingQueryError.textContent = "Enter a question to continue.";
        landingQueryError.hidden = false;
      }
      if (landingQuery) landingQuery.focus({ preventScroll: true });
      return false;
    }

    // Show the tailored transition message ON page A. ``kind`` is the page-A
    // button that was clicked: "estimate" or "run". Hides the error first (the
    // two are mutually exclusive).
    function showLandingHandoffNote(kind) {
      clearLandingError();
      if (!landingHandoffNote || !landingHandoffNoteText) return;
      const message =
        kind === "estimate"
          ? "Got your question. Taking you to review your four models and see the itemized cost before anything runs…"
          : "Got your question. Taking you to review your four models, then we'll price it and run once you approve…";
      // Reveal the container FIRST, then write the text: a ``role="status"``
      // aria-live=polite region announces a text mutation that happens while it
      // is in the accessibility tree. Writing the text while still ``hidden`` and
      // then merely un-hiding is not reliably announced (NVDA/VoiceOver), so the
      // reason-for-navigation could go unspoken. Order matters here.
      landingHandoffNote.hidden = false;
      landingHandoffNoteText.textContent = message;
    }

    // Disable/enable the two landing CTAs while the transition message dwells, so
    // a second click can't fire a second hand-off mid-transition.
    function setLandingCtasDisabled(disabled) {
      for (const id of ["landing-estimate", "landing-run"]) {
        const btn = el(id);
        if (btn) btn.disabled = disabled;
      }
    }

    // Reset the hand-off dwell latch: clear any pending timer, drop the pending
    // flag, and re-enable the CTAs. Shared by every site that ends a dwell (the
    // timer firing, an example-chip/open-workspace navigation, and How-it-works
    // cancelling) so the trio never drifts out of sync between them.
    function clearLandingHandoffLatch() {
      window.clearTimeout(landingHandoffTimer);
      landingHandoffTimer = null;
      landingHandoffPending = false;
      setLandingCtasDisabled(false);
    }

    // Cancel a pending Estimate/Run dwell WITHOUT navigating: clear the timer,
    // drop the pending latch, re-enable the CTAs, and hide the transition note.
    // Used when the visitor does something during the dwell that means they no
    // longer want the automatic hand-off (e.g. clicking "How it works" to read
    // the example instead of being yanked to the composer). Returns true when a
    // pending hand-off was actually cancelled.
    function cancelPendingHandoff() {
      if (!landingHandoffTimer) return false;
      clearLandingHandoffLatch();
      if (landingHandoffNote) landingHandoffNote.hidden = true;
      return true;
    }

    // Every landing CTA leads here: to the composer, textarea focused. Entering
    // the workspace this way marks it "seen" so the first-visit gate in
    // ``boot()`` sends this device straight to the composer next time. ``setView``
    // clears the landing transient state (error + transition note).
    function goToComposer() {
      // If a landing Estimate/Run dwell is still pending (e.g. the visitor
      // clicked an example chip during the ~2.8s dwell), cancel it: this call
      // already lands them on the composer, so letting the stray timer fire a
      // second goToComposer later would yank the viewport back to the top and
      // re-flash after they had settled in. Clearing an already-fired timer is
      // a harmless no-op.
      if (landingHandoffTimer) clearLandingHandoffLatch();
      markWorkspaceSeen();
      setView("composer");
      if (!queryTextarea) return;
      // Bring the composer back to the top of the viewport so the question field
      // the user just filled — from an example chip, a follow-up, or the landing
      // hand-off — is actually visible, framed under the "Ask the panel" heading.
      // A bare focus({preventScroll}) left the viewport wherever the user had
      // scrolled (at the example chips, or deep in the result's follow-up block),
      // so the "focused" field sat off-screen and the hand-off looked like nothing
      // had happened. Instant scroll (no animation) is reduced-motion-safe.
      window.scrollTo(0, 0);
      queryTextarea.focus({ preventScroll: true });
      // Caret at the END of the pre-filled text, ready to refine.
      const caret = queryTextarea.value.length;
      try {
        queryTextarea.setSelectionRange(caret, caret);
      } catch (_) {
        // setSelectionRange throws on some input types; the focus still lands.
      }
      // Programmatic focus does NOT trigger :focus-visible, and the composer
      // textarea suppresses the plain-:focus ring, so without this the field
      // gives no visible "your question landed here" cue after a hand-off. Flash
      // an explicit highlight for a beat so the focus is unmistakable — but ONLY
      // when a question was actually carried in. A bare "Open the workspace" skip
      // (empty composer) would otherwise ring an empty field, which reads as a
      // spurious "your question landed here" cue over nothing.
      if (queryTextarea.value.length > 0) {
        queryTextarea.classList.add("question-handoff-focus");
        if (composerHandoffFlashTimer) window.clearTimeout(composerHandoffFlashTimer);
        composerHandoffFlashTimer = window.setTimeout(() => {
          queryTextarea.classList.remove("question-handoff-focus");
          composerHandoffFlashTimer = null;
        }, 1400);
      }
    }

    // Estimate/Run on the landing: validate, carry the typed question into the
    // real composer (so its own validation/char-count/high-stakes probe run),
    // show the tailored transition message ON page A, then — after a short dwell
    // so the visitor reads WHY — hand off to the composer. Nothing is estimated
    // or run here; page B owns model review + cost approval.
    function handoffFromLanding(kind) {
      if (landingHandoffPending) return;
      if (!landingHasQuestion()) return;
      landingHandoffPending = true;
      const question = landingQuery.value.trim();
      if (queryTextarea) {
        queryTextarea.value = question;
        queryTextarea.dispatchEvent(new Event("input", { bubbles: true }));
      }
      showLandingHandoffNote(kind);
      setLandingCtasDisabled(true);
      // Disabling the CTA the user just activated blurs it, which drops keyboard
      // focus to <body> for the whole dwell (a lost-focus a11y gap). Re-home focus
      // onto the still-visible question field so a keyboard/SR user keeps an
      // anchored, sensible focus until goToComposer moves it to the composer.
      if (landingQuery) landingQuery.focus({ preventScroll: true });
      landingHandoffTimer = window.setTimeout(() => {
        clearLandingHandoffLatch();
        // The field stays focused through the dwell, so the visitor may have
        // refined the question. Carry the LATEST text (not the click-time
        // snapshot) into the composer so a dwell-time edit is never discarded.
        if (queryTextarea && landingQuery && landingQuery.value.trim() !== queryTextarea.value) {
          queryTextarea.value = landingQuery.value.trim();
          queryTextarea.dispatchEvent(new Event("input", { bubbles: true }));
        }
        goToComposer();
      }, LANDING_HANDOFF_DWELL_MS);
    }

    if (showLandingButton) {
      showLandingButton.addEventListener("click", enterLanding);
    }

    // "How it works" on the landing itself reveals the illustrative example.
    const landingHowItWorks = el("landing-howitworks");
    const landingPreview = qs(".landing-preview");
    if (landingHowItWorks && landingPreview) {
      landingHowItWorks.addEventListener("click", () => {
        // If an Estimate/Run dwell is pending, the visitor clicking "How it works"
        // means they want to read the example, NOT be yanked to the composer a
        // beat later. Cancel the pending hand-off before scrolling to the preview.
        cancelPendingHandoff();
        landingPreview.scrollIntoView({
          behavior: prefersReducedMotion() ? "auto" : "smooth",
          block: "center",
        });
      });
    }

    // Typing clears the empty-submit error immediately.
    if (landingQuery) {
      landingQuery.addEventListener("input", () => {
        if (landingQuery.value.trim()) clearLandingError();
      });
      // Ctrl/Cmd+Enter from the landing question field runs the same estimate-first
      // hand-off as clicking "See the estimate". The global keyboard-shortcut
      // handler no-ops on the landing (it predates this real textarea), so without
      // this the natural submit gesture is a dead key. Stop propagation so the
      // global handler does not also fire. Empty input falls through to the
      // landing empty-submit guard (same as the button), not a silent no-op.
      landingQuery.addEventListener("keydown", (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          event.preventDefault();
          event.stopPropagation();
          handoffFromLanding("estimate");
        }
      });
    }

    // "Open the workspace" is a plain skip-to-B link (no question needed — the
    // user will type on B). Estimate/Run carry the typed question, guard the
    // empty case, and show the on-page-A transition message.
    const openWorkspaceBtn = el("landing-open-workspace");
    if (openWorkspaceBtn) openWorkspaceBtn.addEventListener("click", goToComposer);
    const estimateBtn = el("landing-estimate");
    if (estimateBtn) estimateBtn.addEventListener("click", () => handoffFromLanding("estimate"));
    const runBtn = el("landing-run");
    if (runBtn) runBtn.addEventListener("click", () => handoffFromLanding("run"));

    // Example chips: fill the real composer textarea, then open it.
    for (const chip of qsa("[data-landing-chip]")) {
      chip.addEventListener("click", () => {
        const question = chip.dataset.landingChip || "";
        if (queryTextarea) {
          queryTextarea.value = question;
          // Native input event so the composer's own validation, character
          // counter, and high-stakes probe react as if the user typed it.
          queryTextarea.dispatchEvent(new Event("input", { bubbles: true }));
        }
        goToComposer();
      });
    }

    // Result-view "Ask your next question" (design parity, screen 05). Follow-up
    // and Start fresh both route back to the composer — there is no server-side
    // context carry (that remains a documented backend follow-up), so the copy
    // only promises what actually happens: the question is pre-filled and the
    // user re-approves the estimate.
    const nextInput = el("result-next-input");
    const followBtn = el("result-followup");
    const freshBtn = el("result-startfresh");
    const nextRun = el("result-next-run");
    let nextFollowUp = true;
    function setNextMode(followUp) {
      nextFollowUp = followUp;
      if (followBtn) {
        followBtn.classList.toggle("result-next-mode-active", followUp);
        followBtn.setAttribute("aria-pressed", String(followUp));
      }
      if (freshBtn) {
        freshBtn.classList.toggle("result-next-mode-active", !followUp);
        freshBtn.setAttribute("aria-pressed", String(!followUp));
      }
      if (!followUp && nextInput) nextInput.value = "";
      if (nextInput) nextInput.focus({ preventScroll: true });
    }
    if (followBtn) followBtn.addEventListener("click", () => setNextMode(true));
    if (freshBtn) freshBtn.addEventListener("click", () => setNextMode(false));
    if (nextRun) {
      nextRun.addEventListener("click", async () => {
        const typed = (nextInput && nextInput.value.trim()) || "";
        // Follow-up pre-fills the answered question so the user can refine it;
        // Start fresh (or a typed refinement) uses the box verbatim.
        const base = typed || (nextFollowUp ? state.liveQueryText || "" : "");
        if (queryTextarea) {
          queryTextarea.value = base;
          queryTextarea.dispatchEvent(new Event("input", { bubbles: true }));
        }
        // Land on the composer (page B) with the question pre-filled so the user
        // can REVIEW OR CHANGE their four models before running — a follow-up
        // reuses the same models by default, but a new question may want a
        // different panel. We deliberately do NOT auto-fire the estimate here;
        // the user picks their models then clicks See the estimate / Run now.
        goToComposer();
      });
    }
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
      // Item 3: refresh the per-slot pre-run estimate for the newly
      // selected model(s). Runs after the card rebuild so the estimate
      // cells exist to paint.
      updatePerSlotEstimates();
      // PR-0 / Bug 9: re-evaluate the drift banner against the
      // new selection. If the user just moved off the drifted
      // default, the banner should disappear on this change
      // rather than waiting for the next ``/ready`` poll.
      renderDriftBanner();
    });
  }

  function initQueryValidation() {
    queryTextarea.addEventListener("input", updateQueryValidation);
    // Item 3: keep the per-slot pre-run estimate in step with the query as the
    // user types. Pure client-side arithmetic (no network), so no debounce.
    queryTextarea.addEventListener("input", updatePerSlotEstimates);
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
        // No-op on the marketing landing (screen 01): it has no run flow of its
        // own — its CTAs route to the composer. Without this guard, a first-time
        // visitor pressing Ctrl/Cmd+Enter on the landing would fire an empty
        // ``startRun()`` and paint a QUERY_REQUIRED error banner over the pitch.
        if (document.getElementById("main-content")?.dataset.activeView === "landing") {
          return;
        }
        // On the cost gate, Ctrl/Cmd+Enter confirms the estimate (unless
        // the confirm CTA is absent/disabled — e.g. the block band).
        if (gateActive) {
          if (gateConfirmButton && !gateConfirmButton.hidden && !gateConfirmButton.disabled) {
            proceedWithRun();
          }
          return;
        }
        // Ctrl/Cmd+Enter runs the estimate-first flow (``startRun`` with the
        // default ``autoProceed=false``), which always routes through the cost
        // gate — the same as clicking "See the estimate". "Run now" (direct) is
        // mouse-only by design. The high-stakes gate keeps the CTA disabled
        // until acknowledged, and the estimate-window latch inside ``startRun``
        // blocks a second concurrent flow.
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
    // First-visit gate: show the marketing landing (screen 01) as the front
    // door to first-time visitors, and boot returning visitors straight into
    // the composer (screen 02). None of the boot helpers below call
    // ``setView``, so the view chosen here is the one the user lands on. Every
    // landing CTA marks the workspace as seen (see ``goToComposer``), so this
    // branch takes the landing path at most once per device. We do NOT move
    // focus to the landing heading here — on a fresh page load assistive tech
    // already reads from the top, and forcing focus would paint a stray outline
    // on the h1. (View-switch focus management lives in ``enterLanding``, which
    // fires only on the user-initiated "How it works" click.)
    setView(hasSeenWorkspace() ? "composer" : "landing");
    // Hand view control back to the normal ``hidden`` mechanism now that
    // setView has applied the correct initial view. The pre-paint gate (inline
    // ``<head>`` script + critical CSS in workspace.html) forced the landing on
    // first visit to avoid a flash of the composer; clearing it AFTER setView
    // (which already set the matching ``hidden`` attributes) avoids any flash or
    // reflow, and prevents the ``!important`` rules from trapping the composer
    // hidden once a first-time visitor navigates into it.
    document.documentElement.removeAttribute("data-first-visit");
    initThemeToggle();
    initLanding();
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
      // "See the estimate" always opens the cost gate first (autoProceed
      // false), even for a cheap allow-band run.
      startRun(false, estimateButton);
    });
    if (runNowButton) {
      runNowButton.addEventListener("click", () => {
        // "Run now" starts straight away for an allow-band estimate; higher
        // cost bands still fall into the gate inside ``estimateRun``.
        startRun(true, runNowButton);
      });
    }
    // ``copyRunIdToClipboard`` is a shared top-level helper (defined near
    // ``buildInfoIcon``) so the result header, receipt, aside, and live card all
    // copy a run id with identical success/failure feedback.
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
    // Slice 6 (07 cost-blocked · AC-010): the block band's two honest
    // recovery paths. Both return to the composer — "Choose cheaper models"
    // lands focus on the first model slot, "Shorten the question" on the
    // query box. Neither runs anything.
    if (gateBlockModelsButton) {
      gateBlockModelsButton.addEventListener("click", () => {
        returnToComposer("slot");
      });
    }
    if (gateBlockShortenButton) {
      gateBlockShortenButton.addEventListener("click", () => {
        returnToComposer("question");
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
    // Slice 4b (05 Result): "Run details" disclosure toggle. Collapsed by
    // default; expands/collapses the run-receipt panel. Keyboard operable
    // (native <button>), reflects state via aria-expanded + the caret glyph.
    const resultDetailsToggle = el("result-details-toggle");
    if (resultDetailsToggle) {
      resultDetailsToggle.addEventListener("click", () => {
        const receipt = el("result-receipt");
        const next = resultDetailsToggle.getAttribute("aria-expanded") !== "true";
        resultDetailsToggle.setAttribute("aria-expanded", next ? "true" : "false");
        if (receipt) receipt.hidden = !next;
        const caret = resultDetailsToggle.querySelector(".result-details-caret");
        if (caret) caret.textContent = next ? "▴" : "▾";
      });
    }
    // Slice 4b: delegated copy for the receipt's ⧉ id buttons — reuses the
    // shared ``copyRunIdToClipboard`` helper so run-id copy stays in lockstep.
    const resultReceiptEl = el("result-receipt");
    if (resultReceiptEl) {
      resultReceiptEl.addEventListener("click", (event) => {
        const target = event.target;
        const button =
          target && target.closest ? target.closest("[data-copy-value]") : null;
        if (!button || !resultReceiptEl.contains(button)) return;
        const value = (button.dataset.copyValue || "").trim();
        if (!value) return;
        copyRunIdToClipboard(button, value, button.dataset.idleTitle || "Copy");
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
    // Slice 5 (06 Transcript): the result view's "Read the full debate
    // transcript →" link opens the audit-trail drill-down; the transcript's
    // "← Back to verdict" header button and its footer link both return to the
    // result view. All three are native <button>s (keyboard operable).
    const transcriptLink = el("result-transcript-link");
    if (transcriptLink) {
      transcriptLink.addEventListener("click", openTranscript);
    }
    const transcriptBack = el("transcript-back");
    if (transcriptBack) {
      transcriptBack.addEventListener("click", () => {
        setView("result");
        focusResultHeading();
      });
    }
    const transcriptFooterLink = el("transcript-footer-link");
    if (transcriptFooterLink) {
      transcriptFooterLink.addEventListener("click", () => {
        setView("result");
        focusResultHeading();
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
