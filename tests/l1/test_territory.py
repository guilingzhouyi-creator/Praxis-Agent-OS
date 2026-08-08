"""Territory containment tests — boundary-safe subtree matching."""

from __future__ import annotations

from l1.kernel.territory import is_within


class TestIsWithinBoundary:
    """Test boundary-safe subtree containment semantics."""

    def test_exact_match(self):
        assert is_within("/project/foo", ["/project/foo"]) is True

    def test_child_file_inside(self):
        assert is_within("/project/foo/main.py", ["/project/foo"]) is True

    def test_deep_child_inside(self):
        assert is_within("/project/foo/a/b/c.py", ["/project/foo"]) is True

    def test_prefix_collision_rejected(self):
        assert is_within("/project/foo_secret", ["/project/foo"]) is False

    def test_prefix_collision_rejected_two(self):
        assert is_within("/project/foobar/x.py", ["/project/foo"]) is False

    def test_sibling_rejected(self):
        assert is_within("/project/bar/x.py", ["/project/foo"]) is False

    def test_empty_bases_matches_anything(self):
        assert is_within("/anything/at/all", []) is True

    def test_empty_target_matches_nothing(self):
        assert is_within("", ["/project/foo"]) is False

    def test_trailing_separator_normalized(self):
        assert is_within("/project/foo/", ["/project/foo"]) is True
        assert is_within("/project/foo/x.py", ["/project/foo/"]) is True

    def test_relative_target_resolved(self):
        assert is_within("project/foo/main.py", ["/project/foo"]) is False

    def test_multiple_bases(self):
        assert is_within("/elsewhere/x.py", ["/project/foo", "/elsewhere"]) is True

    def test_target_equal_base_with_sibling_file(self):
        assert is_within("/project/foo", ["/project/foo"]) is True

    def test_root_base(self):
        assert is_within("/etc/passwd", ["/"]) is True

    def test_single_char_base(self):
        assert is_within("/x2/y.py", ["/x"]) is False
        assert is_within("/x/y.py", ["/x"]) is True


class TestNormalizationEdgeCases:
    """Edge case handling in path normalization."""

    def test_pure_dot_paths(self):
        assert is_within("/project/./foo", ["/project/x", "/project/foo"]) is True

    def test_dotdot_paths(self):
        assert is_within("/project/foo/../foo_secret", ["/project/foo"]) is False

    def test_empty_base_in_list_skipped(self):
        assert is_within("/project/foo", ["", "/project/foo"]) is True

    def test_nonextant_but_boundary_correct(self):
        assert is_within("/project/foo/new_dir/new_file", ["/project/foo"]) is True
