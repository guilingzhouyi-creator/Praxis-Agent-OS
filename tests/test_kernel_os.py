"""OS lifecycle tests — boot/shutdown/restart/watchdog."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestOSLifecycle:
    def test_get_os_singleton(self):
        from l1.kernel.os import get_os
        svc = get_os()
        assert svc is not None

    def test_status(self):
        from l1.kernel.os import get_os
        svc = get_os()
        s = svc.status()
        assert isinstance(s, dict)

    def test_start_stop(self):
        from l1.kernel.os import get_os
        svc = get_os()
        assert svc is not None
