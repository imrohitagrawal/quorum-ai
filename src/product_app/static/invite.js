/* W32 (ADR-0134): accept an invite link.
 *
 * The token rides in the URL fragment (#...), which the browser never sends
 * in a request line or a Referer. This script takes it, removes it from the
 * address bar at once, and posts it in a JSON body to /v1/invite, which
 * answers with the invite cookie. It never logs or stores the token.
 */
(function () {
  "use strict";
  var status = document.getElementById("invite-status");

  function say(state, text) {
    status.setAttribute("data-state", state);
    status.textContent = text;
  }

  var token = window.location.hash.replace(/^#/, "");
  // Drop the fragment from the address bar and history before anything else.
  window.history.replaceState(null, "", window.location.pathname);

  if (!token) {
    say("missing", "This link has no invite in it. Ask for a new link.");
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
})();
