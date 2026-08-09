from introspection_sdk._backoff import _MAX_RETRY_BACKOFF, _retry_delay


def test_full_jitter_without_retry_after() -> None:
    assert _retry_delay(2, None, 0.5, random_value=0.0) == 0.0
    assert _retry_delay(2, None, 0.5, random_value=0.5) == 1.0
    assert _retry_delay(2, None, 0.5, random_value=1.0) == 2.0


def test_jitter_is_added_above_retry_after_floor() -> None:
    assert _retry_delay(1, 1.0, 0.5, random_value=0.0) == 1.0
    assert _retry_delay(1, 1.0, 0.5, random_value=0.5) == 1.5
    assert _retry_delay(1, 1.0, 0.5, random_value=1.0) == 2.0


def test_only_the_jitter_the_sdk_adds_is_capped() -> None:
    assert _retry_delay(4, None, 1.0, random_value=1.0) == _MAX_RETRY_BACKOFF
    assert (
        _retry_delay(4, 9.0, 1.0, random_value=1.0) == 9.0 + _MAX_RETRY_BACKOFF
    )


def test_retry_after_longer_than_the_cap_is_honoured() -> None:
    # ``Retry-After: 60`` used to be clamped to 10s, so the SDK re-hit the
    # rate limiter 50s before the server said it could.
    assert _retry_delay(0, 60.0, 0.5, random_value=0.0) == 60.0
    assert _retry_delay(0, 60.0, 0.5, random_value=1.0) == 60.5
