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

    # 选项流基类为 OptionsFlowWithReload，流结束后框架自动 reload；
    # 不可再注册 update_listener（官方规定二者不可共存，会 raise ValueError）。
    return True

async def async_unload_entry(hass: HomeAssistant, entry: IkuaiConfigEntry) -> bool:
    """卸载集成."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # runtime_data 由框架在卸载成功后自动 delattr 清空（无类级默认值），
        # 必须用 getattr 防御式取值。判定「是否还有其他已加载 entry」时，
        # 排除当前正在卸载的 entry 本身。
        if not any(
            getattr(other, "runtime_data", None) is not None
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        ):
            await async_unload_services(hass)
    return unload_ok
