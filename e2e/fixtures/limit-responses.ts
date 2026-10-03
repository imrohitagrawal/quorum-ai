/**
 * W33 slice C (ADR-0141): server-shaped estimate and create responses, one per
 * limit the server can name.
 *
 * NOT hand-written. Every object below is a response the REAL server returned
 * on 2026-10-03 at dcd2d62 (FastAPI TestClient, live execution off, the
 * pinned static catalog of tests/integration/test_query_run_cost_guardrails.py),
 * with only the random ``correlation_id`` and ``confirmation_token`` replaced by
 * fixed strings. How each was reached:
 *
 *   perRunCap                  opus-tier panel, 12,000-character query (0.5963 / worst 0.6228)
 *   dailyCap                   three default-panel runs, then the estimate (spent 0.3156)
 *   dailyCapLargerThanADay     confirm-band panel, 12,000 characters (0.4013 / worst 0.4278)
 *   accountRunningTotal        0.4500 on the in-memory total, ledger empty
 *   ledgerUnavailable          fail-closed on, a reopen tried, ledger untrustworthy
 *   allowBoundedByRunningTotal 0.3000 on the in-memory total: remaining 0.2000, bounded_by running_total
 *   allowAllowanceUnavailable  the ADR-0016 degrade path: daily_allowance null
 *   createChargeTimeDailyCap   the charge-time OVER_DAILY_CAP 402 (another tab booked 0.3500)
 *   createChargeTimeDailyCapNoAllowance  the same 402 when the fresh allowance read fails
 *                              (ADR-0141 decision 8; only daily_allowance differs)
 *
 * They exist so a page test never renders a combination the server cannot
 * produce (failure-mode row 14 of
 * docs/analysis/2026-10-03-w33c-limit-messages-failure-modes.md: the old
 * fixtures put a $0.30 total under a "$0.25 hard cap" block).
 */
export const LIMIT_RESPONSES = {
  "perRunCap": {
    "correlation_id": "estimate_fixture_per_run_cap",
    "cost_estimate": {
      "estimated_cost_usd": "0.5963",
      "currency": "USD",
      "threshold_action": "block",
      "confirmation_token": null,
      "reasons": [
        "Worst-case cost could exceed the USD 0.50 hard limit for this account."
      ],
      "max_cost_usd": "0.6228",
      "breakdown": {
        "by_model": [
          {
            "model_id": "openai/gpt-4.1",
            "display_name": "GPT-4.1",
            "usd": "0.0337",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-opus-4",
            "display_name": "Claude Opus 4",
            "usd": "0.2373",
            "kind": "model"
          },
          {
            "model_id": "google/gemini-2.5-pro",
            "display_name": "Gemini 2.5 Pro",
            "usd": "0.0237",
            "kind": "model"
          },
          {
            "model_id": "openai/o3",
            "display_name": "o3",
            "usd": "0.2072",
            "kind": "model"
          },
          {
            "model_id": "synthesis",
            "display_name": "Synthesis",
            "usd": "0.0944",
            "kind": "synthesis"
          }
        ],
        "by_stage": [
          {
            "stage": "initial_answers",
            "usd": "0.5020"
          },
          {
            "stage": "debate_round_1",
            "usd": "0.0223"
          },
          {
            "stage": "debate_round_2",
            "usd": "0.0223"
          },
          {
            "stage": "synthesis",
            "usd": "0.0497"
          }
        ],
        "total": "0.5963"
      },
      "global_ceiling_reached": false,
      "spend_metering_unavailable": false,
      "block_reason": "per_run_cap",
      "daily_allowance": {
        "cap_usd": "0.40",
        "spent_usd": "0.0000",
        "remaining_usd": "0.4000",
        "bounded_by": "daily_cap"
      }
    },
    "model_slots": [
      {
        "slot_number": 1,
        "model_id": "openai/gpt-4.1",
        "search": true
      },
      {
        "slot_number": 2,
        "model_id": "anthropic/claude-opus-4",
        "search": true
      },
      {
        "slot_number": 3,
        "model_id": "google/gemini-2.5-pro",
        "search": true
      },
      {
        "slot_number": 4,
        "model_id": "openai/o3",
        "search": true
      }
    ],
    "reasons": [
      "Estimated cost exceeds USD 0.50 and is blocked for this slice."
    ]
  },
  "dailyCap": {
    "correlation_id": "estimate_fixture_daily_cap",
    "cost_estimate": {
      "estimated_cost_usd": "0.1052",
      "currency": "USD",
      "threshold_action": "block",
      "confirmation_token": null,
      "reasons": [
        "This run would take the account past its USD 0.40 daily cap.",
        "Account has spent 0.3156 USD in the last 24 hours; spend frees up as each run turns 24 hours old."
      ],
      "max_cost_usd": "0.1593",
      "breakdown": {
        "by_model": [
          {
            "model_id": "openai/gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "usd": "0.0078",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-haiku-4.5",
            "display_name": "Claude Haiku 4.5",
            "usd": "0.0129",
            "kind": "model"
          },
          {
            "model_id": "google/gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "usd": "0.0095",
            "kind": "model"
          },
          {
            "model_id": "nvidia/nemotron-3-nano-30b-a3b",
            "display_name": "Nemotron 3 Nano",
            "usd": "0.0072",
            "kind": "model"
          },
          {
            "model_id": "synthesis",
            "display_name": "Synthesis",
            "usd": "0.0678",
            "kind": "synthesis"
          }
        ],
        "by_stage": [
          {
            "stage": "initial_answers",
            "usd": "0.0374"
          },
          {
            "stage": "debate_round_1",
            "usd": "0.0142"
          },
          {
            "stage": "debate_round_2",
            "usd": "0.0142"
          },
          {
            "stage": "synthesis",
            "usd": "0.0394"
          }
        ],
        "total": "0.1052"
      },
      "global_ceiling_reached": false,
      "spend_metering_unavailable": false,
      "block_reason": "daily_cap",
      "daily_allowance": {
        "cap_usd": "0.40",
        "spent_usd": "0.3156",
        "remaining_usd": "0.0844",
        "bounded_by": "daily_cap"
      }
    },
    "model_slots": [
      {
        "slot_number": 1,
        "model_id": "openai/gpt-4o-mini",
        "search": true
      },
      {
        "slot_number": 2,
        "model_id": "anthropic/claude-haiku-4.5",
        "search": true
      },
      {
        "slot_number": 3,
        "model_id": "google/gemini-2.5-flash",
        "search": true
      },
      {
        "slot_number": 4,
        "model_id": "nvidia/nemotron-3-nano-30b-a3b",
        "search": true
      }
    ],
    "reasons": [
      "This run would take the account past its USD 0.40 cap for the last 24 hours and is blocked."
    ]
  },
  "dailyCapLargerThanADay": {
    "correlation_id": "estimate_fixture_daily_larger",
    "cost_estimate": {
      "estimated_cost_usd": "0.4013",
      "currency": "USD",
      "threshold_action": "block",
      "confirmation_token": null,
      "reasons": [
        "This run's estimate of 0.4013 USD is larger than the account's whole USD 0.40 allowance for 24 hours, so it will not fit however long you wait.",
        "Choose lower-cost models or shorten the question."
      ],
      "max_cost_usd": "0.4278",
      "breakdown": {
        "by_model": [
          {
            "model_id": "openai/gpt-4.1",
            "display_name": "GPT-4.1",
            "usd": "0.0337",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-haiku-4.5",
            "display_name": "Claude Haiku 4.5",
            "usd": "0.0224",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-opus-4",
            "display_name": "Claude Opus 4",
            "usd": "0.2372",
            "kind": "model"
          },
          {
            "model_id": "google/gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "usd": "0.0136",
            "kind": "model"
          },
          {
            "model_id": "synthesis",
            "display_name": "Synthesis",
            "usd": "0.0944",
            "kind": "synthesis"
          }
        ],
        "by_stage": [
          {
            "stage": "initial_answers",
            "usd": "0.3070"
          },
          {
            "stage": "debate_round_1",
            "usd": "0.0223"
          },
          {
            "stage": "debate_round_2",
            "usd": "0.0223"
          },
          {
            "stage": "synthesis",
            "usd": "0.0497"
          }
        ],
        "total": "0.4013"
      },
      "global_ceiling_reached": false,
      "spend_metering_unavailable": false,
      "block_reason": "daily_cap",
      "daily_allowance": {
        "cap_usd": "0.40",
        "spent_usd": "0.0000",
        "remaining_usd": "0.4000",
        "bounded_by": "daily_cap"
      }
    },
    "model_slots": [
      {
        "slot_number": 1,
        "model_id": "openai/gpt-4.1",
        "search": true
      },
      {
        "slot_number": 2,
        "model_id": "anthropic/claude-haiku-4.5",
        "search": true
      },
      {
        "slot_number": 3,
        "model_id": "anthropic/claude-opus-4",
        "search": true
      },
      {
        "slot_number": 4,
        "model_id": "google/gemini-2.5-flash",
        "search": true
      }
    ],
    "reasons": [
      "This run would take the account past its USD 0.40 cap for the last 24 hours and is blocked."
    ]
  },
  "accountRunningTotal": {
    "correlation_id": "estimate_fixture_running_total",
    "cost_estimate": {
      "estimated_cost_usd": "0.1052",
      "currency": "USD",
      "threshold_action": "block",
      "confirmation_token": null,
      "reasons": [
        "This run would take the account's recent spend past its USD 0.50 running limit.",
        "Cumulative spend for this account is 0.4500 USD."
      ],
      "max_cost_usd": "0.1593",
      "breakdown": {
        "by_model": [
          {
            "model_id": "openai/gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "usd": "0.0078",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-haiku-4.5",
            "display_name": "Claude Haiku 4.5",
            "usd": "0.0129",
            "kind": "model"
          },
          {
            "model_id": "google/gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "usd": "0.0095",
            "kind": "model"
          },
          {
            "model_id": "nvidia/nemotron-3-nano-30b-a3b",
            "display_name": "Nemotron 3 Nano",
            "usd": "0.0072",
            "kind": "model"
          },
          {
            "model_id": "synthesis",
            "display_name": "Synthesis",
            "usd": "0.0678",
            "kind": "synthesis"
          }
        ],
        "by_stage": [
          {
            "stage": "initial_answers",
            "usd": "0.0374"
          },
          {
            "stage": "debate_round_1",
            "usd": "0.0142"
          },
          {
            "stage": "debate_round_2",
            "usd": "0.0142"
          },
          {
            "stage": "synthesis",
            "usd": "0.0394"
          }
        ],
        "total": "0.1052"
      },
      "global_ceiling_reached": false,
      "spend_metering_unavailable": false,
      "block_reason": "account_running_total",
      "daily_allowance": {
        "cap_usd": "0.40",
        "spent_usd": "0.0000",
        "remaining_usd": "0.0500",
        "bounded_by": "running_total"
      }
    },
    "model_slots": [
      {
        "slot_number": 1,
        "model_id": "openai/gpt-4o-mini",
        "search": true
      },
      {
        "slot_number": 2,
        "model_id": "anthropic/claude-haiku-4.5",
        "search": true
      },
      {
        "slot_number": 3,
        "model_id": "google/gemini-2.5-flash",
        "search": true
      },
      {
        "slot_number": 4,
        "model_id": "nvidia/nemotron-3-nano-30b-a3b",
        "search": true
      }
    ],
    "reasons": [
      "This run would take the account's recent spend past its USD 0.50 running limit and is blocked."
    ]
  },
  "ledgerUnavailable": {
    "correlation_id": "estimate_fixture_ledger",
    "cost_estimate": {
      "estimated_cost_usd": "0.1052",
      "currency": "USD",
      "threshold_action": "block",
      "confirmation_token": null,
      "reasons": [
        "The daily spend ledger is not writable and a reconnect attempt has already been made without restoring it, so no account's 24h cap can be verified right now. This is a storage fault on the shared ledger, not a limit this account has reached."
      ],
      "max_cost_usd": "0.1593",
      "breakdown": {
        "by_model": [
          {
            "model_id": "openai/gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "usd": "0.0078",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-haiku-4.5",
            "display_name": "Claude Haiku 4.5",
            "usd": "0.0129",
            "kind": "model"
          },
          {
            "model_id": "google/gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "usd": "0.0095",
            "kind": "model"
          },
          {
            "model_id": "nvidia/nemotron-3-nano-30b-a3b",
            "display_name": "Nemotron 3 Nano",
            "usd": "0.0072",
            "kind": "model"
          },
          {
            "model_id": "synthesis",
            "display_name": "Synthesis",
            "usd": "0.0678",
            "kind": "synthesis"
          }
        ],
        "by_stage": [
          {
            "stage": "initial_answers",
            "usd": "0.0374"
          },
          {
            "stage": "debate_round_1",
            "usd": "0.0142"
          },
          {
            "stage": "debate_round_2",
            "usd": "0.0142"
          },
          {
            "stage": "synthesis",
            "usd": "0.0394"
          }
        ],
        "total": "0.1052"
      },
      "global_ceiling_reached": false,
      "spend_metering_unavailable": false,
      "block_reason": "ledger_unavailable",
      "daily_allowance": null
    },
    "model_slots": [
      {
        "slot_number": 1,
        "model_id": "openai/gpt-4o-mini",
        "search": true
      },
      {
        "slot_number": 2,
        "model_id": "anthropic/claude-haiku-4.5",
        "search": true
      },
      {
        "slot_number": 3,
        "model_id": "google/gemini-2.5-flash",
        "search": true
      },
      {
        "slot_number": 4,
        "model_id": "nvidia/nemotron-3-nano-30b-a3b",
        "search": true
      }
    ],
    "reasons": [
      "The daily spend ledger cannot be verified right now, so this run is blocked. This is a storage fault, not a limit this account has reached."
    ]
  },
  "allowBoundedByRunningTotal": {
    "correlation_id": "estimate_fixture_allow_running",
    "cost_estimate": {
      "estimated_cost_usd": "0.1052",
      "currency": "USD",
      "threshold_action": "allow",
      "confirmation_token": "cost_v1_fixture_token",
      "reasons": [
        "Worst-case cost is within the no-confirmation band."
      ],
      "max_cost_usd": "0.1593",
      "breakdown": {
        "by_model": [
          {
            "model_id": "openai/gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "usd": "0.0078",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-haiku-4.5",
            "display_name": "Claude Haiku 4.5",
            "usd": "0.0129",
            "kind": "model"
          },
          {
            "model_id": "google/gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "usd": "0.0095",
            "kind": "model"
          },
          {
            "model_id": "nvidia/nemotron-3-nano-30b-a3b",
            "display_name": "Nemotron 3 Nano",
            "usd": "0.0072",
            "kind": "model"
          },
          {
            "model_id": "synthesis",
            "display_name": "Synthesis",
            "usd": "0.0678",
            "kind": "synthesis"
          }
        ],
        "by_stage": [
          {
            "stage": "initial_answers",
            "usd": "0.0374"
          },
          {
            "stage": "debate_round_1",
            "usd": "0.0142"
          },
          {
            "stage": "debate_round_2",
            "usd": "0.0142"
          },
          {
            "stage": "synthesis",
            "usd": "0.0394"
          }
        ],
        "total": "0.1052"
      },
      "global_ceiling_reached": false,
      "spend_metering_unavailable": false,
      "block_reason": null,
      "daily_allowance": {
        "cap_usd": "0.40",
        "spent_usd": "0.0000",
        "remaining_usd": "0.2000",
        "bounded_by": "running_total"
      }
    },
    "model_slots": [
      {
        "slot_number": 1,
        "model_id": "openai/gpt-4o-mini",
        "search": true
      },
      {
        "slot_number": 2,
        "model_id": "anthropic/claude-haiku-4.5",
        "search": true
      },
      {
        "slot_number": 3,
        "model_id": "google/gemini-2.5-flash",
        "search": true
      },
      {
        "slot_number": 4,
        "model_id": "nvidia/nemotron-3-nano-30b-a3b",
        "search": true
      }
    ],
    "reasons": [
      "Estimated cost is within the normal execution band."
    ]
  },
  "allowAllowanceUnavailable": {
    "correlation_id": "estimate_fixture_allow_null",
    "cost_estimate": {
      "estimated_cost_usd": "0.1052",
      "currency": "USD",
      "threshold_action": "allow",
      "confirmation_token": "cost_v1_fixture_token",
      "reasons": [
        "Worst-case cost is within the no-confirmation band."
      ],
      "max_cost_usd": "0.1593",
      "breakdown": {
        "by_model": [
          {
            "model_id": "openai/gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "usd": "0.0078",
            "kind": "model"
          },
          {
            "model_id": "anthropic/claude-haiku-4.5",
            "display_name": "Claude Haiku 4.5",
            "usd": "0.0129",
            "kind": "model"
          },
          {
            "model_id": "google/gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "usd": "0.0095",
            "kind": "model"
          },
          {
            "model_id": "nvidia/nemotron-3-nano-30b-a3b",
            "display_name": "Nemotron 3 Nano",
            "usd": "0.0072",
            "kind": "model"
          },
          {
            "model_id": "synthesis",
            "display_name": "Synthesis",
            "usd": "0.0678",
            "kind": "synthesis"
          }
        ],
        "by_stage": [
          {
            "stage": "initial_answers",
            "usd": "0.0374"
          },
          {
            "stage": "debate_round_1",
            "usd": "0.0142"
          },
          {
            "stage": "debate_round_2",
            "usd": "0.0142"
          },
          {
            "stage": "synthesis",
            "usd": "0.0394"
          }
        ],
        "total": "0.1052"
      },
      "global_ceiling_reached": false,
      "spend_metering_unavailable": true,
      "block_reason": null,
      "daily_allowance": null
    },
    "model_slots": [
      {
        "slot_number": 1,
        "model_id": "openai/gpt-4o-mini",
        "search": true
      },
      {
        "slot_number": 2,
        "model_id": "anthropic/claude-haiku-4.5",
        "search": true
      },
      {
        "slot_number": 3,
        "model_id": "google/gemini-2.5-flash",
        "search": true
      },
      {
        "slot_number": 4,
        "model_id": "nvidia/nemotron-3-nano-30b-a3b",
        "search": true
      }
    ],
    "reasons": [
      "Estimated cost is within the normal execution band."
    ]
  },
  "createChargeTimeDailyCap": {
    "detail": {
      "code": "COST_LIMIT_EXCEEDED",
      "message": "This run would take the account past its USD 0.40 cap for the last 24 hours; spend frees up as each run turns 24 hours old.",
      "block_reason": "daily_cap",
      "daily_allowance": {
        "cap_usd": "0.40",
        "spent_usd": "0.3500",
        "remaining_usd": "0.0500",
        "bounded_by": "daily_cap"
      }
    }
  },
  "createChargeTimeDailyCapNoAllowance": {
    "detail": {
      "code": "COST_LIMIT_EXCEEDED",
      "message": "This run would take the account past its USD 0.40 cap for the last 24 hours; spend frees up as each run turns 24 hours old.",
      "block_reason": "daily_cap",
      "daily_allowance": null
    }
  }
} as const;
