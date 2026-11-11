from labelprinter import auth

KEY = b"k" * 32


def test_token_roundtrip_and_tamper_and_expiry():
    token = auth.make_token(KEY, now=1000)
    assert auth.valid_token(token, KEY, now=1001)
    assert not auth.valid_token(token, b"x" * 32, now=1001)            # wrong key
    assert not auth.valid_token("1" + token, KEY, now=1001)            # expiry edited
    assert not auth.valid_token(token, KEY, now=1000 + auth.EXPIRY_SECONDS + 1)
    assert not auth.valid_token("", KEY) and not auth.valid_token(None, KEY) and not auth.valid_token("nodot", KEY)


def test_password_ok_handles_non_ascii():
    assert auth.password_ok("s3cret-é", "s3cret-é")
    assert not auth.password_ok("s3cret", "s3cret-é")


def test_session_key_is_persisted(tmp_path):
    a = auth.get_session_key(tmp_path / "data")
    assert len(a) == 32 and auth.get_session_key(tmp_path / "data") == a


def test_throttle_blocks_after_ten_failures_and_frees_after_the_window():
    now = [0.0]
    t = auth.Throttle(clock=lambda: now[0])
    for _ in range(auth.MAX_FAILURES - 1):
        t.record_failure("1.2.3.4")
    assert not t.blocked("1.2.3.4")
    t.record_failure("1.2.3.4")
    assert t.blocked("1.2.3.4") and not t.blocked("5.6.7.8")
    now[0] = auth.FAILURE_WINDOW + 1
    assert not t.blocked("1.2.3.4")
