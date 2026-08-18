"""iKuai Connect 集成级服务（单例注册）."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv, device_registry as dr
import homeassistant.util.dt as dt_util

from .const import DOMAIN, LOGGER
from .coordinator import IkuaiCoordinator


def _get_coordinator(hass: HomeAssistant, device_id: str | None = None) -> IkuaiCoordinator:
    """根据 device_id 获取对应 coordinator，未指定时自动选择唯一 entry."""
    loaded_entry_ids = hass.data.get(DOMAIN, {}).get("loaded_entries", set())
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id in loaded_entry_ids
    ]

    if not entries:
        raise ValueError("没有已加载的 iKuai Connect 配置")

    if device_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(device_id)
        if device and device.config_entries:
            for entry in entries:
                if entry.entry_id in device.config_entries:
                    return entry.runtime_data
        raise ValueError(f"找不到设备 ID 对应的路由器: {device_id}")

    if len(entries) == 1:
        return entries[0].runtime_data

    raise ValueError(
        "存在多个路由器配置，请通过 device_id 指定目标设备"
    )


async def async_setup_services(hass: HomeAssistant) -> None:
    """注册集成级服务（仅注册一次）。"""
    if hass.data.setdefault(DOMAIN, {}).get("services_registered"):
        return
    hass.data[DOMAIN]["services_registered"] = True

    # ---获取流量排行---
    async def async_get_traffic_ranking(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        res = await coordinator.api.get_client_traffic_summary()
        return {
            "total_flow_mb": round(res.get("terminal_total_flow", 0) / 1024 / 1024, 2),
            "devices": [
                {
                    "name": d.get("comment") or d.get("termname") or d.get("mac"),
                    "ip": d.get("ip_addr"),
                    "mac": d.get("mac"),
                    "total_mb": round(d.get("sum_total", 0) / 1024 / 1024, 2),
                    "up_mb": round(d.get("sum_total_up", 0) / 1024 / 1024, 2),
                    "down_mb": round(d.get("sum_total_down", 0) / 1024 / 1024, 2),
                }
                for d in res.get("terminal", [])
            ]
        }

    # ---获取特定设备的协议分布---
    async def async_get_protocol_stats(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        mac = call.data["mac"].lower().replace("-", ":")
        ip = call.data.get("ip")

        if not ip:
            client_info = coordinator.data.get("clients", {}).get(mac)
            if client_info:
                ip = client_info.get("ip_addr")

        if not ip:
            return {"error": "无法获取该设备的IP地址，请手动输入IP"}

        res = await coordinator.api.get_client_protocol_stats(mac, ip)

        protocol_data = [
            {
                "name": p.get("proto_name"),
                "total_mb": round(p.get("total", 0) / 1024 / 1024, 2)
            }
            for p in res.get("data", [])
            if p.get("total", 0) > 0
        ]

        return {
            "mac": mac,
            "ip": ip,
            "protocols": sorted(protocol_data, key=lambda x: x["total_mb"], reverse=True)
        }

    # ---查询离线历史---
    async def async_get_offline_history(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        res = await coordinator.api.get_offline_history()

        raw_history = res.get("offline_data", [])
        history_list = []

        for d in raw_history:
            name = (
                d.get("termname")
                or d.get("client_model")
                or d.get("comment")
                or f"Client {d.get('mac', '')[-5:]}"
            )

            total_bytes = int(d.get("total_up", 0)) + int(d.get("total_down", 0))
            total_mb = round(total_bytes / 1048576, 2)

            logout_ts = d.get("logout_time", 0)
            offline_time = dt_util.as_local(
                dt_util.utc_from_timestamp(logout_ts)
            ).strftime("%Y-%m-%d %H:%M:%S") if logout_ts else "Unknown"

            history_list.append({
                "name": name,
                "mac": d.get("mac"),
                "ip": d.get("ip_addr"),
                "offline_at": offline_time,
                "total_usage_mb": total_mb,
                "client_type": d.get("client_type"),
                "vendor": d.get("client_vendor")
            })

        return {"history": history_list}

    # ---添加 MAC 访问控制规则---
    async def async_add_mac_rule(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        mac = call.data["mac"].lower().replace("-", ":")
        payload = {
            "mac": mac,
            "enabled": "yes",
            "tagname": call.data.get("tagname", f"HA_{mac[-5:]}"),
            "comment": call.data.get("comment", "Added by HA"),
            "expires": call.data.get("expires", 0),
            "strategy": "day", "cycle_time": "all", "time": "00:00-23:59"
        }

        await coordinator.api.add_mac_rule(payload)
        await coordinator.async_request_refresh()

    # ---删除 MAC 访问控制规则---
    async def async_delete_mac_rule(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data.get("device_id"))
        rule_id = call.data["rule_id"]
        await coordinator.api.delete_mac_rule(rule_id)
        await coordinator.async_request_refresh()

    # ---注册服务---
    hass.services.async_register(
        DOMAIN, "get_traffic_ranking", async_get_traffic_ranking,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "get_protocol_stats", async_get_protocol_stats,
        supports_response=SupportsResponse.ONLY,
        schema=vol.Schema({
            vol.Optional("device_id"): cv.string,
            vol.Required("mac"): cv.string,
            vol.Optional("ip"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, "get_offline_history", async_get_offline_history,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "add_mac_rule", async_add_mac_rule,
        schema=vol.Schema({
            vol.Optional("device_id"): cv.string,
            vol.Required("mac"): cv.string,
            vol.Optional("tagname"): cv.string,
            vol.Optional("comment"): cv.string,
            vol.Optional("expires"): cv.positive_int,
        }),
    )
    hass.services.async_register(
        DOMAIN, "delete_mac_rule", async_delete_mac_rule,
        schema=vol.Schema({
            vol.Optional("device_id"): cv.string,
            vol.Required("rule_id"): cv.positive_int,
        }),
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """当最后一个 entry 卸载时，注销集成级服务。"""
    loaded_entry_ids = hass.data.get(DOMAIN, {}).get("loaded_entries", set())
    if loaded_entry_ids:
        return  # 还有其他 entry 在运行，不注销服务

    for service in (
        "get_traffic_ranking",
        "get_protocol_stats",
        "get_offline_history",
        "add_mac_rule",
        "delete_mac_rule",
    ):
        hass.services.async_remove(DOMAIN, service)

    hass.data.get(DOMAIN, {}).pop("services_registered", None)
