/* W32 (ADR-0134): accept an invite link.
 *
 * The token rides in the URL fragment (#...), which the browser never sends
 * in a request line or a Referer. This script takes it, removes it from the
 * address bar at once, and posts it in a JSON body to /v1/invite, which
 * answers with the invite cookie. It never logs or stores the token.
 */
(function () {
  "use strict";

  // Theme before first paint, the same rule as session-capped.html: the
  // stored choice, else the system preference. tokens.css keys dark mode on
  // data-theme, not on the media query.
  try {
    var stored = window.localStorage.getItem("quorum.theme");
    if (stored === "dark" || stored === "light") {
      document.documentElement.setAttribute("data-theme", stored);
    } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      document.documentElement.setAttribute("data-theme", "light");
    }
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "light");
  }

  document.addEventListener("DOMContentLoaded", accept);

  function accept() {
    var status = document.getElementById("invite-status");

    function say(state, text) {
      status.setAttribute("data-state", state);
      status.textContent = text;
    }

    var token = window.location.hash.replace(/^#/, "");
    // Drop the fragment from the address bar and history before anything else.
    window.history.replaceState(null, "", window.location.pathname);

    if (!token) {
      // A reload after accepting lands here too (the fragment is gone), and
      // the invite is still active then, so do not say it is lost.
      say(
        "missing",
        "If you already opened your invite in this browser, continue. Otherwise ask for a new link."
      );
      return;
    }

    fetch("/v1/invite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ token: token }),
    })
      .then(function (response) {
        if (response.status === 204) {
          say("accepted", "Your invite is accepted. Continue to start.");
        } else if (response.status === 404) {
          say("disabled", "Invite links are not enabled here.");
        } else if (response.status === 429) {
          say("busy", "Too many attempts. Wait a minute and open the link again.");
        } else {
          say("invalid", "This invite link is not valid. Ask for a new one.");
        }
      })
      .catch(function () {
        say("error", "The invite could not be checked. Check your connection and open the link again.");
      });
  }
})();
