"""ikuai connect 集成入口."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_TOKEN, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant

from .api import IkuaiAPI
from .const import DOMAIN, LOGGER, PLATFORMS, DEFAULT_SCAN_INTERVAL
from .coordinator import IkuaiCoordinator
from .services import async_setup_services, async_unload_services

type IkuaiConfigEntry = ConfigEntry[IkuaiCoordinator]

async def async_setup_entry(hass: HomeAssistant, entry: IkuaiConfigEntry) -> bool:
    """设置集成入口."""
    # 实例 API
    api = IkuaiAPI(hass, entry.data[CONF_HOST], entry.data[CONF_TOKEN])
    # 实例协调器
    coordinator = IkuaiCoordinator(
        hass,
        api,
        entry.data[CONF_HOST],
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    coordinator.config_entry = entry

    # 强制执行第一次成功刷新，确保平台加载时有数据
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # 注册集成级服务（单例，仅注册一次）
    await async_setup_services(hass)

    # 转发平台
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 监听选项更新
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True

async def update_listener(hass: HomeAssistant, entry: IkuaiConfigEntry) -> None:
    """当 Options 或 Data 变更时重载."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: IkuaiConfigEntry) -> bool:
    """卸载集成."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # 清空运行期数据，标记本 entry 已卸载
        entry.runtime_data = None
        # 仅当所有 entry 均卸载时，注销集成级服务
        if not any(
            e.runtime_data is not None
            for e in hass.config_entries.async_entries(DOMAIN)
        ):
            await async_unload_services(hass)
    return unload_ok
