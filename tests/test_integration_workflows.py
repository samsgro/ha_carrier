"""End-to-end Home Assistant workflow tests for Carrier integration behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from inspect import isawaitable

from carrier_api import CarrierApiAuthError, CarrierApiConnectionError
from homeassistant import config_entries
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    HVACMode,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.ha_carrier import async_migrate_entry
from custom_components.ha_carrier.const import (
    CONF_INFINITE_HOLDS,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    HEAT_SOURCE_ODU_ONLY_LABEL,
)
from custom_components.ha_carrier.util import is_unauthorized_error

from .conftest import (
    IDENTITY_ID,
    PASSWORD,
    USERNAME,
    FakeCarrierApiConnection,
    entity_id_for_unique_id,
)


@pytest.mark.asyncio
async def test_reauth_workflow_reloads_and_unloads_without_lingering_coordinator(
    hass: HomeAssistant,
    patch_carrier_api: FakeCarrierApiConnection,
) -> None:
    """Run setup, reauth, reload, and unload as one HA lifecycle workflow."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=IDENTITY_ID,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: "old"},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_PASSWORD] == PASSWORD
    await _async_unload_loaded_entry(hass, config_entry)


@pytest.mark.asyncio
async def test_options_workflow_reloads_and_unloads_without_lingering_coordinator(
    hass: HomeAssistant,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """Run setup, options update, reload, and unload as one HA lifecycle workflow."""
    config_entry = await setup_integration(options={CONF_INFINITE_HOLDS: True})
    first_coordinator = config_entry.runtime_data

    form = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={CONF_INFINITE_HOLDS: False},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_INFINITE_HOLDS] is False
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is not first_coordinator
    assert first_coordinator.websocket_task is None

    current_coordinator = config_entry.runtime_data
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert current_coordinator.websocket_task is None


@pytest.mark.asyncio
async def test_scheduled_refresh_uses_energy_path_and_unload_cancels_future_refresh(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """Advance HA time through a scheduled refresh and then unload cleanly."""
    config_entry = await setup_integration()
    carrier_api.calls.clear()

    async_fire_time_changed(
        hass,
        dt_util.utcnow() + timedelta(minutes=DEFAULT_UPDATE_INTERVAL_MINUTES),
    )
    await hass.async_block_till_done()

    assert [call[0] for call in carrier_api.calls] == ["get_energy"]
    coordinator = config_entry.runtime_data
    await _async_unload_loaded_entry(hass, config_entry)

    carrier_api.calls.clear()
    async_fire_time_changed(
        hass,
        dt_util.utcnow() + timedelta(minutes=DEFAULT_UPDATE_INTERVAL_MINUTES),
    )
    await hass.async_block_till_done()

    assert coordinator.websocket_task is None
    assert carrier_api.calls == []


@pytest.mark.asyncio
async def test_refresh_failure_and_recovery_update_poll_interval_in_ha_workflow(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """Exercise HA coordinator refresh failure and recovery interval changes."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data
    coordinator.data_flush = True
    carrier_api.load_data_error = CarrierApiConnectionError("temporary")

    await coordinator.async_refresh()

    assert coordinator.last_exception is not None
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.update_interval == timedelta(minutes=1)

    carrier_api.load_data_error = None
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.update_interval == timedelta(minutes=DEFAULT_UPDATE_INTERVAL_MINUTES)


@pytest.mark.asyncio
async def test_websocket_callback_updates_timestamp_and_survives_entry_unload(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """Drive registered websocket callbacks and then unload the HA entry."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data

    for callback in carrier_api.api_websocket.callbacks:
        result = callback("{}")
        if isawaitable(result):
            await result
    await hass.async_block_till_done()

    assert coordinator.timestamp_websocket is not None
    await _async_unload_loaded_entry(hass, config_entry)
    assert coordinator.websocket_task is None


@pytest.mark.asyncio
async def test_service_workflow_still_writes_after_config_entry_reload(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """Call HA services before and after a config-entry reload."""
    config_entry = await setup_integration()
    climate_entity_id = entity_id_for_unique_id(hass, CLIMATE_DOMAIN, "abc123_zone_1_thermostat")
    select_entity_id = entity_id_for_unique_id(hass, SELECT_DOMAIN, "abc123_heat_source")

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )
    assert carrier_api.calls[-1][0] == "set_config_mode"

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: select_entity_id, ATTR_OPTION: HEAT_SOURCE_ODU_ONLY_LABEL},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert carrier_api.calls[-1][0] == "set_heat_source"
    assert hass.states.get(climate_entity_id) is not None
    assert hass.states.get(select_entity_id) is not None


@pytest.mark.asyncio
async def test_registry_migration_workflow_preserves_entities_through_setup(
    hass: HomeAssistant,
    patch_carrier_api: FakeCarrierApiConnection,
) -> None:
    """Migrate legacy registry IDs, set up HA, and verify no stale IDs remain."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    legacy_sensor = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        "ABC123_Outdoor Temperature",
        config_entry=config_entry,
    )
    legacy_climate = ent_reg.async_get_or_create(
        "climate",
        DOMAIN,
        "ABC123_Living Room",
        config_entry=config_entry,
    )

    assert await async_migrate_entry(hass, config_entry)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.version == 3
    assert config_entry.unique_id == IDENTITY_ID
    migrated_sensor = ent_reg.async_get(legacy_sensor.entity_id)
    migrated_climate = ent_reg.async_get(legacy_climate.entity_id)
    assert migrated_sensor is not None
    assert migrated_sensor.unique_id == "abc123_outdoor_temperature"
    assert migrated_climate is not None
    assert migrated_climate.unique_id == "abc123_zone_1_thermostat"
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, "ABC123_Outdoor Temperature") is None
    assert ent_reg.async_get_entity_id("climate", DOMAIN, "ABC123_Living Room") is None


@pytest.mark.asyncio
async def test_reauth_probe_reloads_and_aborts_flow_on_successful_login(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Self-heal a parked reauth probe by aborting the flow and reloading."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data
    assert config_entry.state is ConfigEntryState.LOADED

    async def instant_probe_sleep(_delay: float) -> None:
        """Skip the 30-minute probe interval without touching asyncio.sleep."""
        return

    monkeypatch.setattr(
        "custom_components.ha_carrier.carrier_data_update_coordinator._async_reauth_probe_sleep",
        instant_probe_sleep,
    )
    form = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    assert form["type"] is FlowResultType.FORM

    rejected = CarrierApiAuthError("access rejected", reason="access_rejected")
    carrier_api.load_data_errors = [rejected]
    coordinator.data_flush = True
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    probe = coordinator.reauth_probe_task
    if probe is not None and not probe.done():
        await probe
    await hass.async_block_till_done()

    assert carrier_api.login_calls == 1
    progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert not any(
        (item.get("context") or {}).get("source") == config_entries.SOURCE_REAUTH
        for item in progress
    )
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.asyncio
async def test_reauth_probe_stays_idle_on_login_failed(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep probing after login_failed without reloading the entry."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data
    first_coordinator = coordinator
    carrier_api.login_error = CarrierApiAuthError("login failed", reason="login_failed")
    carrier_api.load_data_error = CarrierApiAuthError("unauthorized")

    async def sleep_until_two_probe_logins(_delay: float) -> None:
        """Skip the probe interval and unpark after two failed probe logins."""
        if carrier_api.login_calls >= 3:
            coordinator._reauth_parked = False

    monkeypatch.setattr(
        "custom_components.ha_carrier.carrier_data_update_coordinator._async_reauth_probe_sleep",
        sleep_until_two_probe_logins,
    )
    coordinator.data_flush = True
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    probe = coordinator.reauth_probe_task
    assert probe is not None

    async def hold_updates() -> list[dict[str, object]]:
        """Prevent a healthy refresh from unparking the probe mid-interval."""
        raise UpdateFailed("hold coordinator refresh while the reauth probe runs")

    monkeypatch.setattr(coordinator, "_async_update_data", hold_updates)
    coordinator.update_interval = None
    await probe
    await hass.async_block_till_done()

    assert carrier_api.login_calls >= 3
    assert config_entry.runtime_data is first_coordinator
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.asyncio
async def test_reauth_probe_cancelled_on_unload(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """Cancel the reauth probe during unload so it cannot linger."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data
    coordinator._reauth_parked = True
    coordinator._start_reauth_probe()
    probe_task = coordinator.reauth_probe_task
    assert probe_task is not None

    await _async_unload_loaded_entry(hass, config_entry)

    assert coordinator.reauth_probe_task is None
    assert probe_task.cancelled() or probe_task.done()


@pytest.mark.asyncio
async def test_websocket_and_coordinator_refresh_share_one_client_recovery(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """Overlapping coordinator, energy, websocket, and write 401s share one login."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data
    rejected_generation = carrier_api._generation
    carrier_api.rejected_generation = rejected_generation
    carrier_api.auth_wave_target = 4
    carrier_api.login_hold = asyncio.Event()
    carrier_api.calls.clear()
    carrier_api.login_calls = 0
    carrier_api.login_started.clear()

    async def full_refresh_with_gap3() -> None:
        """Run a full refresh through the Gap 3(a) unauthorized handler."""
        try:
            await coordinator._async_full_refresh()
        except BaseException as error:
            if is_unauthorized_error(error):
                await coordinator._async_final_login_then_retry(
                    error, coordinator._async_full_refresh, "full data refresh"
                )
                return
            raise

    async def energy_refresh_with_gap3() -> None:
        """Run an energy refresh through the Gap 3(a) unauthorized handler."""
        try:
            await coordinator._async_energy_refresh()
        except BaseException as error:
            if is_unauthorized_error(error):
                await coordinator._async_final_login_then_retry(
                    error, coordinator._async_energy_refresh, "energy refresh"
                )
                return
            raise

    async def websocket_requested_refresh() -> None:
        """Run a websocket-requested full refresh through Gap 3(a)."""
        try:
            await coordinator._async_full_refresh()
        except BaseException as error:
            if is_unauthorized_error(error):
                await coordinator._async_final_login_then_retry(
                    error, coordinator._async_full_refresh, "websocket refresh"
                )
                return
            raise

    async def write_against_rejected_generation() -> None:
        """Issue a write against the same rejected generation."""
        await carrier_api.set_config_mode(
            system_serial=carrier_api.systems[0].profile.serial,
            mode="off",
        )

    tasks = [
        asyncio.create_task(full_refresh_with_gap3()),
        asyncio.create_task(energy_refresh_with_gap3()),
        asyncio.create_task(websocket_requested_refresh()),
        asyncio.create_task(write_against_rejected_generation()),
    ]
    await carrier_api.auth_wave_ready.wait()
    assert carrier_api.auth_wave_count >= 4
    await carrier_api.login_started.wait()
    assert any(not task.done() for task in tasks)
    carrier_api.login_hold.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert carrier_api.login_calls == 1
    assert carrier_api._generation == rejected_generation + 1
    assert sum(isinstance(result, BaseException) for result in results) == 1
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.asyncio
async def test_sibling_refresh_recovers_while_fallback_holds_no_recovery(
    hass: HomeAssistant,
    carrier_api: FakeCarrierApiConnection,
    setup_integration: Callable[..., Awaitable[ConfigEntry]],
) -> None:
    """A websocket refresh started outside Gap 3(a) still recovers once."""
    config_entry = await setup_integration()
    coordinator = config_entry.runtime_data
    coordinator.data_flush = True
    carrier_api.calls.clear()
    carrier_api.login_calls = 0
    carrier_api.login_started.clear()
    carrier_api.no_recovery_entered.clear()
    carrier_api.load_data_errors = [CarrierApiAuthError("unauthorized")]
    fallback_hold = asyncio.Event()
    carrier_api.no_recovery_hold = fallback_hold

    task_a = asyncio.create_task(coordinator._async_update_data())
    await asyncio.wait_for(carrier_api.no_recovery_entered.wait(), timeout=2)
    assert carrier_api.login_calls == 1
    assert not task_a.done()
    generation_at_hold = carrier_api._generation
    carrier_api.rejected_generation = generation_at_hold
    carrier_api.no_recovery_hold = None
    carrier_api.login_started.clear()
    carrier_api.no_recovery_entered.clear()

    async def sibling_websocket_refresh() -> list[dict[str, object]]:
        """Run a websocket-requested refresh through the coordinator."""
        return await coordinator._async_update_data()

    task_b = asyncio.create_task(sibling_websocket_refresh())
    await asyncio.wait_for(carrier_api.login_started.wait(), timeout=2)
    b_result = await asyncio.wait_for(task_b, timeout=2)
    fallback_hold.set()
    a_result = await asyncio.wait_for(task_a, timeout=2)

    assert b_result
    assert a_result
    assert carrier_api.login_calls == 2
    assert carrier_api._generation == generation_at_hold + 1
    assert coordinator._reauth_parked is False
    assert coordinator.reauth_probe_task is None
    assert config_entry.state is ConfigEntryState.LOADED


async def _async_unload_loaded_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> None:
    """Unload a loaded Carrier entry and let HA settle pending tasks.

    Args:
        hass: Home Assistant test instance.
        config_entry: Config entry to unload when still loaded.
    """
    await hass.async_block_till_done()
    if config_entry.state is ConfigEntryState.LOADED:
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
