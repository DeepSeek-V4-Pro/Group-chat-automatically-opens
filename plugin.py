"""群聊定时打卡插件 — 新 SDK 版本

自动在指定时间对配置的群聊执行打卡操作。
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp
import tomlkit

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase

logger = logging.getLogger("group_sign")


# ===== 配置模型 =====


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="2.0.0", description="配置版本")
    startup_delay: int = Field(default=10, description="插件加载后启动定时任务的延迟时间(秒)")


class SignConfig(PluginConfigBase):
    __ui_label__ = "打卡"
    __ui_icon__ = "calendar-check"
    __ui_order__ = 1

    groups: list[str] = Field(default_factory=list, description="需要进行打卡的群聊列表")
    check_interval: int = Field(default=3600, description="打卡检查间隔(秒)")
    reminder_time: str = Field(default="09:00", description="每日打卡提醒时间")


class ApiConfig(PluginConfigBase):
    __ui_label__ = "API"
    __ui_icon__ = "server"
    __ui_order__ = 2

    host: str = Field(default="127.0.0.1", description="打卡API的主机地址")
    port: str = Field(default="4999", description="打卡API的端口号")
    token: str = Field(default="", description="API鉴权token，可选")
    timeout: int = Field(default=10, description="API请求超时时间(秒)")


class PermissionsConfig(PluginConfigBase):
    __ui_label__ = "权限"
    __ui_icon__ = "shield"
    __ui_order__ = 3

    admin_users: list[str] = Field(default_factory=list, description="允许管理打卡配置的管理员QQ号")


class GroupSignPluginConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    sign: SignConfig = Field(default_factory=SignConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)


# ===== 打卡定时任务管理器 =====


class SignTaskManager:
    """打卡定时任务管理器，负责处理定时打卡逻辑"""

    def __init__(self, plugin: "GroupSignPlugin"):
        self.plugin = plugin
        self.is_running = False
        self.task = None
        self.last_check_date = None
        self.last_checked = False

    async def start(self):
        if self.is_running:
            logger.info("[SignTaskManager] 打卡任务已在运行中")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._task_loop())
        logger.info("[SignTaskManager] 打卡任务已启动")

    async def stop(self):
        if not self.is_running:
            logger.info("[SignTaskManager] 打卡任务未在运行")
            return

        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None
        logger.info("[SignTaskManager] 打卡任务已停止")

    async def _task_loop(self):
        while self.is_running:
            try:
                check_interval = self.plugin.config.sign.check_interval
                reminder_time = self.plugin.config.sign.reminder_time

                await self._check_and_execute_sign()

                sleep_time = self._calculate_sleep_time(check_interval, reminder_time)
                logger.debug(f"[SignTaskManager] 下次检查将在 {sleep_time} 秒后进行")
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SignTaskManager] 任务循环出错: {str(e)}", exc_info=True)
                await asyncio.sleep(60)

    async def _check_and_execute_sign(self):
        sign_groups = self.plugin.config.sign.groups
        reminder_time = self.plugin.config.sign.reminder_time

        if not sign_groups:
            logger.debug("[SignTaskManager] 打卡群列表为空，不执行打卡")
            return

        now_str = datetime.now().strftime("%H:%M")
        today = datetime.now().date()

        if self.last_check_date != today:
            self.last_check_date = today
            self.last_checked = False

        if not self.last_checked and now_str >= reminder_time:
            logger.info(f"[SignTaskManager] 到达打卡提醒时间 {reminder_time}（当前 {now_str}），开始执行打卡")
            self.last_checked = True

            for group_id in sign_groups:
                try:
                    success, response = await self.plugin.send_group_sign_request(group_id)
                    if success:
                        logger.info(f"[SignTaskManager] 群{group_id}定时打卡成功")
                    else:
                        logger.error(f"[SignTaskManager] 群{group_id}定时打卡失败: {response}")
                except Exception as e:
                    logger.error(f"[SignTaskManager] 群{group_id}打卡过程出错: {str(e)}")

                await asyncio.sleep(2)

    def _calculate_sleep_time(self, check_interval: int, reminder_time: str) -> int:
        now = datetime.now()
        target_time = datetime.strptime(reminder_time, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )

        if now > target_time:
            target_time += timedelta(days=1)

        time_diff = (target_time - now).total_seconds()
        return int(min(time_diff, check_interval))


# ===== 插件主类 =====


class GroupSignPlugin(MaiBotPlugin):
    """群聊打卡插件 — 支持定时打卡和手动控制"""

    config_model = GroupSignPluginConfig

    async def on_load(self) -> None:
        try:
            self.sign_task_manager = None
            startup_delay = self.config.plugin.startup_delay

            if self.config.plugin.enabled:
                asyncio.create_task(self._start_task_after_delay())
            else:
                logger.info("[GroupSign] 插件已禁用，不启动打卡任务")

            logger.info("[GroupSign] 插件加载完成")
        except Exception as e:
            logger.error("[GroupSign] 插件初始化失败", exc_info=True)
            raise

    async def on_unload(self) -> None:
        try:
            if self.sign_task_manager:
                await self.sign_task_manager.stop()
            logger.info("[GroupSign] 插件已卸载")
        except Exception as e:
            logger.error("[GroupSign] 卸载插件时发生错误", exc_info=True)

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        del scope, config_data, version

    # ===== Command 组件 =====

    HELP_TEXT = (
        "群聊定时打卡 使用说明：\n"
        "/groupsign add_group <群号>    — 添加群聊到打卡列表\n"
        "/groupsign remove_group <群号> — 从打卡列表移除群聊\n"
        "/groupsign list_groups         — 查看打卡群聊列表\n"
        "/groupsign execute <群号>      — 立即执行群打卡\n"
        "/groupsign start_task          — 启动打卡定时任务\n"
        "/groupsign stop_task           — 停止打卡定时任务\n"
        "/groupsign status              — 查看定时任务状态"
    )

    @Command(
        "groupsign",
        description="群聊打卡管理命令",
        pattern=r"^/groupsign(?:\s+(?P<operation_type>\w+)(?:\s+(?P<value>.+))?)?$",
    )
    async def handle_groupsign(
        self,
        stream_id: str = "",
        user_id: str = "",
        group_id: str = "",
        matched_groups: dict | None = None,
        **kwargs: Any,
    ):
        del kwargs

        try:
            if not user_id:
                await self.ctx.send.text("系统错误：无法识别发送者信息", stream_id)
                return False, "无法识别发送者信息", False

            if not self._check_admin_permission(user_id):
                await self.ctx.send.text("权限不足，你无权使用此命令", stream_id)
                return False, "", False

            if matched_groups is None:
                matched_groups = {}

            operation_type = matched_groups.get("operation_type", "")
            value = matched_groups.get("value", "")

            if not operation_type:
                await self.ctx.send.text(self.HELP_TEXT, stream_id)
                return True, "", False

            is_group = bool(group_id)
            if not is_group and operation_type in ("add_group", "remove_group", "execute"):
                await self.ctx.send.text("抱歉，添加/移除打卡群聊及执行打卡需在群聊中操作", stream_id)
                return False, "", False

            operation_map = {
                "add_group": lambda: self._handle_group_add(stream_id, value),
                "remove_group": lambda: self._handle_group_remove(stream_id, value),
                "list_groups": lambda: self._handle_group_list(stream_id),
                "execute": lambda: self._handle_execute_sign(stream_id, value),
                "start_task": lambda: self._handle_start_task(stream_id),
                "stop_task": lambda: self._handle_stop_task(stream_id),
                "status": lambda: self._handle_task_status(stream_id),
            }

            if operation_type in operation_map:
                await operation_map[operation_type]()
                return True, "", False
            else:
                await self.ctx.send.text(
                    "无效的操作参数\n" + self.HELP_TEXT,
                    stream_id,
                )
                return False, "", False

        except Exception as e:
            logger.error(f"[Command:groupsign] 执行错误: {e}", exc_info=True)
            await self.ctx.send.text(f"执行失败: {str(e)}", stream_id)
            return False, f"执行失败: {str(e)}", False

    # ===== 操作处理方法 =====

    async def _handle_group_add(self, stream_id: str, value: str):
        if not value:
            await self.ctx.send.text("请指定要添加的群号，格式: /groupsign add_group <群号>", stream_id)
            return
        if not re.match(r"^[1-9]\d{4,10}$", value):
            await self.ctx.send.text(f"{value}不是有效的群号格式", stream_id)
            return
        await self._update_group_config(stream_id, "add", value)

    async def _handle_group_remove(self, stream_id: str, value: str):
        if not value:
            await self.ctx.send.text("请指定要移除的群号，格式: /groupsign remove_group <群号>", stream_id)
            return
        if not re.match(r"^[1-9]\d{4,10}$", value):
            await self.ctx.send.text(f"{value}不是有效的群号格式", stream_id)
            return
        await self._update_group_config(stream_id, "remove", value)

    async def _handle_group_list(self, stream_id: str):
        groups = self.config.sign.groups
        if not groups:
            await self.ctx.send.text("打卡列表为空", stream_id)
        else:
            result = "打卡群聊列表：\n" + "\n".join(groups)
            await self.ctx.send.text(result, stream_id)

    async def _handle_execute_sign(self, stream_id: str, value: str):
        if not value:
            await self.ctx.send.text("请指定要执行打卡的群号，格式: /groupsign execute <群号>", stream_id)
            return
        if not re.match(r"^[1-9]\d{4,10}$", value):
            await self.ctx.send.text(f"{value}不是有效的群号格式", stream_id)
            return
        if value not in self.config.sign.groups:
            await self.ctx.send.text(f"群聊{value}不在打卡列表中，无法执行打卡", stream_id)
            return

        success, response = await self.send_group_sign_request(value)
        if success:
            await self.ctx.send.text(f"已在群{value}执行打卡操作", stream_id)
            logger.info(f"[Command:groupsign] 已在群{value}执行打卡操作")
        else:
            error_msg = f"打卡操作失败: {response}" if response else "打卡操作失败，未知错误"
            await self.ctx.send.text(error_msg, stream_id)
            logger.error(f"[Command:groupsign] 群{value}打卡失败: {response}")

    async def _handle_start_task(self, stream_id: str):
        if self.sign_task_manager:
            await self.sign_task_manager.start()
            await self.ctx.send.text("已尝试启动打卡定时任务", stream_id)
        else:
            await self.ctx.send.text("打卡任务管理器未初始化", stream_id)

    async def _handle_stop_task(self, stream_id: str):
        if self.sign_task_manager:
            await self.sign_task_manager.stop()
            await self.ctx.send.text("已尝试停止打卡定时任务", stream_id)
        else:
            await self.ctx.send.text("打卡任务管理器未初始化", stream_id)

    async def _handle_task_status(self, stream_id: str):
        if self.sign_task_manager:
            status = "运行中" if self.sign_task_manager.is_running else "已停止"
            await self.ctx.send.text(f"打卡定时任务状态: {status}", stream_id)
        else:
            await self.ctx.send.text("打卡定时任务未初始化", stream_id)

    # ===== 配置辅助方法 =====

    def _check_admin_permission(self, user_id: str) -> bool:
        admin_users = self.config.permissions.admin_users
        return user_id in admin_users

    async def _update_group_config(self, stream_id: str, action: str, group_id: str):
        # 直接读写 config.toml 而非走 SDK 配置持久化路径，原因：
        # 1. SDK 的 on_config_update 是 push 模式（UI/外部修改时回调），
        #    不支持从 Command 中写入单字段后触发完整持久化
        # 2. 此处只需修改 groups 列表一个字段，全量写回 toml 文件比重建
        #    整个 PluginConfigBase 再序列化更简单可靠
        # 3. 同步更新 self.config 保持运行时状态一致
        try:
            config_path = os.path.join(Path(__file__).parent, "config.toml")

            with open(config_path, "r", encoding="utf-8") as f:
                config_data = tomlkit.load(f)

            if "sign" not in config_data:
                config_data["sign"] = tomlkit.table()
            if "groups" not in config_data["sign"]:
                config_data["sign"]["groups"] = tomlkit.array()

            groups_list = config_data["sign"]["groups"]

            if action == "add":
                if group_id not in groups_list:
                    groups_list.append(group_id)
                    self.config.sign.groups.append(group_id)
                    await self.ctx.send.text(f"已将群聊{group_id}添加到打卡列表", stream_id)
                    logger.info(f"[Command:groupsign] 已添加打卡群聊: {group_id}")
                else:
                    await self.ctx.send.text(f"群聊{group_id}已在打卡列表中", stream_id)
                    return

            elif action == "remove":
                if group_id in groups_list:
                    groups_list.remove(group_id)
                    self.config.sign.groups.remove(group_id)
                    await self.ctx.send.text(f"已将群聊{group_id}从打卡列表中移除", stream_id)
                    logger.info(f"[Command:groupsign] 已移除打卡群聊: {group_id}")
                else:
                    await self.ctx.send.text(f"群聊{group_id}不在打卡列表中", stream_id)
                    return

            with open(config_path, "w", encoding="utf-8") as f:
                tomlkit.dump(config_data, f)

        except Exception as e:
            logger.error(f"[Command:groupsign] 更新配置失败: {e}", exc_info=True)
            await self.ctx.send.text(f"操作失败: {str(e)}", stream_id)

    # ===== API 调用 =====

    async def send_group_sign_request(self, group_id: str) -> tuple[bool, str | None]:
        try:
            api_config = self.config.api
            api_host = api_config.host
            api_port = api_config.port
            api_token = api_config.token
            timeout = api_config.timeout

            base_url = f"http://{api_host}:{api_port}"
            params = {}
            if api_token:
                params["access_token"] = api_token

            payload = {"group_id": group_id}

            logger.info(f"[GroupSign] 发送打卡请求到 {base_url}/set_group_sign, 群号: {group_id}")

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(
                        f"{base_url}/set_group_sign",
                        json=payload,
                        params=params,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as response:
                        status_code = response.status
                        logger.debug(f"[GroupSign] 打卡API响应状态码: {status_code}")

                        response_text = await response.text()
                        logger.debug(f"[GroupSign] 打卡API响应内容: {response_text}")

                        if status_code != 200:
                            return False, f"HTTP请求失败，状态码: {status_code}"

                        try:
                            result = json.loads(response_text)
                            if result.get("status") == "ok" and result.get("retcode") == 0:
                                return True, "打卡成功"
                            else:
                                error_msg = result.get(
                                    "wording", result.get("message", f"未知错误（响应: {response_text}）")
                                )
                                return False, error_msg
                        except json.JSONDecodeError:
                            return False, f"响应格式错误，非JSON: {response_text}"

                except asyncio.TimeoutError:
                    return False, f"API请求超时（超过{timeout}秒）"
                except aiohttp.ClientError as e:
                    return False, f"HTTP客户端错误: {str(e)}"

        except Exception as e:
            error_msg = f"API请求异常: {str(e)}"
            logger.error(f"[GroupSign] {error_msg}", exc_info=True)
            return False, error_msg

    # ===== 任务启动 =====

    async def _start_task_after_delay(self):
        try:
            startup_delay = self.config.plugin.startup_delay
            logger.info(f"[GroupSign] 插件将在{startup_delay}秒后启动打卡任务...")
            await asyncio.sleep(startup_delay)

            self.sign_task_manager = SignTaskManager(self)
            await self.sign_task_manager.start()
            logger.info("[GroupSign] 打卡任务启动成功")

        except Exception as e:
            logger.error(f"[GroupSign] 延迟启动过程中发生错误", exc_info=True)
            logger.info("[GroupSign] 尝试立即启动打卡任务")
            self.sign_task_manager = SignTaskManager(self)
            await self.sign_task_manager.start()


def create_plugin() -> GroupSignPlugin:
    return GroupSignPlugin()
