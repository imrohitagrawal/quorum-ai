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
    var buckets = {}; // le -> summed count across handlers
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

  refresh();
  window.setInterval(refresh, REFRESH_MS);
})();
