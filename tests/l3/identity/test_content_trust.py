"""Tests for l3.services.content_trust — provenance tagging and trust evaluation."""

from __future__ import annotations


class TestProvenanceModel:
    """Provenance dataclass — creation, to_dict, from_dict."""

    def test_provenance_defaults(self):
        from l3.services.content_trust import Provenance, SourceType
        p = Provenance()
        assert p.source_type == SourceType.UNKNOWN
        assert p.source_id == ""
        assert p.trace_id == ""
        assert p.trust_score == 0.0

    def test_provenance_create(self):
        from l3.services.content_trust import Provenance, SourceType
        p = Provenance(
            source_type=SourceType.AGENT,
            source_id="agent-1",
            method="execution",
            trace_id="trace-abc",
            trust_score=0.85,
        )
        assert p.source_type == SourceType.AGENT
        assert p.source_id == "agent-1"
        assert p.trust_score == 0.85

    def test_provenance_to_dict(self):
        from l3.services.content_trust import Provenance, SourceType
        p = Provenance(source_type=SourceType.TOOL, source_id="read_file", trust_score=0.9)
        d = p.to_dict()
        assert d["source_type"] == "tool"
        assert d["source_id"] == "read_file"
        assert d["trust_score"] == 0.9

    def test_provenance_from_dict_roundtrip(self):
        from l3.services.content_trust import Provenance, SourceType
        p = Provenance(source_type=SourceType.HUMAN, source_id="shell", method="input", trust_score=1.0)
        d = p.to_dict()
        p2 = Provenance.from_dict(d)
        assert p2.source_type == SourceType.HUMAN
        assert p2.source_id == "shell"
        assert p2.method == "input"

    def test_provenance_from_dict_unknown_type(self):
        from l3.services.content_trust import Provenance, SourceType
        d = {"source_type": "invalid_type", "source_id": "test"}
        p = Provenance.from_dict(d)
        assert p.source_type == SourceType.UNKNOWN


class TestSourceReputation:
    """source reputation tracking — record + moving average."""

    def test_record_and_avg(self):
        from l3.services.content_trust import get_source_reputation, record_source_performance, reset_source_reputation
        reset_source_reputation()
        record_source_performance("agent-a", 0.8)
        record_source_performance("agent-a", 0.9)
        record_source_performance("agent-a", 0.7)
        avg = get_source_reputation("agent-a")
        assert round(avg, 2) == 0.80

    def test_empty_reputation(self):
        from l3.services.content_trust import get_source_reputation
        score = get_source_reputation("nonexistent")
        assert score == 0.0

    def test_record_capped(self):
        from l3.services.content_trust import get_source_reputation, record_source_performance, reset_source_reputation
        reset_source_reputation()
        for i in range(150):
            record_source_performance("agent-b", 0.5)
        avg = get_source_reputation("agent-b")
        assert avg == 0.5


class TestGetTrust:
    """ContentTrust.tag() provenance tagging."""

    def test_tag_returns_provenance(self):
        from l3.services.content_trust import ContentTrust, SourceType
        ct = ContentTrust()
        p = ct.tag("agent", source_id="agent-1", method="test", trace_id="t1")
        assert p.source_type == SourceType.AGENT
        assert p.source_id == "agent-1"
        assert p.trace_id == "t1"

    def test_tag_tool_source(self):
        from l3.services.content_trust import ContentTrust, SourceType
        ct = ContentTrust()
        p = ct.tag("tool", source_id="read_file", method="execution")
        assert p.source_type == SourceType.TOOL
        assert p.source_id == "read_file"

    def test_tag_human_source(self):
        from l3.services.content_trust import ContentTrust, SourceType
        ct = ContentTrust()
        p = ct.tag("human", source_id="user-1")
        assert p.source_type == SourceType.HUMAN
