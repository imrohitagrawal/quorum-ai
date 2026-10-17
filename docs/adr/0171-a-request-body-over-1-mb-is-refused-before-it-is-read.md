# ADR-0171: A request body over 1 MB is refused before it is read, and the request models bound what a body may hold

## Status

Accepted — 2026-10-17, board row W85. The limit, 1 MB (1,048,576 bytes), and "413 before it is
read" are the product owner's (CHG-063 (a)), and so are the list bounds and the 20-error cap of
decisions 6 and 7, which the session chose and the owner then approved (CHG-064). Everything else
below is the session's design. The
failure modes were listed before any code
(`docs/analysis/2026-10-17-w85-request-body-limit-failure-modes.md`, findings A1 to A12). Codex
reviewed the plan before any code (ADR-0168, decision 7): it found five problems, the plan was
revised, and a second Codex pass confirmed all five closed in the plan and found one more defect in a
planned test, which was fixed before the test was written.

**Amends ADR-0120 decision 6** ("The API edge is not bounded to the range"): `model_slots` and
`slot_search` are now bounded at the edge, at 16 items. See decision 6 below.

## Context

Before W85 nothing limited the size of a request body. The server read the whole body, and parsed it
when it was JSON, before it checked the session. Production is one machine with 512 MB
(`fly.toml`, `memory = "512mb"`) running one worker (`Dockerfile`, `--workers 1`). So one request
could take the memory of the only process.

A body under any sensible limit could still do damage, through the 422 answer. Pydantic builds one
error per bad item, and the app's 422 handler returned every one of them.

## Measured

"Before" figures come from the failure-modes list, the owner's question in CHG-063 (a) and the two
Codex plan reviews; each was measured in-process (FastAPI's `TestClient`, or a raw ASGI call), not
in production. "After" figures were measured by the docs session on the W85 branch at `92b6ca6`,
in-process, with `TestClient` and `tracemalloc`, from a scratch folder (the probe printed that it
imported `src/product_app/main.py` from the W85 worktree).

| Case | Before W85 | After W85 |
|---|---|---|
| 200 MB body to `POST /v1/query-runs`, no cookie | read in full, then `401`; test process peak memory 108 MB to 907 MB (client and server in one process; CHG-063 (a)) | `413`, 94-byte answer, traced peak 0.1 MB |
| 1,000,034-byte estimate body, `model_slots: [1, 1, ...]` (500,000 items) | `422`, 500,000 `field_errors`, 47.4 MB answer, 521 MB Python peak, 7.3 s (A1) | `422`, 1 field error, 240-byte answer, traced peak 6.4 MB, 0.22 s |
| `context` with 80,000 keys and integer values, 868,942 bytes | `422`, 80,000 `field_errors`, 7.3 MB answer, 89 MB peak (A1, a body of the same shape) | `422`, 1 field error, 252-byte answer, traced peak 9.4 MB, 0.06 s |
| 111,000 unknown top-level keys, under 1 MB | let through, unknown keys ignored; with plain `extra="forbid"` added: 111,000 errors, 9.5 MB answer, 130 MB peak, 1.8 s (A2) | `422`, 1 field error, 245-byte answer, traced peak 15.4 MB, 0.09 s (884,072-byte body) |
| 85,000 unknown keys to `/v1/account/delete` (its model already had `extra="forbid"`) | 85,000 errors, 78,377,407 traced bytes (Codex plan review 2) | 1 error (`tests/integration/test_validation_error_amplifier.py::test_85_000_unknown_keys_to_the_already_strict_routes_get_one_error`) |
| A buffer that keeps each received message, 1,000,000 one-byte messages | 192,439,240 bytes held for a 1,000,000-byte body (Codex plan review 1, a standalone probe) | one `bytearray`; the test's traced peak must stay under 16 MB (`tests/unit/test_request_body_limit_middleware.py::test_a_million_one_byte_messages_are_coalesced_and_memory_stays_bounded`) |
| `Content-Length: 5` with chunked framing, under h11 | the app received 2,097,152 bytes (A4) | `413`: bytes are counted, whatever the header says |
| One unknown `context` key of about 1 MB | 2,000,274-byte answer from a 1,000,058-byte request: the message repeated the key (Codex plan review 5) | fixed message; the answer does not contain the key (`tests/integration/test_validation_error_amplifier.py::test_a_context_with_one_900_kb_unknown_key_is_refused_without_echoing_it`) |

Where the limit sits decides what the 413 carries (A8, measured in fresh processes):

| Where the limit is added | Security headers | `X-Request-ID` | Counted in `/metrics` |
|---|---|---|---|
| after the security-headers function (outermost) | no | no | no |
| between the request-id layer and the security-headers function | yes | no | no |
| just before the request-id layer | yes | yes | no |
| before `.instrument(app)` (innermost), the choice | yes | yes | yes, as `4xx` |

## Decision

1. **The limit is 1,048,576 bytes, inclusive** (CHG-063 (a)). It is `MAX_REQUEST_BODY_BYTES` in
   `src/product_app/request_limits.py`. The largest body the page sends is about 100 KB: a
   20,000-character question plus a follow-up context of up to 80,117 characters. Escaping control
   characters can grow that to about 600 KB, still under the limit.
2. **A body over the limit gets `413` before it is read.** The answer is the app's usual envelope:
   `{"detail": {"code": "REQUEST_TOO_LARGE", "message": "The request is larger than the 1 MB
   limit."}}`, with `Content-Type: application/json`. Answering before reading is the point: a
   refusal after reading would already have spent the memory. The answer does not send
   `Connection: close`: with it, a client still sending saw a reset; without it, uvicorn reads and
   discards the rest of the body, holding no memory for it (A6). The page already shows "The request
   was too large to send." for a 413 (`static/app.js`).
3. **The bytes are always counted.** A `Content-Length` over the limit is refused at once, without
   calling the app. Any other body is counted as it arrives, whatever the header says. Under h11,
   `Content-Length: 5` with chunked framing delivered 2 MB to the app (A4); httptools refuses that
   request, but uvicorn falls back to h11 when httptools cannot be imported. The header is parsed
   strictly: plain ASCII digits only. Python's `int()` accepts `1_0`, `+5`, spaces and non-ASCII
   digits, and raises on `abc`, which would be a 500. Anything that is not plain digits is left to
   the server, which answers 400 for it before the app runs, and the body is counted either way.
4. **The body is kept in one `bytearray` and handed to the app as one message.** Keeping each
   received message instead cost about 192 bytes per message (Codex plan review 1). The buffer is
   dropped before the app runs, so at most one second copy of at most 1 MB exists for a moment. If
   the client leaves mid-body, the app is still called, with what was read and then the disconnect,
   so FastAPI answers its usual 400. Returning without calling the app made the security-headers
   layer raise "No response returned." and send a 500 (A3).
5. **The limit is the innermost layer** (added first in `main.py`, before `.instrument(app)`). So
   the 413 carries the security headers and `X-Request-ID`, and `/metrics` counts it, grouped as
   `4xx` with 401 and 422 (table above).
6. **The request lists are bounded: `model_slots` and `slot_search` at 16 items,
   `safety_acknowledgements` at 8.** This amends ADR-0120 decision 6, which kept the edge unbounded
   so a wrong slot count gets the typed `INVALID_MODEL_SLOT` answer, not Pydantic's generic
   `VALIDATION_ERROR`. The bound is 16, not the panel's 4, so every count from 5 to 16 still reaches
   the domain check and keeps the typed answer; only above 16 is the answer generic. A list bound
   stops Pydantic at one error (A1). There are 2 warning types; 8 leaves room for repeats.
7. **A 422 returns at most the first 20 field errors**, and the banner code is picked from those
   20 alone, so it never names an error the answer does not show. The list bounds stop most floods
   at one error; this cap bounds whatever is left.
8. **An unknown field is refused, as one error however many are sent.** The query-run models, the
   acknowledgement and the cost confirmation now set `extra="forbid"`, kept so the OpenAPI document
   says `additionalProperties: false`. Alone, `extra="forbid"` builds one error per unknown key (A2),
   so each of those models, and `AccountDeleteRequest` and `InviteAcceptRequest`, which already
   forbade extras, also run `refuse_unknown_fields` before field validation. It is wired as
   `model_validator(mode="before")(refuse_unknown_fields)` in the class body, not with decorator
   syntax: `tests/unit/test_mutation_test_set_integrity.py` caps the decorated functions under
   `src/product_app` at 55, and the tree is at 55.
9. **An unknown `context` key is refused before its value is checked, with a fixed message.** A
   `BeforeValidator` lets `None` through (the schema allows `context: null`) and refuses a dict with
   any key other than `prior_question` and `prior_synthesis`. The message names only the allowed
   keys, never the ones sent; the old message listed them, so one large key came back at about twice its size.
10. **The 413 is declared in the OpenAPI document** on every operation there that takes a body:
    estimate, create and warnings, the three the document lists with a request body. It goes
    through the routes' `responses=` argument, so Schemathesis's status-code check knows the
    middleware can answer it (Codex plan review 4).

## Rejected alternatives

- **Trust `Content-Length` when it is present and under the limit.** Beaten by a lying header under
  h11 (A4). Counting costs nothing extra, because the body is read anyway.
- **Skip buffering for GET and HEAD.** Rejected because Sentry's request integration reads a GET
  body before the handler (reproduced on h11 by Codex, round 2), and nothing pins that no GET route
  reads a body.
- **Keep the received messages in a list and replay them.** 192 MB held for 1,000,000 one-byte
  messages (Codex plan review 1).
- **Return without calling the app when the client leaves mid-body.** A 500 and an ERROR log (A3).
- **Add the limit last (outermost), as `add_middleware` order suggests at first reading.** The 413
  then has no security headers and no `X-Request-ID`, and is not counted (A8).
- **Bound `model_slots` at 4.** ADR-0120 decision 6 measured a `min_length=max_length=4` bound:
  `test_create_query_run_with_wrong_slot_count_preserves_typed_envelope`, which sends ONE slot, went
  RED because the typed `INVALID_MODEL_SLOT` answer became generic. The typed answer for 5 slots is
  pinned by
  `tests/integration/test_panel_size_api_and_workspace.py::test_estimate_refuses_one_and_five_slots_with_the_range_message`.
- **Rely on `extra="forbid"` alone.** It creates a new flood: one error per unknown key (A2).
- **Rely on the 20-error cap alone.** It shortens the answer but not the work: 85,000 errors were
  still built, at 78 MB traced, before the cap could cut them (Codex plan review 2).
- **Raise the decorated-function cap to fit decorated validators.** The cap belongs to the mutation
  study; plain functions wired without decorator syntax do the same job.
- **512 KB or 4 MB.** The other two options the owner was offered (CHG-063 (a)).

## Consequences

- A body over 1 MB from any client gets 413 with no session needed, before any work. A client that
  sends unknown fields now gets 422 where it was silently let through. The page (`app.js`) sends no unknown
  field. Two other senders did: `e2e/tests/navigation/navigation.spec.ts:58` and `:71` send
  `model_ids`, which is not a field, and that spec accepts the 422; and two tests in
  `tests/integration/test_quick_mode_backend.py` sent `safety_acknowledgements` to `/estimate`, which
  commit `92b6ca6` changed (failure modes, section C).
- The list of security measures gains SC-98 (the size limit) and SC-99 (the request-model bounds)
  in `docs/41-security-controls.md`.
- **Left open, recorded as advisory, none built here:**
  - **A5, many bodies at once.** Many requests of just under 1 MB, sent at once, still cost the
    server far more memory than one does. It was measured locally after the build; the figures are
    held back until board row W102 ships (the session's reading of CHG-060, not an owner decision).
    Fly's connection limit is 100 (`fly.toml`, `hard_limit`). Limits at scale are also row W94's.
  - **A7, no counter of its own for 413.** `/metrics` groups it with 401 and 422 as `4xx`.
  - **A10, strings with no length bound.** A model id, an acknowledgement's `version` and a cost
    confirmation's token rely on the 1 MB limit alone. A too-long string would map to the misleading
    `QUERY_TOO_LONG` banner code today, so it needs its own change.
  - **A12, a body that does not arrive.** A request that declares a length and does not send it
    now waits for it on every route, as a body-reading route already did on main; real clients send
    the body or `Content-Length: 0`.
  - **Sentry reads request bodies.** Sentry's FastAPI integration reads request bodies by default
    (`max_request_body_size` is not set in `main.py`'s Sentry options); whether a body reaches
    Sentry is for W76 to check.
  - **What Fly's proxy does with an early 413** (whether a browser gets the 413, a 502 or a reset)
    is UNVERIFIED: no production probe was made.
  - **Under `TestClient` only**, a `Content-Length` such as `abc` makes the Prometheus
    instrumentator raise after the answer, because it calls `int()` on the header and sits outside
    the limit. A real server answers 400 for such a header before the app runs (failure modes,
    section B). `tests/integration/test_request_body_limit_api.py` notes this and tests only the
    values `int()` accepts on the real app.
