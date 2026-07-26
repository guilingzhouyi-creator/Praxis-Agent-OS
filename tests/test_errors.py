import sys
sys.path.insert(0, r'C:\CODE_game-development\praxis\src')

from l1.kernel.errors import (
    PraxisError, error, catalog, set_locale, get_locale,
    E_TIMEOUT, E_INTERNAL, register_error,
)

def test_basic_error():
    e = PraxisError(E_TIMEOUT, "Operation timed out", timeout=60)
    d = e.to_dict()
    assert d["success"] is False
    assert d["error_code"] == "E_TIMEOUT"
    assert d["context"]["timeout"] == 60
    assert str(e) == "[E_TIMEOUT] Operation timed out"
    print("  basic error: OK")

def test_convenience():
    d = error(E_INTERNAL, cause=Exception("disk full"))
    assert d["success"] is False
    assert "cause" in d
    print("  convenience error: OK")

def test_catalog():
    c = catalog()
    assert "E_TIMEOUT" in c
    assert len(c) >= 20
    print(f"  catalog: {len(c)} codes")

def test_i18n():
    set_locale("zh-CN")
    d = error(E_TIMEOUT)
    assert d["error"] == "操作超时"
    print("  i18n zh-CN: OK")

    set_locale("en")
    d = error(E_TIMEOUT)
    assert d["error"] == "Operation timed out"
    print("  i18n en: OK")

def test_default_message():
    from l1.kernel.errors import _default_message
    msg = _default_message(E_TIMEOUT)
    assert msg == "Operation timed out"
    print("  default message: OK")

def test_error_str():
    e = PraxisError(E_TIMEOUT, "Operation timed out")
    assert "E_TIMEOUT" in str(e)
    print("  str representation: OK")

if __name__ == "__main__":
    test_basic_error()
    test_convenience()
    test_catalog()
    test_i18n()
    test_default_message()
    test_error_str()
    print("\nAll error tests passed")
