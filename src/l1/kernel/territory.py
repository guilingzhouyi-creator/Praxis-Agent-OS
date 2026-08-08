"""Territory containment — boundary-safe subtree path matching for gate gates.

Territory checks historically used ``str.startswith``, which maps the
authorized base ``/project/foo`` to the outside path ``/project/foo_secret``
(a prefix-collision bypass). Matching here uses boundary semantics: a target
is inside a base only when it equals the base or continues past a natural
separator. This is the typed subtree rule used by gates, constitution rules
and capability resources.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

_SEP = os.sep


def _normalize(path: str) -> str:
    """Return the absolute, separator-normalized form of *path* (no trailing separator)."""
    normalized = os.path.normpath(os.path.abspath(path))
    while normalized.endswith(_SEP) and len(normalized) > 1:
        normalized = normalized[:-1]
    return normalized


def is_within(target: str, bases: Iterable[str]) -> bool:
    """Return True when *target* sits inside at least one *bases* subtree.

    A target is inside a base when the normalized target equals the base or
    continues past a path separator from it. ``/project/foo_secret`` is NOT
    inside ``/project/foo``. Empty *bases* matches everything; an empty
    *target* matches nothing.
    """
    targets = list(bases)
    if not targets:
        return True
    if not target:
        return False
    t = _normalize(target)
    for base in targets:
        b = _normalize(base)
        if not b:
            continue
        if t == b:
            return True
        if b == _SEP:
            if t.startswith(_SEP):
                return True
            continue
        if t.startswith(b + _SEP):
            return True
    return False
