"""iKuai Connect 数据协调器."""
from __future__ import annotations

from datetime import timedelta
import time
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from .helpers import extract_name_from_label, normalize_mac
from .const import (
    DOMAIN,
    LOGGER,
    CONF_TRACKER_CONFIG,
    CONF_OFFLINE_GRACE_PERIOD,
    DEFAULT_OFFLINE_GRACE_PERIOD,
)

class IkuaiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """处理 OpenAPI 数据清洗."""

    def __init__(self, hass, api, host, interval):
        super().__init__(
            hass, LOGGER, name=f"{DOMAIN}_{host}",
            update_interval=timedelta(seconds=interval),
        )
        self.api = api
        self.host = host
        self.gwid = None  # 主网关 ID
        self.last_presence_id = None
        self.last_ddns_id = None
        self.last_wifi_id = None
        self.last_system_log_id = None
        self._hostname = "iKuai"
        self._last_seen: dict[str, float] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """抓取并清洗数据."""
        try:
            # 异步并发抓取所有端点的数据
            results = await self.api.get_all_data()

            # ---安全解包：将异常/非字典结果降级为空字典，避免 AttributeError 拖垮整体更新---
            def _safe(result):
                if isinstance(result, Exception):
                    LOGGER.warning("API 请求失败，降级为空数据: %s", result)
                    return {}
                return result if isinstance(result, dict) else {}

            results = [_safe(r) for r in results]

            # --- 正确解包变量 (顺序必须与 api.py 完全一致) ---
            (
                sys_res,            # 0 系统信息（get_system_info）
                clients_res,        # 1 终端列表（get_lan_devices）
                wifi_stats_res,     # 2 无线统计（get_wifi_stats）
                wifi_score_res,     # 3 无线评分（get_wifi_score）
                v6_res,             # 4 IPv6 流量（get_v6_traffic）

                iface_status_res,   # 5 线路状态（get_iface_status）
                msg_center_res,     # 6 消息中心（get_message_center）
                presence_log_res,   # 7 上下线日志（get_offline_history）
                ddns_log_res,      # 8 DDNS 日志（get_ddns_logs）
                wireless_log_res,  # 9 无线日志（get_wireless_logs）

                system_log_res,    # 10 系统日志（get_system_logs）

                mac_mode_res,       # 11 MAC 模式（get_mac_mode）
                mac_rules_res,      # 11 MAC 规则（get_mac_rules）
                backup_res,         # 12 备份列表（get_backup_list）
                up_info_res,        # 13 升级信息（get_upgrade_info）
                up_status_res,      # 14 升级状态（get_upgrade_status）
                disks_res           # 15 磁盘信息（get_disks）
            ) = results

            # ---基础元数据提取 --- 包括主机名、系统版本、硬件版本等 (供设备信息使用)
            sysinfo = sys_res.get("sysinfo", {}) if isinstance(sys_res, dict) else {}
            verinfo = sysinfo.get("verinfo", {})
            self._hostname = sysinfo.get("hostname", "iKuai")
            self._sw_version = verinfo.get("version", "Unknown")
            self._hw_version = verinfo.get("arch", "Unknown")
            ver_string = verinfo.get("verstring", "Unknown")

            mem = sysinfo.get("memory", {})
            users = sysinfo.get("online_user", {})
            stream = sysinfo.get("stream", {})

            #获取爱快硬件唯一的 gwid
            if not self.gwid:
                self.gwid = sysinfo.get("gwid") or self.config_entry.entry_id

            # ---WAN IPv4 提取（汇总所有在线 WAN 拨号线路的 IP，适配多拨/多 WAN）---
            iface_check_list = iface_status_res.get("iface_check", []) if isinstance(iface_status_res, dict) else []
            wan_v4_list = []
            for check in iface_check_list:
                ip = check.get("ip_addr")
                if ip and ip != "--" and str(check.get("result", "")).lower() in ("success", "ok", "1"):
                    wan_v4_list.append(ip)
            wan_v4_ip = ", ".join(wan_v4_list) if wan_v4_list else "Disconnected"

            # ---IPv6 流量与连接数汇总 ---
            v6_data_list = v6_res.get("data", []) if isinstance(v6_res, dict) else []
            # 分口 IPv6 映射，供接口设备生成 WAN IPv6 传感器
            v6_by_iface = {item.get("interface"): item for item in v6_data_list if isinstance(item, dict)}
            v6_total = {"up": 0, "down": 0, "t_up": 0, "t_down": 0, "conn": 0}
            for v6_item in v6_data_list:
                v6_total["up"] += int(v6_item.get("upload", 0))
                v6_total["down"] += int(v6_item.get("download", 0))
                v6_total["t_up"] += int(v6_item.get("total_upload", 0))
                v6_total["t_down"] += int(v6_item.get("total_download", 0))
                v6_total["conn"] += int(v6_item.get("conn", 0))

            # ---构建 processed_sys (主设备) ---
            processed_sys = {
                "cpu_load": float(sysinfo.get("cpu", ["0%"])[0].replace("%", "")),
                "memory_usage": float(mem.get("used", "0%").replace("%", "")),
                "memory_detail": {k: v for k, v in mem.items() if k != "used"},
                "uptime": int(sysinfo.get("uptime", 0)),
                "temperature": float(sysinfo.get("cputemp", [0])[0]) if sysinfo.get("cputemp") else 0.0,
                "ver_string": ver_string,
                "verinfo": verinfo,
                "wan_ip_v4": wan_v4_ip,
                "online_users": int(users.get("count", 0)),
                "online_user_detail": {k: v for k, v in users.items() if k != "count"},
                "connection_count": int(stream.get("connect_num", 0)),
                "connect_detail": {
                    "tcp": stream.get("tcp_connect_num"), "udp": stream.get("udp_connect_num"), 
                    "icmp": stream.get("icmp_connect_num"), "ipv6": v6_total["conn"]
                },
                "upload": int(stream.get("upload", 0)), "download": int(stream.get("download", 0)),
                "total_up": int(stream.get("total_up", 0)), "total_down": int(stream.get("total_down", 0)),
                "v6_stats": {
                    "upload_speed_v6": v6_total["up"], "download_speed_v6": v6_total["down"], 
                    "total_upload_v6": v6_total["t_up"], "total_download_v6": v6_total["t_down"]
                }
            }

            # ---处理无线监控 (AP) ---
            wifi_data = wifi_stats_res if isinstance(wifi_stats_res, dict) else {}
            ap_status = wifi_data.get("ap_status", {})
            clt_status = wifi_data.get("clt_status", {})
            wifi_score_data = wifi_score_res if isinstance(wifi_score_res, dict) else {}
            net_score = wifi_score_data.get("total_count_net_status", {})
            processed_sys.update({
                "ap_online": int(ap_status.get("ap_online", 0)),
                "wireless_detail": {
                    # AP 状态详情
                    "total_ap": ap_status.get("ap_count"),
                    "offline_ap": ap_status.get("ap_offline"),
                    "roaming_supported": ap_status.get("ap_roaming"),
                    "prefer_5g_aps": ap_status.get("ap_perfer_5g"),
                    # 无线终端分布
                    "clients_2g": clt_status.get("clt_count_2g"),
                    "clients_5g": clt_status.get("clt_count_5g"),
                    "active_clients": clt_status.get("clt_active"),
                    # 无线质量评分属性
                    "signal_coverage": f"{net_score.get('coverage', 0)}%",
                    "network_delay": f"{net_score.get('delay', 0)}ms",
                    "packet_loss": f"{net_score.get('dropptk', 0)}%",
                    "airtime_health_score": net_score.get("score_chutil_load"),
                }
            })

            # --- 终端映射 (Clients) ---
            now = time.time()
            tracker_config = self.config_entry.options.get(CONF_TRACKER_CONFIG, {})
            grace_seconds = self.config_entry.options.get(CONF_OFFLINE_GRACE_PERIOD, DEFAULT_OFFLINE_GRACE_PERIOD)            
            # 拿到 API 当前实时在线的列表
            api_online_map = {}
            if isinstance(clients_res, dict):
                for c in clients_res.get("data", []):
                    if "mac" not in c: continue
                    
                    mac_l = normalize_mac(c["mac"])
                    
                    fallback_name = (
                        c.get("termname") 
                        or c.get("client_model") 
                        or extract_name_from_label(c.get("comment")) 
                        or f"Client {mac_l.replace(':', '')[-4:]}"
                    )
                    c["display_name"] = fallback_name
                    api_online_map[mac_l] = c

            previous_clients = self.data.get("clients", {}) if self.data and isinstance(self.data, dict) else {}
            final_clients_map = {}
            
            for mac_lower, device_conf in tracker_config.items():
                if mac_lower in api_online_map:
                    self._last_seen[mac_lower] = now
                    final_clients_map[mac_lower] = api_online_map[mac_lower]
                else:
                    last_seen_ts = self._last_seen.get(mac_lower, 0)
                    elapsed = now - last_seen_ts
                    dev_grace = device_conf.get("buffer", grace_seconds)
                    
                    if elapsed < dev_grace:
                        # 沿用缓存数据，如果没有则创建一个带基本名称的字典
                        final_clients_map[mac_lower] = previous_clients.get(
                            mac_lower, 
                            {"mac": mac_lower, "ip_addr": "unknown", "offline_buffering": True}
                        )
                    else:
                        # 【真正离线】：不加入 final_clients_map
                        LOGGER.debug("设备 %s 离线超时，设置为离开", mac_lower)

            # ---接口监控管理子设备---
            # ---处理接口监控 (Interfaces) ---
            processed_ifaces = {}
            iface_stream_list = iface_status_res.get("iface_stream", []) if isinstance(iface_status_res, dict) else []
            iface_check_list = iface_status_res.get("iface_check", []) if isinstance(iface_status_res, dict) else []
            check_by_iface = {i.get("interface"): i for i in iface_check_list}
            # 父口 → 子线路映射，用于聚合父口（如 wan1）的在线状态推导
            parent_to_children = {}
            for c in iface_check_list:
                parent_to_children.setdefault(c.get("parent_interface"), []).append(c)

            for s in iface_stream_list:
                logic_name = s.get("interface")
                chk = check_by_iface.get(logic_name)
                v6 = v6_by_iface.get(logic_name)
                if chk is not None:
                    # 真实拨号线路（adsl / vwan / pppoe 等）：用 result 判连断
                    connected = str(chk.get("result", "")).lower() in ("success", "ok", "1")
                    is_wan_line = True
                elif logic_name.startswith("wan"):
                    # 聚合父口（如 wan1）：在线 = 任一子线路在线
                    children = parent_to_children.get(logic_name, [])
                    connected = any(str(c.get("result", "")).lower() in ("success", "ok", "1") for c in children)
                    is_wan_line = True
                else:
                    connected = False
                    is_wan_line = False
                processed_ifaces[logic_name] = {
                    "ip": s.get("ip_addr") if s.get("ip_addr") not in ("--", None) else "",
                    "upload_speed": int(s.get("upload", 0)), "download_speed": int(s.get("download", 0)),
                    "total_up": int(s.get("total_up", 0)), "total_down": int(s.get("total_down", 0)),
                    # WAN 拨号状态：internet 字段为拨号协议类型（PPPOE/DHCP），非公网可达
                    "connected": connected,
                    "protocol": chk.get("internet") if chk else None,
                    "gateway": chk.get("gateway") if chk else None,
                    "auto_switch": chk.get("auto_switch") if chk else None,
                    "errmsg": chk.get("errmsg") if chk else None,
                    "parent_interface": chk.get("parent_interface") if chk else None,
                    "is_wan_line": is_wan_line,
                    # has_v6：该接口是否在 interfaces-traffic-v6 中真实返回了数据行，
                    # 即「本线路开启了 IPv6」（未开启则接口完全不出现于该接口响应）。
                    # 用于传感器平台按真实配置动态排除 IPv6 实体，兼容不同用户的网口拓扑。
                    "has_v6": isinstance(v6, dict),
                    # 分口 IPv6 流量（total 字段为字符串，需 int 化；无则返回 0）
                    "v6_upload_speed": int(v6.get("upload", 0)) if isinstance(v6, dict) else 0,
                    "v6_download_speed": int(v6.get("download", 0)) if isinstance(v6, dict) else 0,
                    "v6_total_up": int(v6.get("total_upload") or 0) if isinstance(v6, dict) else 0,
                    "v6_total_down": int(v6.get("total_download") or 0) if isinstance(v6, dict) else 0,
                    "v6_conn": int(v6.get("conn", 0)) if isinstance(v6, dict) else 0,
                }

            # ---系统维护管理子设备---
            # ---日志---
            def get_new_events(res_data, last_id_attr):
                if not isinstance(res_data, dict): 
                    return [], getattr(self, last_id_attr)
                
                # ---兼容嵌套结构 ---
                data_list = res_data.get("data")
                if data_list is None:
                    data_list = res_data.get("results", {}).get("data", [])
                
                if not data_list: 
                    return [], getattr(self, last_id_attr)
                
                curr_max_id = data_list[0].get("id", 0)
                last_id = getattr(self, last_id_attr)
                
                # 冷启动：激活最新一条
                if last_id is None:
                    setattr(self, last_id_attr, curr_max_id - 1)
                    last_id = curr_max_id - 1
                
                new_items = []
                if curr_max_id > last_id:
                    # 只取比上次记录 ID 更大的新数据
                    new_items = sorted(
                        [item for item in data_list if item.get("id", 0) > last_id],
                        key=lambda x: x.get("id", 0)
                    )
                    setattr(self, last_id_attr, curr_max_id)
                return new_items, getattr(self, last_id_attr)

            # 提取三类新事件
            new_presence, _ = get_new_events(presence_log_res, "last_presence_id")
            new_ddns, _ = get_new_events(ddns_log_res, "last_ddns_id")
            new_wifi, _ = get_new_events(wireless_log_res, "last_wifi_id")
            new_system, _ = get_new_events(system_log_res, "last_system_log_id")

            # ---处理消息中心增量---
            # 实测 message-center 条目不含 id / timestamp，仅含 status/type/detail/title，
            # 故无法用 id 游标；改用「内容签名」去重（type|title|detail）。
            # 请求按 order_by=id 降序返回，新增条目出现在队首，签名未出现过的即为新消息。
            new_messages = []
            msg_raw = msg_center_res if isinstance(msg_center_res, dict) else {}
            msg_res_data = msg_raw.get("data")
            if msg_res_data is None:
                msg_res_data = msg_raw.get("results", {}).get("data", [])
            if msg_res_data:
                if not hasattr(self, "_seen_msg_sigs"):
                    self._seen_msg_sigs = set()
                for m in msg_res_data:
                    sig = "|".join(str(m.get(k)) for k in ("type", "title", "detail"))
                    if sig not in self._seen_msg_sigs:
                        self._seen_msg_sigs.add(sig)
                        new_messages.append(m)
                # 控制内存：仅保留最近 200 条签名
                if len(self._seen_msg_sigs) > 200:
                    self._seen_msg_sigs = set(list(self._seen_msg_sigs)[-100:])

            # ---安全管理子设备---
            # ---处理安全管理 (Security) ---
            processed_security = {
                "mac_mode_code": mac_mode_res.get("acl_mac", 0) if isinstance(mac_mode_res, dict) else 0,
                "mac_rules": {str(r["id"]): r for r in (mac_rules_res.get("data", []) if isinstance(mac_rules_res, dict) else []) if "id" in r}
            }

            # ---处理升级与备份 (Backup/Upgrade) ---
            # 备份列表中找最新的一个，提取文件名、大小、版本等信息
            latest_backup = {}
            if isinstance(backup_res, dict):
                b_info = backup_res.get("backup_info", [])
                if b_info:
                    top = sorted(b_info, key=lambda x: x.get("timestamp", 0), reverse=True)[0]
                    latest_backup = {"latest_filename": top.get("filename"), "detail": {"backtype": top.get("backtype"), "filesize": top.get("filesize"), "version": top.get("version")}}
            
            # 升级信息中提取当前版本、最新版本、升级日志等，并根据状态码判断是否正在升级或可升级
            up_data = up_info_res.get("data", {}) if isinstance(up_info_res, dict) else {}
            up_stat_info = up_status_res.get("auto_upgrade", {}) if isinstance(up_status_res, dict) else {}
            curr_ver = up_data.get("system_ver")
            new_ver = up_data.get("new_system_ver")
            # status: 0=空闲, 1=下载中, 2=安装中, <0=失败
            status_code = up_stat_info.get("status", 0)
            status_msg = up_stat_info.get("status_msg", "")
            # 计算显示状态逻辑
            if status_code != 0:
                # 正在升级（下载或安装）
                display_up = status_msg if status_msg else "正在处理升级..."
            elif new_ver and new_ver != curr_ver:
                # 有新版本
                display_up = f"发现新版本: {new_ver}"
            else:
                # 已是最新
                display_up = "已是最新版本"

            processed_maint = {
                "upgrade_display_state": display_up,
                "upgrade_detail": {
                    "current_version": curr_ver,
                    "latest_version": new_ver,
                    "version_type": up_data.get("version_type"),
                    "build_date": up_data.get("build_date"),
                    "update_content": up_data.get("update_content", "无更新说明"),
                    "last_check": time.strftime('%Y-%m-%d %H:%M:%S')
                }
            }

            # ---存储磁盘子设备---
            # ---处理磁盘存储 (Storage) ---
            PURPOSE_MAP = {"0": "普通储存", "1": "有余繁星", "2": "视频缓存", "3": "行为记录", "4": "钉钉闪传"}
            processed_disks = {}
            disk_raw = disks_res.get("data", []) if isinstance(disks_res, dict) else []

            for d in disk_raw:
                disk_id = d.get("disk")
                total_bytes = 0
                used_bytes = 0
                partitions = []

                for p in d.get("partition", []):
                    m = p.get("mounted") or {}
                    mt_total = int(m.get("mt_total") or 0)
                    mt_used = int(m.get("mt_used") or 0)

                    # 累加磁盘总量与使用量
                    if mt_total > 0:
                        total_bytes += mt_total
                        used_bytes += mt_used

                    # 处理 usage 字段，避免重复百分号
                    mt_uses = m.get("mt_uses")
                    if isinstance(mt_uses, str) and mt_uses.endswith("%"):
                        usage = mt_uses
                    else:
                        usage = f"{mt_uses}%" if mt_uses is not None else "未知"

                    # purpose 映射，统一转字符串
                    purpose_key = str(m.get("mt_purpose"))
                    purpose = PURPOSE_MAP.get(purpose_key, "未知")
                    partitions.append({
                        "name": p.get("name"),
                        "usage": usage,
                        "mount": m.get("mt_name"),
                        "purpose": purpose
                    })

                # 计算磁盘使用率
                usage_pct = round(used_bytes / total_bytes * 100, 1) if total_bytes > 0 else 0
                processed_disks[disk_id] = {
                    "base_info": {
                        "model": d.get("model"),
                        "disk": disk_id,
                        "system": d.get("system"),
                        "type": d.get("type"),
                        "block_size": d.get("block_size")
                    },
                    "state": {
                        "disk_physical_size": d.get("size"),
                        "disk_usage_rate": usage_pct,
                        "disk_used_capacity": used_bytes
                    },
                    "partitions": partitions
                }

            # ---多 WAN 负载均衡快照（只读派生，基于各 WAN 线路实时速率占比）---
            wan_line_names = [n for n, v in processed_ifaces.items() if v.get("is_wan_line")]
            total_wan_down = sum(processed_ifaces[n]["download_speed"] for n in wan_line_names) or 1
            balance_lines = {}
            for n in wan_line_names:
                v = processed_ifaces[n]
                d = v["download_speed"]
                balance_lines[n] = {
                    "protocol": v.get("protocol"),
                    "ipv4": v.get("ip"),
                    "connected": v.get("connected"),
                    "upload_speed": v["upload_speed"],
                    "download_speed": d,
                    "download_share": round(d / total_wan_down * 100, 1),
                    "v6_download_speed": v.get("v6_download_speed", 0),
                }
            active_wan = [n for n in wan_line_names if processed_ifaces[n]["connected"]]
            wan_balance = {
                "_state": f"{len(active_wan)}/{len(wan_line_names)} 在线" if active_wan else "全部离线",
                "lines": balance_lines,
            }

            # --- 整合所有模块 ---
            return {
                "system": processed_sys,
                "clients": final_clients_map,
                "interfaces": processed_ifaces,
                "wan_balance": wan_balance,
                "backup": latest_backup,
                "maintenance": processed_maint,
                "disks": processed_disks,
                "security": processed_security,
                "events": {
                    "presence": new_presence,
                    "ddns": new_ddns,
                    "wifi": new_wifi,
                    "system": new_system,
                    "messages": new_messages
                }
            }
        except Exception as err:
            LOGGER.exception("iKuai Coordinator 数据清洗关键错误")
            raise UpdateFailed(f"API 错误: {err}") from err
      
    # 主设备        
    @property
    def device_info(self) -> DeviceInfo:
        device_name = self.config_entry.title
        return DeviceInfo(
            identifiers={(DOMAIN, self.host)},
            name=f"{device_name} 负载监控",
            manufacturer="iKuai",
            model="iKuai Router",
            sw_version=self._sw_version,
            hw_version=self._hw_version,
            configuration_url=self.host,
        )
    
    # 接口管理子设备    
    @property
    def iface_mgmt_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}_iface_mgmt")},
            name=f"{self.config_entry.title} 接口监控",
            manufacturer="iKuai",
            model="Interface Monitor",
            via_device=(DOMAIN, self.host),
        )
     
    # 定义安全管理子设备
    @property
    def security_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}_security")},
            name=f"{self.config_entry.title} 安全中心",
            manufacturer="iKuai",
            model="Security & Firewall",
            via_device=(DOMAIN, self.host),
        )

    # 升级与备份管理子设备    
    @property
    def maintenance_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}_maintenance")},
            name=f"{self.config_entry.title} 系统维护",
            manufacturer="iKuai",
            model="System Maintenance",
            via_device=(DOMAIN, self.host),
        )
