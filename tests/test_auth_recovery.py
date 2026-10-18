"""Exercise the coordinator with mocked HTTP and config-entry persistence."""

import asyncio
import base64
import json
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.codex_usage import coordinator as module
from custom_components.codex_usage.const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_CODEX_HOME,
    CONF_REFRESH_TOKEN,
)


def jwt(exp):
    return "header." + base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode() + ".sig"


class Response:
    def __init__(self, status=200, data=None):
        self.status = status
        self.data = data if data is not None else {}

    async def __aenter__(self):
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.data

    async def text(self):
        return json.dumps(self.data)


@pytest.fixture
def rig(monkeypatch):
    entry = SimpleNamespace(
        data={
            CONF_ACCESS_TOKEN: jwt(9999999999),
            CONF_REFRESH_TOKEN: "refresh-old",
            CONF_ACCOUNT_ID: "account",
            "keep": "unchanged",
        },
        entry_id="existing-entry",
        unique_id="existing-unique",
    )
    hass = SimpleNamespace(config_entries=Mock(), async_add_executor_job=AsyncMock())

    def update(entry, *, data):
        entry.data = data

    hass.config_entries.async_update_entry.side_effect = update
    coord = object.__new__(module.CodexUsageCoordinator)
    coord.hass, coord.entry, coord._cfg = hass, entry, entry.data
    coord._auth_lock = asyncio.Lock()
    coord._async_get_reset_credits = AsyncMock(return_value={})
    gets, posts, get_calls, post_calls = deque(), deque(), [], []

    def get(url, **kwargs):
        get_calls.append(dict(kwargs["headers"]))
        result = gets.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    def post(url, **kwargs):
        post_calls.append(kwargs)
        result = posts.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        module.aiohttp_client,
        "async_get_clientsession",
        lambda _: SimpleNamespace(get=get, post=post),
    )
    return SimpleNamespace(
        c=coord,
        entry=entry,
        hass=hass,
        gets=gets,
        posts=posts,
        get_calls=get_calls,
        post_calls=post_calls,
    )


@pytest.mark.asyncio
async def test_valid_and_missing_window(rig):
    rig.gets.append(Response(data={"plan_type": "pro", "credits": {"balance": 2}}))
    result = await rig.c._async_update_data()
    assert result["plan"] == "pro"
    assert result["credits_balance"] == 2
    assert result["primary_used_percent"] is None
    assert not rig.post_calls


@pytest.mark.asyncio
async def test_proactive_refresh_rotation_and_entry_identity(rig):
    rig.entry.data[CONF_ACCESS_TOKEN] = jwt(1)
    rig.posts.append(Response(data={"access_token": "new", "refresh_token": "rotated"}))
    rig.gets.append(Response())
    await rig.c._async_update_data()
    assert rig.get_calls[0]["Authorization"] == "Bearer new"
    assert rig.entry.data[CONF_REFRESH_TOKEN] == "rotated"
    assert rig.entry.data["keep"] == "unchanged"
    assert rig.entry.entry_id == "existing-entry"
    assert rig.entry.unique_id == "existing-unique"
    rig.hass.config_entries.async_update_entry.assert_called_once()


@pytest.mark.asyncio
async def test_future_jwt_rejected_refresh_and_exact_retry(rig):
    rig.gets.extend(
        [Response(401, {"error": {"code": "token_expired"}}), Response(401), Response()]
    )
    rig.posts.append(Response(data={"access_token": "new", "refresh_token": "rotated"}))
    await rig.c._async_update_data()
    assert len(rig.post_calls) == 1
    assert len(rig.get_calls) == 3
    assert "ChatGPT-Account-Id" not in rig.get_calls[0]
    assert rig.get_calls[1]["ChatGPT-Account-Id"] == "account"
    assert rig.get_calls[2]["ChatGPT-Account-Id"] == "account"
    assert rig.get_calls[2]["Authorization"] == "Bearer new"


@pytest.mark.asyncio
async def test_header_fallback_success_does_not_refresh(rig):
    rig.gets.extend([Response(401), Response()])
    await rig.c._async_update_data()
    assert not rig.post_calls


@pytest.mark.asyncio
async def test_no_account_and_no_rotation(rig):
    rig.entry.data[CONF_ACCOUNT_ID] = ""
    rig.gets.extend([Response(401), Response()])
    rig.posts.append(Response(data={"access_token": "new"}))
    await rig.c._async_update_data()
    assert len(rig.get_calls) == 2
    assert rig.entry.data[CONF_REFRESH_TOKEN] == "refresh-old"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_invalid_refresh_requires_reauth(rig, status):
    rig.gets.extend([Response(401), Response(401)])
    rig.posts.append(Response(status, {"error": "invalid_grant"}))
    with pytest.raises(ConfigEntryAuthFailed):
        await rig.c._async_update_data()
    assert len(rig.post_calls) == 1


@pytest.mark.asyncio
async def test_second_401_stops(rig):
    rig.gets.extend([Response(401), Response(401), Response(401)])
    rig.posts.append(Response(data={"access_token": "new"}))
    with pytest.raises(ConfigEntryAuthFailed):
        await rig.c._async_update_data()
    assert len(rig.get_calls) == 3
    assert len(rig.post_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429, 500])
async def test_non_auth_http_errors_do_not_refresh(rig, status):
    rig.gets.append(Response(status))
    with pytest.raises(UpdateFailed, match=f"HTTP {status}"):
        await rig.c._async_update_data()
    assert not rig.post_calls


@pytest.mark.asyncio
async def test_missing_refresh_requires_reauth(rig):
    rig.entry.data.pop(CONF_REFRESH_TOKEN)
    rig.gets.extend([Response(401), Response(401)])
    with pytest.raises(ConfigEntryAuthFailed):
        await rig.c._async_update_data()
    assert not rig.post_calls


@pytest.mark.asyncio
async def test_concurrent_failures_share_rotated_token(rig):
    old = rig.entry.data[CONF_ACCESS_TOKEN]
    rig.posts.append(Response(data={"access_token": "new", "refresh_token": "rotated"}))
    results = await asyncio.gather(*(rig.c._async_get_bearer(old) for _ in range(5)))
    assert results == [("new", "account")] * 5
    assert len(rig.post_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh", [False, True])
async def test_timeout(rig, refresh):
    if refresh:
        rig.gets.extend([Response(401), Response(401)])
        rig.posts.append(TimeoutError())
    else:
        rig.gets.append(TimeoutError())
    with pytest.raises(UpdateFailed):
        await rig.c._async_update_data()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"access_token": ""},
        {"access_token": 1},
        {"access_token": "new", "refresh_token": []},
    ],
)
async def test_malformed_refresh_does_not_persist(rig, payload):
    rig.gets.extend([Response(401), Response(401)])
    rig.posts.append(Response(data=payload))
    with pytest.raises(UpdateFailed):
        await rig.c._async_update_data()
    rig.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_file_auth_recovery_and_rotation(rig):
    rig.entry.data.pop(CONF_ACCESS_TOKEN)
    rig.entry.data[CONF_CODEX_HOME] = "/unused"
    auth = {
        "tokens": {
            "access_token": "file-old",
            "refresh_token": "file-refresh",
            "account_id": "file-account",
        }
    }
    rig.c._async_read_auth_json = AsyncMock(return_value=("/unused/auth.json", auth))
    rig.c._async_write_auth_json = AsyncMock()
    rig.gets.extend([Response(401), Response(401), Response()])
    rig.posts.append(Response(data={"access_token": "file-new", "refresh_token": "rotated"}))
    await rig.c._async_update_data()
    assert auth["tokens"]["refresh_token"] == "rotated"
    assert auth["tokens"]["access_token"] == "file-new"
    rig.c._async_write_auth_json.assert_awaited_once()
    assert rig.get_calls[-1]["ChatGPT-Account-Id"] == "file-account"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], "unexpected"])
async def test_malformed_usage_response(rig, payload):
    rig.gets.append(Response(data=payload))
    with pytest.raises(UpdateFailed, match="unexpected response"):
        await rig.c._async_update_data()
    assert not rig.post_calls


@pytest.mark.asyncio
async def test_refresh_transient_failure_redacts_body(rig):
    rig.gets.extend([Response(401), Response(401)])
    rig.posts.append(Response(429, {"secret": "must-not-leak"}))
    with pytest.raises(UpdateFailed) as error:
        await rig.c._async_update_data()
    assert "must-not-leak" not in str(error.value)
    assert "429" in str(error.value)
    rig.hass.config_entries.async_update_entry.assert_not_called()
