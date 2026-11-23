import sys

import pytest

from src.core.auth import User, require_user

USER_A = User(uid="user-a", email="a@example.com")
USER_B = User(uid="user-b", email="b@example.com")


def _app():
    # Only set when a test module imported the app, so unit tests do not pay
    # for loading it. Collection imports every module before any test runs.
    main = sys.modules.get("src.main")
    return main.app if main else None


def sign_in_as(user):
    _app().dependency_overrides[require_user] = lambda: user


@pytest.fixture(scope="session", autouse=True)
def _api_runs_signed_in():
    """API tests run as user A, including module-scoped fixtures that upload."""
    app = _app()
    if app is not None:
        sign_in_as(USER_A)
    yield
    if app is not None:
        app.dependency_overrides.pop(require_user, None)


@pytest.fixture(autouse=True)
def _back_to_user_a():
    """A test that signs in as someone else, or as nobody, does not leak it."""
    yield
    if _app() is not None:
        sign_in_as(USER_A)
