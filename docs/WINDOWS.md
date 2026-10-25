# Windows 客户端指南

[返回首页](../README.md)

支持 Windows 10/11 x64 与 BLE 适配器。推荐使用 Releases 中的 EXE；源码开发推荐 Python 3.11（包含 Tk）。BLE 依赖固定为 Bleak 1.1.1，打包依赖 PyInstaller 6.22.3。

## 首次配对与同步

1. 烧录固件并保持设备开机；初始应显示等待连接。
2. 从 [Magpie 官方发布页](https://github.com/yetone/magpie-releases/releases) 获取 Windows 版（x64 文件为 `magpie-windows-amd64.exe`），按其说明完成配置并启动本地网关，默认 `http://127.0.0.1:3425`。显示客户端不负责安装或登录 Agent，也不会读取其凭据文件。
3. Windows 设置 → 蓝牙和设备 → 添加设备 → 蓝牙，选择 **Magpie Display**，输入小屏显示的六位码。文档预览中的 `123 456` 是示例，每次实际配对使用屏幕上的随机码。
4. 再打开客户端，确认 API 地址与设备名，点击 **开始同步**。

Bleak 1.x 的 Windows 自动配对不能完成本固件要求的六位码流程，因此必须先经系统设置配对。未配对时客户端会暂停连接，避免抢占配对。客户端内的“配对 / 蓝牙设置”会先停止同步并释放 BLE，再打开设置；配对后手动开始同步。

![离线示例客户端](images/windows-client.png)

这张图展示真实 Tk 客户端组件，数据来自离线预览脚本；不代表一次实机同步。

## 日常操作

- **立即刷新**：同步时重新读 API 并推送；停止时只读取统计供窗口预览。
- **最小化**：继续同步；**关闭窗口**：停止同步并释放蓝牙。
- **登录 Windows 后自动同步**：默认关闭，由用户勾选；下一次登录后最小化启动。Magpie Agent 也需要运行。
- **日志**：打开实际日志目录，默认 `%LOCALAPPDATA%\MagpieUsageDisplay\`。Store Python 可能使用重定向目录，以日志按钮打开的位置为准。

GUI 日志为 `desktop.log`，CLI 为 `companion.log`，自动轮转。配置 `settings.json` 在同一目录。自动启动使用当前用户 Run 项，不要求管理员权限。移动 EXE 后需要重新设置登录启动；不要同时启用旧 CLI 启动脚本。

程序使用命名互斥量避免两个 GUI 或 GUI 与 CLI 同时争用设备。需要多台显示器时，当前单实例设计需要另外适配。

## 从源码运行

在仓库根目录执行：

```powershell
# 首次创建隔离环境并安装依赖，只取 API 数据
powershell -NoProfile -ExecutionPolicy Bypass -File .\companion\run.ps1 -Once
# 持续同步（先在系统中完成配对）
powershell -NoProfile -ExecutionPolicy Bypass -File .\companion\run.ps1
# 自定义 Magpie 地址
powershell -NoProfile -ExecutionPolicy Bypass -File .\companion\run.ps1 -MagpieUrl http://127.0.0.1:3425
# GUI
.\companion\.venv\Scripts\python.exe -m companion.codex_display.desktop
```

`-ExecutionPolicy Bypass` 仅作用于本次进程。CLI 用 Ctrl+C 退出。持续同步前应停止 GUI 同步。

## 构建 EXE 与快捷方式

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\companion\build_desktop.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\companion\install_desktop.ps1
```

产物 `dist/MagpieDisplay.exe` 为包含 Python/Tk 的单文件程序，未签名。构建前退出已有 EXE，避免文件锁；快捷方式指向构建目录，之后不要随意移动。源码与测试始终公开，可自行构建。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| API 不可用 | 确认 Magpie Agent 已运行、端口正确、根接口返回 `name=magpie`，且有文档中的三个统计端点 |
| 找不到设备 | 确认固件启动、蓝牙开启、距离合适；默认名可同时通过服务 UUID 识别，自定义名称需精确匹配 |
| 已配对但一直 `LINKING` | 先看 API 状态；无有效首包不会显示在线。停止同步后重新开始，查看日志中的 GATT / 认证错误 |
| `pairing failed`、认证失败或持续 `Unreachable` | 停止同步；Windows 删除设备，必要时左键长按 3 秒清除硬件绑定，再按系统配对流程输入新码 |
| 设备普通断电后离线 | 已成功同步过的会话会自动扫描和恢复；连续三次临时失败后清理旧服务并等待 15 秒。最终 1.3.1 的完整断电循环仍需更多实机验证 |
| 首次初始化三次失败后停止 | 这是配对保护；完成配对或修复认证状态后手动开始，避免持续连接打断验证码流程 |
| 长按中键没有切到 Magpie | 先打开 Magpie Agent；Windows 前台窗口规则可能阻止切换，失败会显示 `OPEN MAGPIE ON PC` |
| 百分比 `--` / 重置时间缺失 | API 没有符合条件的 Codex 窗口或有效时间；查看数据说明，不会以其他服务额度补位 |

提交 Issue 时提供 Windows 版本、蓝牙适配器、固件/客户端版本和已脱敏的错误片段。请移除用户名、设备地址、请求内容及个人用量。
