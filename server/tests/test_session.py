from unittest.mock import MagicMock

import pytest

from api.db import session as database


def test_session_dependency_cleans_up_without_automatic_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    monkeypatch.setattr(database, "SessionFactory", factory)

    dependency = database.get_session()
    assert next(dependency) is session
    dependency.close()

    factory.return_value.__exit__.assert_called_once()
    session.commit.assert_not_called()
