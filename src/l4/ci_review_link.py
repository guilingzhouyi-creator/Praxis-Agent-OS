"""CiReviewService linkage mixin — downstream consumers of a review verdict.

Extracted from ``ci_review.py`` to slim the service class. Every linkage is
config-gated and non-blocking; ``CiReviewService`` inherits this mixin so the
runtime behavior is unchanged.

``capture`` is resolved at call time from ``l4.ci_review`` so tests (and any
other caller) that monkeypatch the module-bound ``capture`` name in
``l4.ci_review`` keep intercepting linkage failures exactly as before the
split.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ci_review import CardCiReport

logger = logging.getLogger(__name__)


def _capture(*args, **kwargs) -> None:
    """Resolve the ErrorBus capture at call time (keeps module-bound patches working)."""
    from l4.ci_review import capture

    return capture(*args, **kwargs)


class CiReviewLinkMixin:
    """Config-gated, non-blocking downstream linkages for CI review reports."""

    # ── Downstream linkages (config-gated, non-blocking) ──

    def _dispatch_linkages(self, report: CardCiReport) -> None:
        """Fire config-gated downstream consumers based on the verdict.

        Every consumer is wrapped in its own suppression so a failing
        linkage can never abort the remaining consumers or the report.
        """
        with contextlib.suppress(Exception):
            if report.verdict == "REJECT" and self._setting("ci.review.escalate_reject", False):
                self._link_approval(report)
        with contextlib.suppress(Exception):
            if report.verdict == "NEEDS_CHANGES" and self._setting("ci.review.route_convention", False):
                self._link_convention(report)
        with contextlib.suppress(Exception):
            if report.review and self._setting("ci.review.reputation", False):
                self._link_reputation(report)
        with contextlib.suppress(Exception):
            if report.verdict != "PASS" and self._setting("ci.review.lean_trace", False):
                self._link_lean_trace(report)
        with contextlib.suppress(Exception):
            if report.verdict in ("REJECT", "NEEDS_CHANGES") and self._setting("ci.review.notify.enabled", False):
                self._link_notify(report)
        with contextlib.suppress(Exception):
            if report.verdict != "PASS" and self._setting("ci.review.todo_linkage", False):
                self._link_todo(report)

    def _link_approval(self, report: CardCiReport) -> None:
        """Escalate a REJECT verdict to the ApprovalGate (optional)."""
        try:
            from l3.card.approval_gate import get_gate

            get_gate().request(
                "ci.review",
                report.agent_id or "system",
                {"card_id": report.card_id, "run_id": report.run_id},
                reason=f"CI review {report.verdict}: {report.error}",
            )
        except Exception as e:
            _capture(
                "ci_review: approval linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "approval"},
            )
            logger.debug("ci_review: approval linkage failed: %s", e)

    def _link_convention(self, report: CardCiReport) -> None:
        """Route a NEEDS_CHANGES verdict to cross-agent Convention (optional)."""
        try:
            from l3.card.card_registry import get_registry

            reg = get_registry()
            intent = domain = ""
            rec = reg.get(report.card_id)
            if rec is not None:
                cols = getattr(getattr(rec, "summary", None), "columns", None) or {}
                intent = cols.get("intent", "")
                domain = cols.get("domain", "")
            reg._route_to_convention(report.card_id, intent=intent, domain=domain)
        except Exception as e:
            _capture(
                "ci_review: convention linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "convention"},
            )
            logger.debug("ci_review: convention linkage failed: %s", e)

    def _link_reputation(self, report: CardCiReport) -> None:
        """Adjust the executing agent's reputation from an LLM review (optional)."""
        try:
            from l1.kernel.reputation import get_reputation

            get_reputation().record_review(report.agent_id or "system", approved=report.verdict == "PASS")
        except Exception as e:
            _capture(
                "ci_review: reputation linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "reputation"},
            )
            logger.debug("ci_review: reputation linkage failed: %s", e)

    def _link_lean_trace(self, report: CardCiReport) -> None:
        """Archive a failure trace for R4Agent skill evolution (optional)."""
        try:
            from l3.tools._archive import _cmd_archive_store

            entry = {"card_id": report.card_id, "verdict": report.verdict, "gates": report.gates, "error": report.error}
            _cmd_archive_store(
                fonds="skills",
                series="lean_trace",
                content=json.dumps(entry, ensure_ascii=False),
                tags=f"ci_review,{report.agent_id or 'system'},failure",
            )
        except Exception as e:
            _capture(
                "ci_review: lean trace failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "lean_trace"},
            )
            logger.debug("ci_review: lean trace failed: %s", e)

    def _link_notify(self, report: CardCiReport) -> None:
        """Push a notification for a failing verdict (optional).

        Webhook mode: when ``ci.review.notify.webhook_url`` is configured
        and the verdict's event is in ``ci.review.notify.webhook_events``
        (default failed/rejected), POSTs a structured payload through the
        notify webhook channel.  Otherwise falls back to the configured
        notify channel (log|email|slack|sms).
        """
        try:
            from l4.notify import get_service as _get_notify

            channel = str(self._setting("ci.review.notify.channel", "log"))
            message = f"CI review {report.verdict} for card {report.card_id}"
            webhook_url = str(self._setting("ci.review.notify.webhook_url", "") or "")
            events = self._setting("ci.review.notify.webhook_events", ["failed", "rejected"]) or []
            if webhook_url and self._verdict_event(report.verdict) in events:
                payload = json.dumps(
                    {
                        "card_id": report.card_id,
                        "verdict": report.verdict,
                        "gates": report.gates,
                        "error": report.error,
                        "agent_id": report.agent_id,
                        "timestamp": report.completed_at or report.started_at,
                    },
                    ensure_ascii=False,
                )
                _get_notify().send(channel="webhook", to=webhook_url, subject=message, body=payload)
                return
            _get_notify().send(
                channel=channel, to=report.agent_id or "system", subject="Praxis notification", body=message
            )
        except Exception as e:
            _capture(
                "ci_review: notify linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "notify"},
            )
            logger.debug("ci_review: notify linkage failed: %s", e)

    @staticmethod
    def _verdict_event(verdict: str) -> str:
        """Map a verdict to a webhook event name."""
        return {
            "PASS": "passed",
            "NEEDS_CHANGES": "failed",
            "REJECT": "rejected",
            "SKIPPED": "skipped",
        }.get(verdict, "failed")

    def _link_todo(self, report: CardCiReport) -> None:
        """Record a fix-up task for a failing verdict (optional)."""
        try:
            from l3.services.todo_tracker import TodoTracker

            content = f"ci-review:{report.card_id} ({report.verdict})"
            tracker = TodoTracker()
            tracker.update(content, "add")
            tracker.update(content, "escalated")
        except Exception as e:
            _capture(
                "ci_review: todo linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "todo"},
            )
            logger.debug("ci_review: todo linkage failed: %s", e)
