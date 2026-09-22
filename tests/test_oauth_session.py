"""oauthfix.1 Home Assistant setup, unload, and reauth safety tests."""

from __future__ import annotations

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
    CONF_INFINITE_HOLDS,
    DOMAIN,
    UNAUTHORIZED_RETRY_THRESHOLD,
)
from custom_components.ha_carrier.diagnostics import async_get_config_entry_diagnostics
from custom_components.ha_carrier.exceptions import CarrierUnauthorizedError
from custom_components.ha_carrier.resiliency import ResiliencyState

from .conftest import PASSWORD, USERNAME, FakeCarrierApiConnection, entity_id_for_unique_id
from .test_carrier_data_update_coordinator import _set_coordinator_api_connection

_STALE_CANARY_KEY = "early_refresh_canary"
_STALE_RECOVERY_KEY = "invalid_grant_recovery"


@pytest.mark.asyncio
async def test_h1_setup_has_no_oauth_experiment_options_or_scheduler(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H1: setup passes only credentials and starts no OAuth scheduler task."""
    config_entry = await setup_integration()

    assert carrier_api.constructor_kwargs == {}
    assert "schedule_fn" not in carrier_api.constructor_kwargs
    assert "early_refresh_canary" not in carrier_api.constructor_kwargs
    assert "invalid_grant_recovery" not in carrier_api.constructor_kwargs
    assert config_entry.options.get(_STALE_CANARY_KEY) is None
    assert config_entry.options.get(_STALE_RECOVERY_KEY) is None
    assert hass.loop is not None


@pytest.mark.asyncio
async def test_h2_stale_stored_option_keys_are_ignored(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H2: leftover canary/recovery option keys are ignored at setup."""
    config_entry = await setup_integration(
        options={
            CONF_INFINITE_HOLDS: True,
            _STALE_CANARY_KEY: True,
            _STALE_RECOVERY_KEY: True,
        }
    )

    assert config_entry.options[_STALE_CANARY_KEY] is True
    assert config_entry.options[_STALE_RECOVERY_KEY] is True
    assert carrier_api.constructor_kwargs == {}
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.asyncio
async def test_h4_three_expiry_auth_errors_still_reauth(
    carrier_api: FakeCarrierApiConnection,
) -> None:
    """H4: repeated expiry AuthErrors still escalate to reauth."""
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
async def test_h5_successful_load_does_not_reauth(
    carrier_api: FakeCarrierApiConnection,
) -> None:
    """H5: a successful coordinator load does not start reauth."""
    coordinator = CarrierDataUpdateCoordinator.__new__(CarrierDataUpdateCoordinator)
    coordinator.systems = carrier_api.systems
    coordinator.data_flush = True
    coordinator._websocket_initialized = True
    _set_coordinator_api_connection(coordinator, carrier_api)
    coordinator.resiliency = ResiliencyState(unauthorized_threshold=3, transient_threshold=5)

    await coordinator._async_full_refresh()

    assert coordinator.resiliency.consecutive_unauthorized == 0
    assert coordinator.systems == carrier_api.systems


@pytest.mark.asyncio
async def test_h6_login_failure_follows_unauthorized_path(
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
    """H7: unload awaits connection cleanup and then unloads platforms."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert carrier_api.cleanup_calls >= 1
    assert carrier_api._closing is True
    assert coordinator.websocket_task is None
    assert config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.asyncio
async def test_h8_options_form_no_longer_exposes_oauth_experiments(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H8: the options form only updates infinite_holds and ignores stale keys."""
    config_entry = await setup_integration(
        options={
            CONF_INFINITE_HOLDS: True,
            _STALE_CANARY_KEY: True,
            _STALE_RECOVERY_KEY: True,
        }
    )

    form = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={CONF_INFINITE_HOLDS: False},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_INFINITE_HOLDS: False}
    assert carrier_api.constructor_kwargs == {}
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.asyncio
async def test_h9_diagnostics_include_redacted_oauth_session(
    hass: HomeAssistant,
    setup_integration: Callable[..., Any],
) -> None:
    """H9: diagnostics expose state and never include secrets or experiment flags."""
    config_entry = await setup_integration()

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["entry"]["data"][CONF_USERNAME] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    oauth_session = diagnostics["oauth_session"]
    assert oauth_session["state"] == "ACTIVE"
    assert "early_refresh_canary" not in oauth_session
    assert "invalid_grant_recovery" not in oauth_session
    assert "access_token" not in oauth_session
    assert "refresh_token" not in str(oauth_session)
    assert USERNAME not in str(oauth_session)
    assert PASSWORD not in str(oauth_session)


@pytest.mark.asyncio
async def test_h10_climate_write_still_succeeds_with_stale_option_keys(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Any],
) -> None:
    """H10: a climate write still succeeds when stale OAuth keys remain stored."""
    await setup_integration(options={_STALE_CANARY_KEY: True, _STALE_RECOVERY_KEY: False})
    entity_id = entity_id_for_unique_id(hass, CLIMATE_DOMAIN, "abc123_zone_1_thermostat")

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )

    assert any(name == "set_config_mode" for name, _payload in carrier_api.calls)
    assert carrier_api.constructor_kwargs == {}


@pytest.mark.asyncio
async def test_h11_infinite_holds_still_works_without_removed_keys(
    hass: HomeAssistant,
) -> None:
    """H11: infinite_holds still updates when the removed option keys are omitted."""
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
