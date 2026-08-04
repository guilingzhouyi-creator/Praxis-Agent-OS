"""ASK clarification — l3a_ask tool state machine.

When L3A cannot resolve the user's intent from the prompt alone, the LLM
calls the ``l3a_ask`` tool to raise up to ASK_MAX_QUESTIONS questions. The
session enters ``awaiting`` state; the AgentLoop breaks early (awaiting_input
marker) and the question list is returned to the caller. The user answers in
the chat window itself, via ``/l3a answer``, or through the REST endpoint;
answers are injected into the session history and the loop resumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import params as _p


@dataclass
class AskQuestion:
    """A single clarification question raised by the LLM."""

    id: str
    question: str
    options: list[str] = field(default_factory=list)
    required: bool = True
    answer: str = ""

    def to_dict(self) -> dict:
        d = {"id": self.id, "question": self.question, "required": self.required}
        if self.options:
            d["options"] = self.options
        if self.answer:
            d["answer"] = self.answer
        return d


@dataclass
class AskState:
    """Per-session pending clarification state."""

    questions: list[AskQuestion]
    asked_at: float = field(default_factory=lambda: __import__("time").time())
    status: str = _p.ASK_STATUS_AWAITING
    free_form: str = ""

    @classmethod
    def from_questions(cls, raw_questions: list) -> AskState:
        qs = []
        for i, raw in enumerate(raw_questions[: _p.ASK_MAX_QUESTIONS], start=1):
            if isinstance(raw, dict):
                qs.append(
                    AskQuestion(
                        id=str(raw.get("id", f"q{i}")),
                        question=str(raw.get("question", raw.get("text", ""))),
                        options=[str(o) for o in raw.get("options", [])],
                        required=bool(raw.get("required", True)),
                    )
                )
            else:
                qs.append(AskQuestion(id=f"q{i}", question=str(raw)))
        return cls(questions=qs)

    def missing(self) -> list[str]:
        return [q.id for q in self.questions if q.required and not q.answer]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "questions": [q.to_dict() for q in self.questions],
            "free_form": self.free_form,
            "asked_at": self.asked_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AskState:
        qs = []
        for raw in d.get("questions", []):
            qs.append(
                AskQuestion(
                    id=raw.get("id", ""),
                    question=raw.get("question", ""),
                    options=list(raw.get("options", [])),
                    required=bool(raw.get("required", True)),
                    answer=raw.get("answer", ""),
                )
            )
        st = cls(questions=qs)
        st.status = d.get("status", _p.ASK_STATUS_AWAITING)
        st.free_form = d.get("free_form", "")
        st.asked_at = float(d.get("asked_at", 0) or 0)
        return st


def ask_handler(session: object, args: dict, agent_id: str = "") -> dict:
    """Handler for the ``l3a_ask`` tool (registered on the AgentLoop).

    The LLM passes a list of questions; the session records them as pending
    and returns the awaiting marker so the loop stops and the user answers.
    """
    raw = args.get("questions") or args.get("ask") or []
    if not raw:
        return {"success": False, "error": "questions required"}
    session._ask = AskState.from_questions(raw)
    return {
        "success": True,
        "awaiting_input": True,
        "status": _p.ASK_STATUS_AWAITING,
        "asked": len(session._ask.questions),
        "questions": [q.to_dict() for q in session._ask.questions],
    }


def submit_answers(session: object, answers: dict, free_form: str = "") -> dict:
    """Fill answers into the pending question state.

    ``answers`` maps question id -> answer text; ``free_form`` carries the
    user's unstructured/custom input from the chat window. Partial answers
    are allowed: unanswered required questions are reported as ``missing``.
    """
    st = session._ask
    if not st or st.status != _p.ASK_STATUS_AWAITING:
        return {"success": False, "error": "no pending question"}
    for q in st.questions:
        if q.id in answers and answers[q.id] is not None:
            q.answer = str(answers[q.id])[: _p.ASK_MAX_ANSWER_CHARS]
    if free_form:
        st.free_form = str(free_form)[: _p.ASK_MAX_ANSWER_CHARS]
    missing = st.missing()
    st.status = _p.ASK_STATUS_ANSWERED
    return {
        "success": True,
        "status": _p.ASK_STATUS_ANSWERED,
        "answered": len([q for q in st.questions if q.answer]),
        "missing": missing,
    }


def build_answer_block(st: AskState) -> str:
    """Render the Q&A block injected into session history before resuming."""
    lines = ["[User Clarification]"]
    for q in st.questions:
        marker = "->" if q.answer else "(unanswered)"
        lines.append(f"Q: {q.question} {marker} {q.answer}")
    if st.free_form:
        lines.append(f"Free-form input: {st.free_form}")
    return "\n".join(lines)
