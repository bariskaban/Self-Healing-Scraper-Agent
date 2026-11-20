"""Settings of the learning and repair agent. Built with `AgentSettings.from_env()`.

Every number here is our own choice (CLAUDE.md, "Source of truth"; CONVENTIONS.md, rule 7), so it
is a setting and not a constant in the logic. Each field can be overridden by AGENT_<NAME>.
The models themselves and their prices are in `app/config.py`.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class AgentSettings:
    # Model calls one run may make (CONVENTIONS.md, rule 7).
    learn_max_turns: int = 40
    repair_max_turns: int = 20
    # What one run may cost before it is stopped from outside the tools, in USD.
    learn_max_usd: float = 5.0
    repair_max_usd: float = 2.5
    check_max_usd: float = 0.25
    # Each model call's input is kept near this many tokens: older steps are replaced by their
    # one-line summaries (Q9: a context that grows with every tool result costs 4.6 times as much).
    context_tokens: int = 30_000
    # Characters taken as one token when the size of a call is estimated before it is sent.
    chars_per_token: float = 3.5
    # Seconds one model call may take (CONVENTIONS.md, rule 8), and how often the client retries
    # a timeout, a connection error or a 5xx answer.
    model_timeout_seconds: float = 120.0
    model_retries: int = 2
    # Reasoning effort per job; blank sends none. Q9 could not confirm the levels of every model.
    reasoning_learn: str = "medium"
    reasoning_repair: str = "medium"
    reasoning_check: str = ""
    # Requests one learn or one repair may send to the portal while it explores (Q3: about 60).
    learn_max_requests: int = 60
    repair_max_requests: int = 30
    # A page view handed to the model is cut into parts of this many characters (about 4K tokens, Q4).
    view_chars: int = 14_000
    # Text inside one element, and one attribute value, are cut to this many characters in a view.
    view_text_chars: int = 240
    view_attr_chars: int = 160
    # On a page with at least this many alike rows, the view shows `view_rows_shown` of them (Q4:
    # three). Rows count as alike when they share tag and classes and most carry a link or a data-* hook.
    view_rows_min: int = 8
    view_rows_shown: int = 3
    # A JSON answer is shown with its arrays cut to this many items, and strings to this length.
    view_json_items: int = 3
    view_json_string_chars: int = 300
    # How many groups `page_links` shows, and how many matches `search_page` shows.
    links_groups: int = 40
    search_matches: int = 20
    search_context_chars: int = 120
    # A dry run of the working recipe reads at most this many list pages and this many tenders'
    # own pages, and may fetch this many pages it lacks before it reports the rest as missing.
    dry_run_list_pages: int = 2
    dry_run_details: int = 3
    dry_run_fetches: int = 8
    # How many of a dry run's records and problems the model is shown.
    dry_run_samples: int = 2
    dry_run_problems: int = 15
    # The spot check: how many tenders it reads, and how much of each page's text it is given.
    check_tenders: int = 3
    check_page_chars: int = 12_000
    # A tool's answer and its arguments, as stored on an agent step, are cut to this length.
    step_preview_chars: int = 600

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and f.name != "model_retries":
                if not value > 0:
                    raise ValueError(f"agent setting {f.name} must be positive")
        if self.model_retries < 0:
            raise ValueError("agent setting model_retries must not be negative")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AgentSettings":
        """Defaults overridden by AGENT_<NAME>. A blank variable keeps the default; one that is
        no number raises ValueError naming the variable."""
        env = os.environ if environ is None else environ
        kw: dict[str, object] = {}
        for f in fields(cls):
            variable = f"AGENT_{f.name.upper()}"
            raw = env.get(variable)
            if raw is None:
                continue
            kind = type(getattr(cls, f.name))
            if kind is str:
                kw[f.name] = raw.strip()
                continue
            if not raw.strip():
                continue
            try:
                kw[f.name] = kind(raw)
            except ValueError:
                raise ValueError(f"{variable} must be a number, got {raw!r}") from None
        return cls(**kw)


DEFAULT_AGENT_SETTINGS = AgentSettings()
