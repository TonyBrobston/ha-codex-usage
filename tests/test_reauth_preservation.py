"""Reauthentication updates the existing entry through the supported helper."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant import config_entries

from custom_components.codex_usage.config_flow import CodexUsageConfigFlow
from custom_components.codex_usage.const import (
    AUTH_METHOD_DEVICE,
    CONF_ACCESS_TOKEN,
    CONF_AUTH_METHOD,
)


@pytest.mark.asyncio
async def test_reauth_preserves_entry_and_uses_update_reload_helper():
    flow = CodexUsageConfigFlow()
    flow.context = {"source": config_entries.SOURCE_REAUTH}
    entry = SimpleNamespace(entry_id="existing", unique_id="original-unique")
    flow._get_reauth_entry = Mock(return_value=entry)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = Mock()
    flow.async_step_reauth_confirm = AsyncMock(return_value={"step_id": "reauth_confirm"})
    flow.async_update_reload_and_abort = Mock(return_value={"reason": "reauth_successful"})
    flow.async_create_entry = Mock()
    original = {CONF_AUTH_METHOD: AUTH_METHOD_DEVICE, CONF_ACCESS_TOKEN: "old", "preserve": 42}
    await flow.async_step_reauth(original)
    flow.async_set_unique_id.assert_awaited_once_with("original-unique")
    flow._abort_if_unique_id_mismatch.assert_called_once()
    flow._base_config[CONF_ACCESS_TOKEN] = "replacement"
    flow._finish_authentication()
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry, data_updates={**original, CONF_ACCESS_TOKEN: "replacement"}
    )
    flow.async_create_entry.assert_not_called()
