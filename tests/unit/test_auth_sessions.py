
from datetime import timedelta

import pytest

from app.services.auth_sessions import (
    create_session,
    generate_session_token,
    hash_session_token,
)


def test_session_tokens_are_random():
    first = generate_session_token()
    second = generate_session_token()

    assert first != second
    assert len(first) >= 40
    assert len(second) >= 40


def test_session_hash_is_deterministic():
    token = generate_session_token()

    first = hash_session_token(token)
    second = hash_session_token(token)

    assert first == second
    assert first != token
    assert len(first) == 64


def test_session_lifetime_must_be_positive():
    with pytest.raises(
        ValueError,
        match="Session lifetime must be positive",
    ):
        create_session(
            employee_id=1,
            lifetime=timedelta(seconds=0),
        )
