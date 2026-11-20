"""The file outcome test of `app/checks` (Q10, rule O2) as the `judge` of `store_document`.

`app/docs` handles bytes and `app/checks` judges them. This is the one place where the two
meet, so neither module has to know the other's types.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Collection

from app.checks import Answer, DownloadFacts, file_outcome, skip_reason
from app.docs.document import FileFacts, Judge
from app.models import CheckResult, SkipReason

_PASSWORD_FIELD = re.compile(rb"""type\s*=\s*["']?password""", re.IGNORECASE)


def plain_answer(facts: FileFacts) -> Answer:
    """What a download ran into, from the facts `app/docs` holds: the status, and a password field
    in the first bytes of a page that came in place of the file. The network layer knows more
    (redirects to a login page, bot-wall headers) and can pass its own function instead."""
    return Answer(status=facts.status, page_load=False,
                  password_field=bool(_PASSWORD_FIELD.search(facts.first_bytes)))


def outcome_judge(run_id: str, results: list[CheckResult], *,
                  answer_for: Callable[[FileFacts], Answer] = plain_answer,
                  usual_signs: Collection[str] = (),
                  trust_content_length: bool = False) -> Judge:
    """A judge that applies `file_outcome` to each download and appends its row to `results`.

    The rows are what `files_failed` (D1) needs at the end of the read. `trust_content_length`
    also holds the bytes received against `Content-Length`; leave it off when the network layer
    hands over a decoded body, whose length differs from the header's.
    """
    def judge(facts: FileFacts) -> SkipReason | None:
        result = file_outcome(run_id, DownloadFacts(
            file_name=facts.file_name, answer=answer_for(facts), first_bytes=facts.first_bytes,
            size_bytes=facts.size_bytes, content_type=facts.content_type,
            announced_size=facts.content_length if trust_content_length else None,
        ), usual_signs=usual_signs)
        results.append(result)
        return skip_reason(result)
    return judge
