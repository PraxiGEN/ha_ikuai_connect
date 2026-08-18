"""iKuai Connect 诊断平台."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN

# 在诊断导出中必须遮蔽的敏感配置键（避免凭证泄露）
_TO_REDACT_KEYS = {"token", "password", "secret"}

def _redact_entry_data(entry: ConfigEntry) -> dict[str, Any]:
    """复制 config entry 数据并遮蔽敏感字段（如 API token）。 """
    data = dict(entry.data)
    options = dict(entry.options)
    for key in _TO_REDACT_KEYS:
        if key in data:
            data[key] = "**redacted**"
        if key in options:
            options[key] = "**redacted**"
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "version": entry.version,
        "minor_version": entry.minor_version,
        "data": data,
        "options": options,
    }

def _slice_by_device(coordinator: Any, device: DeviceEntry) -> dict[str, Any]:
    """按设备 identifier 截取 ``coordinator.data`` 中与该设备相关的切片。

    设备 identifier 后缀约定（见 coordinator.py / sensor.py）：
    - ``<host>``                      主设备（负载监控）
    - ``<host>_iface_mgmt``           接口监控
    - ``<host>_security``             安全中心
    - ``<host>_maintenance``          系统维护
    - ``<host>_disk_<disk_id>``       存储磁盘
    无法识别时回退全量，保证诊断始终有数据可下载。
    """
    data = coordinator.data or {}
    host = coordinator.host

    for ident in device.identifiers:
        if len(ident) != 2 or ident[0] != DOMAIN:
            continue
        value = ident[1]
        if value == host:
            # 主设备（负载监控）
            return {
                "system": data.get("system"),
                "clients": data.get("clients"),
                "wan_balance": data.get("wan_balance"),
            }
        if value.startswith(f"{host}_iface_mgmt"):
            return {
                "interfaces": data.get("interfaces"),
                "wan_balance": data.get("wan_balance"),
            }
        if value.startswith(f"{host}_security"):
            return {"security": data.get("security")}
        if value.startswith(f"{host}_maintenance"):
            return {
                "maintenance": data.get("maintenance"),
                "backup": data.get("backup"),
            }
        if value.startswith(f"{host}_disk_"):
            disk_id = value[len(f"{host}_disk_"):]
            return {"disk": (data.get("disks") or {}).get(disk_id)}
    # 无法识别 → 回退全量
    return data

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """返回整个 config entry 的诊断信息。"""
    coordinator = entry.runtime_data
    return {
        "config_entry": _redact_entry_data(entry),
        "data": coordinator.data or {},
    }

async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """返回指定设备的诊断信息（按设备切片，避免导出全部数据）。"""
    coordinator = entry.runtime_data
    return {
        "config_entry": _redact_entry_data(entry),
        "data": _slice_by_device(coordinator, device),
    }
