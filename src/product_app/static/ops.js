/* OD-2 ops dashboard client.
 *
 * Same-origin only: fetches /metrics (Prometheus text), /status and /ready
 * (JSON). Every "current" number rendered here is COMPUTED from those live
 * responses on each refresh — nothing is hardcoded. All values land in the
 * DOM via textContent only — never as markup. Sparkline history exists only since
 * page open (labelled as such in the page).
 */
(function () {
  "use strict";

  var REFRESH_MS = 10000;
  var prevTotal = null;
  var prevAt = null;
  var rateHistory = [];

  function $(sel) {
    return document.querySelector(sel);
  }

  function setCurrent(key, text) {
    var el = document.querySelector('[data-current="' + key + '"]');
    if (el) el.textContent = text;
  }

  function setVerdict(key, pass) {
    var el = document.querySelector('[data-verdict="' + key + '"]');
    if (!el) return;
    if (pass === null) {
      el.textContent = "no data yet";
      el.className = "slo-unknown";
    } else if (pass) {
      el.textContent = "PASS";
      el.className = "slo-pass";
    } else {
      el.textContent = "FAIL";
      el.className = "slo-fail";
    }
  }

  /* Minimal Prometheus text-format parsing: only the series the tiles need. */
  function parseMetrics(text) {
    var totals = { all: 0, err5xx: 0 };
    /* Null-prototype: keys come from parsed metric text, so inherited
     * names (__proto__, constructor) must be ordinary keys, never
     * prototype hits. */
    var buckets = Object.create(null); // le -> summed count across handlers
    var lines = text.split("\n");
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (!line || line.charAt(0) === "#") continue;
      var sp = line.lastIndexOf(" ");
      if (sp < 0) continue;
      var name = line.slice(0, sp);
      var value = parseFloat(line.slice(sp + 1));
      if (isNaN(value)) continue;
      if (name.indexOf("http_requests_total{") === 0) {
        totals.all += value;
        if (name.indexOf('status="5xx"') >= 0) totals.err5xx += value;
      } else if (name.indexOf("http_request_duration_seconds_bucket{") === 0) {
        var m = name.match(/le="([^"]+)"/);
        if (m) buckets[m[1]] = (buckets[m[1]] || 0) + value;
      }
    }
    return { totals: totals, buckets: buckets };
  }

  /* Metric-family catalog parsing: every "# HELP"/"# TYPE" comment plus a
   * per-family series count, so the "Metrics, explained" catalog renders
   * the LIVE family set — never a hardcoded list. */
  function parseFamilies(text) {
    /* Null-prototype (review finding): with a plain {}, a family named
     * __proto__ evaluates truthy via Object.prototype — it is silently
     * dropped from the catalog AND `.help = ...` pollutes every object
     * on the page. With no prototype, such names are ordinary keys. */
    var families = Object.create(null); // name -> {name, type, help, series}
    var order = [];
    var lines = text.split("\n");
    var i, line;
    for (i = 0; i < lines.length; i++) {
      line = lines[i];
      if (line.indexOf("# HELP ") === 0) {
        var rest = line.slice(7);
        var sph = rest.indexOf(" ");
        var hname = sph < 0 ? rest : rest.slice(0, sph);
        if (!families[hname]) {
          families[hname] = { name: hname, type: "untyped", help: "", series: 0 };
          order.push(hname);
        }
        families[hname].help = sph < 0 ? "" : rest.slice(sph + 1);
      } else if (line.indexOf("# TYPE ") === 0) {
        var restT = line.slice(7);
        var spt = restT.indexOf(" ");
        var tname = spt < 0 ? restT : restT.slice(0, spt);
        if (!families[tname]) {
          families[tname] = { name: tname, type: "untyped", help: "", series: 0 };
          order.push(tname);
        }
        families[tname].type = spt < 0 ? "untyped" : restT.slice(spt + 1);
      }
    }
    /* Series counts: a sample belongs to a family when its base name is the
     * family name or the family name + a histogram/summary suffix. */
    var suffixes = ["", "_bucket", "_count", "_sum"];
    for (i = 0; i < lines.length; i++) {
      line = lines[i];
      if (!line || line.charAt(0) === "#") continue;
      var brace = line.indexOf("{");
      var space = line.indexOf(" ");
      var end = brace >= 0 && (space < 0 || brace < space) ? brace : space;
      if (end < 0) continue;
      var base = line.slice(0, end);
      for (var s = 0; s < suffixes.length; s++) {
        var candidate = suffixes[s] ? base.slice(0, base.length - suffixes[s].length) : base;
        if (suffixes[s] && base.slice(-suffixes[s].length) !== suffixes[s]) continue;
        if (families[candidate]) {
          families[candidate].series += 1;
          break;
        }
      }
    }
    return order.map(function (name) { return families[name]; });
  }

  var GROUPS = ["http", "process", "python"];

  /* "Used by" honesty: the ONLY families whose samples the tiles read are
   * the two parseMetrics() consumes above — http_requests_total (rate + 5xx
   * tiles) and http_request_duration_seconds, whose _bucket series feed the
   * p95 tile. Keyed off the family NAME so the marker stays truthful as
   * families come and go; any family NOT in this map — including brand-new
   * ones — defaults to informational. */
  var CONSUMED = {
    "http_requests_total": "→ feeds the rate + 5xx error tiles",
    "http_request_duration_seconds": "→ feeds the p95 tile (its _bucket series)",
  };

  function usedByOf(familyName) {
    if (Object.prototype.hasOwnProperty.call(CONSUMED, familyName)) {
      return { text: CONSUMED[familyName], cls: "used-feeds" };
    }
    return { text: "informational — not read by any tile", cls: "used-info" };
  }

  function groupOf(familyName) {
    var prefix = familyName.split("_")[0];
    return GROUPS.indexOf(prefix) >= 0 ? prefix : "other";
  }

  /* Rebuild the catalog tables from the freshly parsed families. DOM nodes
   * are created element-by-element and filled via textContent ONLY — provider
   * help text never becomes markup. */
  function renderCatalog(families) {
    var byGroup = { http: [], process: [], python: [], other: [] };
    for (var i = 0; i < families.length; i++) {
      byGroup[groupOf(families[i].name)].push(families[i]);
    }
    var nonEmptyGroups = 0;
    var keys = ["http", "process", "python", "other"];
    for (var g = 0; g < keys.length; g++) {
      var key = keys[g];
      var body = document.querySelector('[data-group-body="' + key + '"]');
      if (!body) continue;
      while (body.firstChild) body.removeChild(body.firstChild);
      var rows = byGroup[key];
      if (rows.length) nonEmptyGroups += 1;
      var section = document.querySelector('[data-group="' + key + '"]');
      if (section && key === "other") section.hidden = rows.length === 0;
      /* Empty known group (e.g. process_* off-Linux): show the honest
       * empty-state note and hide the bare table headers. */
      var emptyNote = document.querySelector('[data-group-empty="' + key + '"]');
      if (emptyNote) emptyNote.hidden = rows.length > 0;
      var scroll = section ? section.querySelector(".catalog-scroll") : null;
      if (scroll) scroll.hidden = rows.length === 0;
      for (var r = 0; r < rows.length; r++) {
        var tr = document.createElement("tr");
        tr.setAttribute("data-family", rows[r].name);
        var cells = [
          rows[r].name,
          rows[r].type,
          String(rows[r].series),
          rows[r].help,
        ];
        for (var c = 0; c < cells.length; c++) {
          var td = document.createElement("td");
          td.textContent = cells[c];
          tr.appendChild(td);
        }
        /* "Used by" cell — page-authored text, still via textContent only. */
        var usedBy = usedByOf(rows[r].name);
        var usedTd = document.createElement("td");
        usedTd.className = usedBy.cls;
        usedTd.textContent = usedBy.text;
        tr.appendChild(usedTd);
        body.appendChild(tr);
      }
    }
    setCurrent("family-count", String(families.length));
    setCurrent("group-count", String(nonEmptyGroups));
  }

  /* p95 from cumulative histogram buckets, aggregated across handlers.
   * Returns the upper bound of the first bucket whose cumulative count
   * reaches 95% of observations — bucket-derived, labelled so in the page. */
  function p95FromBuckets(buckets) {
    var les = Object.keys(buckets)
      .map(function (le) {
        return { le: le, bound: le === "+Inf" ? Infinity : parseFloat(le), n: buckets[le] };
      })
      .sort(function (a, b) {
        return a.bound - b.bound;
      });
    if (!les.length) return null;
    var total = les[les.length - 1].n;
    if (!total) return null;
    var need = 0.95 * total;
    for (var i = 0; i < les.length; i++) {
      if (les[i].n >= need) {
        return les[i].bound;
      }
    }
    return null;
  }

  function drawSpark(key, history) {
    var svg = document.querySelector('[data-spark="' + key + '"]');
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (history.length < 2) return;
    var max = Math.max.apply(null, history);
    if (max <= 0) max = 1;
    var pts = [];
    for (var i = 0; i < history.length; i++) {
      var x = (i / (history.length - 1)) * 120;
      var y = 26 - (history[i] / max) * 24;
      pts.push(x.toFixed(1) + "," + y.toFixed(1));
    }
    var poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    poly.setAttribute("points", pts.join(" "));
    svg.appendChild(poly);
  }

  function fmtUptime(seconds) {
    var s = Math.floor(seconds);
    var d = Math.floor(s / 86400);
    var h = Math.floor((s % 86400) / 3600);
    var m = Math.floor((s % 3600) / 60);
    if (d > 0) return d + "d " + h + "h " + m + "m";
    if (h > 0) return h + "h " + m + "m";
    return m + "m " + (s % 60) + "s";
  }

  function refresh() {
    Promise.all([
      fetch("/metrics").then(function (r) { return r.text(); }),
      fetch("/status").then(function (r) { return r.json(); }),
      fetch("/ready").then(function (r) { return r.json(); }),
    ])
      .then(function (results) {
        var parsed = parseMetrics(results[0]);
        renderCatalog(parseFamilies(results[0]));
        var statusJson = results[1];
        var readyJson = results[2];
        var now = Date.now();

        /* Request rate: delta between refreshes (needs two scrapes). */
        if (prevTotal !== null && now > prevAt) {
          var rate = (parsed.totals.all - prevTotal) / ((now - prevAt) / 1000);
          if (rate < 0) rate = 0; /* server restarted between scrapes */
          setCurrent("rate", rate.toFixed(2));
          rateHistory.push(rate);
          if (rateHistory.length > 60) rateHistory.shift();
          drawSpark("rate", rateHistory);
        }
        prevTotal = parsed.totals.all;
        prevAt = now;

        /* p95 latency (bucket-derived). */
        var p95 = p95FromBuckets(parsed.buckets);
        if (p95 === null) {
          setCurrent("p95", "—");
          setVerdict("p95", null);
        } else if (p95 === Infinity) {
          setCurrent("p95", "> largest bucket");
          setVerdict("p95", false);
        } else {
          /* Display the bucket's own bound verbatim ("≤ 0.5"), never a
           * toFixed() rendering that implies precision the buckets cannot
           * support. Verdict stays conservative: a bound at/over the SLO
           * reads FAIL even though the true p95 may sit below it. */
          setCurrent("p95", "≤ " + String(p95));
          setVerdict("p95", p95 < 1);
        }

        /* 5xx error rate, process lifetime. */
        if (parsed.totals.all > 0) {
          var pct = (parsed.totals.err5xx / parsed.totals.all) * 100;
          setCurrent("err", pct.toFixed(2));
          setVerdict("err", pct < 1);
        } else {
          setCurrent("err", "—");
          setVerdict("err", null);
        }

        /* Readiness. */
        var live = readyJson.live_readiness || {};
        var state = String(live.state || "unknown");
        setCurrent("ready", state);
        setVerdict("ready", state === "live");
        var reasons = (live.reasons || []).join("; ");
        setCurrent("ready-reasons", reasons ? "reasons: " + reasons : "");

        /* Uptime + version from /status. */
        if (typeof statusJson.uptime_seconds === "number") {
          setCurrent("uptime", fmtUptime(statusJson.uptime_seconds));
        }
        setCurrent("version", String(statusJson.version || "unknown"));
        setCurrent("environment", "environment: " + String(statusJson.environment || "unknown"));

        $("#last-refresh").textContent =
          "Last refresh: " + new Date(now).toLocaleTimeString();
        var errEl = $("#fetch-error");
        errEl.hidden = true;
        errEl.textContent = "";
      })
      .catch(function (err) {
        var errEl = $("#fetch-error");
        errEl.hidden = false;
        errEl.textContent = "fetch failed: " + String(err && err.message ? err.message : err);
      });
  }

  /* Scroll-spy for the jump-bar TOC. IntersectionObserver only — no scroll
   * handler. The TOC links and their targets are static template nodes
   * (refresh() re-renders only table BODIES, never these sections), so the
   * observer is created exactly once for the page's life and never leaks. */
  function initTocSpy() {
    var nav = document.querySelector(".ops-toc");
    if (!nav || typeof IntersectionObserver === "undefined") return;
    var links = nav.querySelectorAll('a[href^="#"]');
    var byId = {};
    var targets = [];
    for (var i = 0; i < links.length; i++) {
      var id = links[i].getAttribute("href").slice(1);
      var el = document.getElementById(id);
      if (el) {
        byId[id] = links[i];
        targets.push(el);
      }
    }
    if (!targets.length) return;
    /* The current-line is READ from the resolved scroll-padding-top so JS
     * and CSS can never drift (cycle-2 finding: a hardcoded 73px only
     * matched 4.5rem at the default 16px root font — an enlarged browser
     * font left the spy one section behind on every click). Re-read on
     * every compute, not once at init: the root font can change
     * mid-session (user text-size setting) and rem-derived padding moves
     * with it. One getComputedStyle per recompute — recomputes are
     * event-driven and rare, never per-frame. */
    function currentLine() {
      var pad = parseFloat(
        window.getComputedStyle(document.documentElement).scrollPaddingTop
      );
      return (isNaN(pad) || pad <= 0 ? 72 : pad) + 1;
    }
    /* Classic scroll-spy: the LAST target whose top has passed the sticky
     * bar's lower edge (the scroll-padding line, +1 for rounding) is
     * current. Position-based, so the final section still wins when the
     * page bottom-clamps an anchor jump and several sections straddle the
     * bar. Falls back to the first target above the fold. */
    function computeCurrent() {
      var line = currentLine();
      var currentId = targets[0].id;
      for (var t = 0; t < targets.length; t++) {
        if (targets[t].getBoundingClientRect().top <= line) {
          currentId = targets[t].id;
        }
      }
      for (var l = 0; l < targets.length; l++) {
        var link = byId[targets[l].id];
        if (targets[l].id === currentId) {
          link.setAttribute("aria-current", "location");
        } else {
          link.removeAttribute("aria-current");
        }
      }
    }
    /* The observer is purely the TRIGGER (no scroll handler, no jank):
     * every intersection change recomputes, and a trailing 150ms settle
     * recompute covers the gap between the last intersection change and
     * where smooth scrolling actually stops. DENSE thresholds (every 0.5%
     * of a section's height) — cycle-2 finding: with the default single
     * threshold, a tall section's top could cross the current-line
     * mid-band without ANY event, leaving aria-current stale for a manual
     * scroll that stops there (~160px stale zone). Dense steps shrink
     * that to a few px and re-arm the settle recompute continuously. */
    var thresholds = [];
    for (var th = 0; th <= 200; th++) thresholds.push(th / 200);
    var settle = null;
    var observer = new IntersectionObserver(
      function () {
        computeCurrent();
        if (settle !== null) window.clearTimeout(settle);
        settle = window.setTimeout(computeCurrent, 150);
      },
      {
        /* Margin is fixed at observe-time (observers cannot re-margin);
         * it only shapes TRIGGER timing — the chosen section always comes
         * from computeCurrent's live currentLine(). */
        rootMargin: "-" + Math.round(currentLine() - 1) + "px 0px -50% 0px",
        threshold: thresholds,
      }
    );
    for (var o = 0; o < targets.length; o++) observer.observe(targets[o]);
    /* Exact final correction where supported (Chrome 114+/FF 109+/Safari
     * 18.4+): scrollend fires ONCE when scrolling stops — not a per-frame
     * scroll handler, no jank. Older engines rely on the dense-threshold
     * settle above. */
    if ("onscrollend" in window) {
      window.addEventListener("scrollend", computeCurrent);
    }
    /* A TOC click's smooth scroll can outlive the last intersection
     * change (observed on Firefox: the settle recompute ran mid-scroll
     * and the spy stuck one section behind). On click, poll scrollY via
     * requestAnimationFrame — NOT a scroll handler — and recompute once
     * the position has been still for ~30 frames (capped at ~10s).
     * 30, not 3: smooth scrolling starts ASYNCHRONOUSLY after the click
     * (Firefox), so a short stillness window can elapse before any
     * movement and freeze the spy one section behind. */
    nav.addEventListener("click", function () {
      var lastY = null;
      var still = 0;
      var frames = 0;
      function tick() {
        frames += 1;
        if (window.scrollY === lastY) {
          still += 1;
        } else {
          still = 0;
          lastY = window.scrollY;
        }
        if (still >= 30 || frames > 600) {
          computeCurrent();
        } else {
          window.requestAnimationFrame(tick);
        }
      }
      window.requestAnimationFrame(tick);
    });
    computeCurrent();
  }

  initTocSpy();
  refresh();
  window.setInterval(refresh, REFRESH_MS);
})();
