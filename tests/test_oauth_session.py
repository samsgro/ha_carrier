"""oauthdiag.3 Home Assistant option, unload, and reauth safety tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from carrier_api import CarrierApiAuthError
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_carrier.carrier_data_update_coordinator import (
    CarrierDataUpdateCoordinator,
)
from custom_components.ha_carrier.const import (
    CONF_EARLY_REFRESH_CANARY,
    CONF_INFINITE_HOLDS,
    CONF_INVALID_GRANT_RECOVERY,
    DOMAIN,
    UNAUTHORIZED_RETRY_THRESHOLD,
)
from custom_components.ha_carrier.diagnostics import async_get_config_entry_diagnostics
from custom_components.ha_carrier.exceptions import CarrierUnauthorizedError
from custom_components.ha_carrier.resiliency import ResiliencyState

from .conftest import PASSWORD, USERNAME, FakeCarrierApiConnection, entity_id_for_unique_id
from .test_carrier_data_update_coordinator import _set_coordinator_api_connection


@pytest.mark.asyncio
async def test_h1_defaults_pass_flags_off_and_do_not_start_canary(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H1: missing options mean both flags off and no connection-owned canary task."""
    config_entry = await setup_integration()

    assert carrier_api.early_refresh_canary is False
    assert carrier_api.invalid_grant_recovery is False
    assert callable(carrier_api.schedule_fn)
    assert carrier_api._canary_task is None
    assert config_entry.options.get(CONF_EARLY_REFRESH_CANARY, False) is False
    assert config_entry.options.get(CONF_INVALID_GRANT_RECOVERY, False) is False


@pytest.mark.asyncio
async def test_h2_h3_canary_option_does_not_reauth(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H2/H3: enabling the canary does not raise ConfigEntryAuthFailed."""
    config_entry = await setup_integration(options={CONF_EARLY_REFRESH_CANARY: True})
    coordinator = config_entry.runtime_data

    assert carrier_api.early_refresh_canary is True
    assert coordinator.resiliency.consecutive_unauthorized == 0
    data = await coordinator._async_update_data()

    assert data
    assert coordinator.resiliency.consecutive_unauthorized == 0
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.asyncio
async def test_h4_three_expiry_auth_errors_still_reauth(
    carrier_api: FakeCarrierApiConnection,
) -> None:
    """H4: flags off, repeated expiry AuthErrors still escalate to reauth."""
    coordinator = CarrierDataUpdateCoordinator.__new__(CarrierDataUpdateCoordinator)
    coordinator.systems = carrier_api.systems
    coordinator.data_flush = True
    coordinator._websocket_initialized = True
    _set_coordinator_api_connection(coordinator, carrier_api)
    coordinator.resiliency = ResiliencyState(
        unauthorized_threshold=UNAUTHORIZED_RETRY_THRESHOLD,
        transient_threshold=5,
    )
    carrier_api.load_data_error = CarrierApiAuthError("invalid_grant")
    saw_reauth = False

    for _ in range(6):
        try:
            await coordinator._async_update_data()
        except ConfigEntryAuthFailed:
            saw_reauth = True
            break
        except UpdateFailed:
            continue

    assert saw_reauth is True


@pytest.mark.asyncio
async def test_h5_recovery_success_does_not_reauth(
    carrier_api: FakeCarrierApiConnection,
) -> None:
    """H5: recovery success is just a successful load with no reauth."""
    coordinator = CarrierDataUpdateCoordinator.__new__(CarrierDataUpdateCoordinator)
    coordinator.systems = carrier_api.systems
    coordinator.data_flush = True
    coordinator._websocket_initialized = True
    _set_coordinator_api_connection(coordinator, carrier_api)
    coordinator.resiliency = ResiliencyState(unauthorized_threshold=3, transient_threshold=5)
    carrier_api.invalid_grant_recovery = True

    await coordinator._async_full_refresh()

    assert coordinator.resiliency.consecutive_unauthorized == 0
    assert coordinator.systems == carrier_api.systems


@pytest.mark.asyncio
async def test_h6_recovery_login_failure_follows_unauthorized_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H6: recovery login auth-failure still uses the existing reauth path."""
    coordinator = CarrierDataUpdateCoordinator.__new__(CarrierDataUpdateCoordinator)
    coordinator.data_flush = True

    async def fake_full_refresh() -> None:
        """Raise an escalated recovery login failure."""
        raise CarrierUnauthorizedError("login_failed")

    monkeypatch.setattr(coordinator, "_async_full_refresh", fake_full_refresh)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_h7_unload_awaits_connection_cleanup(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H7: unload awaits connection cleanup and connection-owned OAuth tasks."""
    config_entry = await setup_integration()
    blocked = asyncio.Event()

    async def hanging_canary() -> None:
        """Stay running until cleanup cancels this connection-owned task."""
        await blocked.wait()

    canary_task = hass.async_create_background_task(
        hanging_canary(), f"{DOMAIN}_oauth_{config_entry.entry_id}"
    )
    carrier_api._canary_task = canary_task
    coordinator = config_entry.runtime_data

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert carrier_api.cleanup_calls >= 1
    assert carrier_api._closing is True
    assert carrier_api._canary_task is None
    assert canary_task.done()
    assert coordinator.websocket_task is None
    assert config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.asyncio
async def test_h8_options_toggle_reloads_flags(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H8: toggling options reloads the entry and passes flags into a new connection."""
    config_entry = await setup_integration()
    assert carrier_api.early_refresh_canary is False

    form = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={
            CONF_INFINITE_HOLDS: True,
            CONF_EARLY_REFRESH_CANARY: True,
            CONF_INVALID_GRANT_RECOVERY: False,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.state is ConfigEntryState.LOADED
    assert carrier_api.early_refresh_canary is True
    assert carrier_api.invalid_grant_recovery is False


@pytest.mark.asyncio
async def test_h9_diagnostics_include_redacted_oauth_session(
    hass: HomeAssistant,
    setup_integration: Callable[..., Any],
) -> None:
    """H9: diagnostics expose flags/state and never include secrets."""
    config_entry = await setup_integration()

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["entry"]["data"][CONF_USERNAME] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    oauth_session = diagnostics["oauth_session"]
    assert oauth_session["early_refresh_canary"] is False
    assert oauth_session["invalid_grant_recovery"] is False
    assert oauth_session["state"] == "ACTIVE"
    assert "access_token" not in oauth_session
    assert "refresh_token" not in str(oauth_session)
    assert USERNAME not in str(oauth_session)
    assert PASSWORD not in str(oauth_session)


@pytest.mark.asyncio
async def test_h10_climate_write_during_canary_still_succeeds(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H10: a climate write still succeeds while the canary option is enabled."""
    await setup_integration(options={CONF_EARLY_REFRESH_CANARY: True})
    entity_id = entity_id_for_unique_id(hass, CLIMATE_DOMAIN, "abc123_zone_1_thermostat")

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )

    assert any(name == "set_config_mode" for name, _payload in carrier_api.calls)


@pytest.mark.asyncio
async def test_h11_infinite_holds_still_works_with_optional_new_keys(
    hass: HomeAssistant,
) -> None:
    """H11: infinite_holds still updates when the new option keys are omitted."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={CONF_INFINITE_HOLDS: True},
    )
    config_entry.add_to_hass(hass)

    form = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={CONF_INFINITE_HOLDS: False},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_INFINITE_HOLDS] is False
