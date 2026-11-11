"""Rolling credentials preserve uploads without surviving socket handover."""

from types import SimpleNamespace

import pytest

from ..forum.media_sessions import MediaSessions
from ..forum.models import ForumError


def sessions():
    clock = [1_800_000_000]
    connection = object()
    user = SimpleNamespace(username='Alice', uuid='account-id', _connection=connection)
    server = SimpleNamespace(_stopping=False, _users={'Alice': user})
    server._active_user_for_client = lambda client: server._users['Alice'] if client is server._users['Alice']._connection else None
    service = SimpleNamespace(account=lambda uuid: None)
    return MediaSessions(server, service, clock=lambda: clock[0]), server, user, clock


def test_rolling_credentials_keep_inflight_grant_until_original_expiry():
    grants, _, user, clock = sessions()
    first, first_expiry = grants.issue(user)
    clock[0] += 44 * 60
    assert grants.issue(user) == (first, first_expiry)
    clock[0] += 60
    second, second_expiry = grants.issue(user)
    assert second != first and second_expiry == first_expiry + 45 * 60
    assert grants.authenticate(first) is user
    assert grants.issue(user) == (second, second_expiry)
    clock[0] = first_expiry
    with pytest.raises(ForumError, match='forum-error-account'):
        grants.authenticate(first)
    assert grants.authenticate(second) is user
    # Repeated refreshes do not accumulate more grants on the same socket.
    for _ in range(100):
        clock[0] += 45 * 60
        grants.issue(user)
        assert len(grants._grants) <= 2


def test_handover_revokes_both_rolling_grants_and_shutdown_revokes_replacement():
    grants, server, user, clock = sessions()
    first, _ = grants.issue(user)
    clock[0] += 45 * 60
    second, _ = grants.issue(user)
    replacement = SimpleNamespace(username=user.username, uuid=user.uuid, _connection=object())
    server._users[user.username] = replacement
    for token in (first, second):
        with pytest.raises(ForumError, match='forum-error-account'):
            grants.authenticate(token)
    with pytest.raises(ForumError, match='forum-error-account'):
        grants.issue(user)
    current, _ = grants.issue(replacement)
    assert grants.authenticate(current) is replacement
    server._stopping = True
    with pytest.raises(ForumError, match='forum-error-account'):
        grants.authenticate(current)


def test_live_account_checks_apply_to_reused_credentials():
    grants, _, user, _ = sessions()
    token, _ = grants.issue(user)

    def suspended(uuid):
        raise ForumError('forum-error-account')

    grants.service.account = suspended
    with pytest.raises(ForumError, match='forum-error-account'):
        grants.authenticate(token)
    with pytest.raises(ForumError, match='forum-error-account'):
        grants.issue(user)
