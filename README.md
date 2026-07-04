# 群聊定时打卡

> 自动在指定时间对配置的群聊执行打卡操作的 MaiBot 插件。

---

## 原作者信息

- **作者**: [WaterInk0101](https://github.com/WaterInk0101)
- **原始仓库**: [https://github.com/WaterInk0101/groupsign](https://github.com/WaterInk0101/groupsign)
- **原始许可证**: MIT

感谢 WaterInk0101 的原始实现。

---

## 修改说明

- **维护者**: [DeepSeek-V4-Pro](https://github.com/DeepSeek-V4-Pro)
- **当前仓库**: [https://github.com/DeepSeek-V4-Pro/Group-chat-automatically-opens](https://github.com/DeepSeek-V4-Pro/Group-chat-automatically-opens)
- **更新适配 MaiBot 1.0.0 ~ 1.99.99**
- 升级 SDK 版本声明，兼容 MaiBot 1.0.0
- 修正 manifest 中 `host_application` 版本范围

---

## 功能说明

让麦麦在群聊中到点打卡。每天到达设定的提醒时间时，插件会自动向配置好的群聊列表中的每个群发送打卡请求。

### 工作原理

1. 插件加载后，经过 `startup_delay` 秒的等待，启动内部定时任务
2. 定时任务按 `check_interval` 秒的间隔周期性检查当前时间
3. 达到或超过每日 `reminder_time` 时，依次向打卡列表中的每个群发送 HTTP 打卡请求
4. 当天已打卡后不再重复触发，次日自动重置

### 前置条件

- 已部署并运行 NapCat（或其他兼容 OneBot 标准的实现）
- NapCat 中已启用 HTTP Server，且主机地址和端口与本插件 `[api]` 配置一致
- NapCat HTTP Server 需提供 `/set_group_sign` 端点（NapCat 内置的打卡接口）

---

## 安装方法

1. 将本插件文件夹放置到 MaiBot 的 `/plugins` 目录中
2. 确认 NapCat 已开启 HTTP Server 功能，`host` 和 `port` 与 `config.toml` 中 `[api]` 配置一致
3. 在 `config.toml` 中配置需要打卡的群聊列表和管理员列表（见下方配置说明）
4. 重启 MaiBot 或使用插件热加载功能

---

## 命令使用方法

所有命令需要由 `[permissions].admin_users` 中配置的管理员 QQ 号发送。

### 命令列表

| 命令 | 说明 | 使用场景 |
|------|------|----------|
| `/groupsign` | 查看使用帮助 | 快速查看可用命令 |
| `/groupsign add_group \<群号\>` | 将群聊添加至打卡列表 | 新增需要定时打卡的群 |
| `/groupsign remove_group \<群号\>` | 将群聊移出打卡列表 | 取消某个群的定时打卡 |
| `/groupsign list_groups` | 查看当前打卡群聊列表 | 确认已配置的打卡群 |
| `/groupsign execute \<群号\>` | 立即在指定群中执行打卡 | 手动触发打卡（不受定时限制） |
| `/groupsign start_task` | 启动打卡定时任务 | 手动启动后台定时器 |
| `/groupsign stop_task` | 停止打卡定时任务 | 手动停止后台定时器 |
| `/groupsign status` | 查看定时任务运行状态 | 确认定时器是否在运行 |

### 使用示例

```
/groupsign add_group 12345678
/groupsign remove_group 12345678
/groupsign list_groups
/groupsign execute 12345678
/groupsign start_task
/groupsign status
```

### 注意事项

- `add_group`、`remove_group`、`execute` 命令**需要在群聊中发送**，私聊无法使用
- 通过命令增删打卡群列表后，配置会自动写入 `config.toml` 持久化
- `execute` 命令只对已在打卡列表中的群生效

---

> ⚠️ **安全提醒**：`[api].host` 和 `[api].port` 指向打卡请求的接收端。请确保该地址为**你可控的可信服务端**（如本地 NapCat），不要指向第三方或未知的 HTTP 端点，否则打卡请求中的群号信息可能被泄露。

## 配置选项

```toml
[plugin]
enabled = true             # 是否启用插件（false 则不启动定时任务）
config_version = "2.0.0"  # 配置文件版本号（请勿随意修改）
startup_delay = 10         # 插件加载后延迟启动定时任务的秒数

[sign]
groups = ["123456"]        # 需要定时打卡的群聊 QQ 群号列表
check_interval = 3600      # 打卡检查间隔，单位秒（默认 1 小时检查一次）
                           # 建议值：3600（每小时）或 1800（每半小时）
                           # 数值越小检查越频繁，但也会增加不必要的请求
reminder_time = "09:00"    # 每日打卡提醒时间，24 小时制 HH:MM 格式
                           # 到达或超过此时间后执行打卡，每天仅一次

[api]
host = "127.0.0.1"         # NapCat HTTP Server 的主机地址
port = "4999"              # NapCat HTTP Server 的端口号
token = ""                 # API 鉴权 token（如果 NapCat 设置了 access_token）
timeout = 10               # API 请求超时时间，单位秒

[permissions]
admin_users = []           # 允许使用 /groupsign 命令的管理员 QQ 号列表
                           # 留空则所有命令均权限不足
```

### 配置详解

- **groups**：可通过命令 `/groupsign add_group` 动态添加，也可直接编辑 `config.toml` 后重启插件
- **check_interval**：定时任务检查当前时间的频率。每个检查周期内，若当前时间 >= `reminder_time` 且当日尚未打卡，则执行打卡。默认 3600 秒（1 小时）足够满足每日打卡需求
- **reminder_time**：使用 `>=` 比较（而非精确相等），因此即便系统稍有延迟也不会漏触发
- **admin_users**：强烈建议至少配置一个管理员 QQ 号，否则无法使用任何 `/groupsign` 命令

---

## 常见问题

**Q: 如何确认插件正常运行？**

A: 在群聊中发送 `/groupsign status`，返回"运行中"则表示定时任务正常。也可查看 MaiBot 日志，搜索 `group_sign` 关键词。

**Q: 打卡失败了怎么办？**

A: 按以下步骤排查：
1. 确认 NapCat HTTP Server 已正常运行
2. 检查 `config.toml` 中 `[api]` 的 `host` 和 `port` 是否与 NapCat 配置一致
3. 如果 NapCat 设置了 `access_token`，需在 `[api].token` 中填写相同值
4. 手动使用 `/groupsign execute <群号>` 测试打卡功能

**Q: 私聊里无法添加群？**

A: `add_group`、`remove_group`、`execute` 命令设计上需要在群聊中发送。这是为了防止有人在私聊中随意操作群打卡配置。

## 日志查看

插件日志使用 `group_sign` 作为 logger 名称，可在 MaiBot 的日志文件中搜索以下关键词定位问题：

- `[GroupSign]` — 插件生命周期（加载、卸载、启动等）
- `[SignTaskManager]` — 定时任务循环（检查、执行、状态）
- `[Command:groupsign]` — 命令执行结果

> [!NOTE]
> 配置项请按需修改，不要随意改动 `config_version`。
