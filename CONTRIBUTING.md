# 参与开发

欢迎提交 Issue 或 Pull Request。请先确认问题属于当前 **ESP32/ST7789 + Windows/Magpie** 分支；原 AMOLED/macOS 功能请参考上游。

## 开发检查

在仓库根目录运行：

```powershell
python -m venv companion/.venv
.\companion\.venv\Scripts\python.exe -m pip install -r companion/requirements.txt
.\companion\.venv\Scripts\python.exe -m unittest discover -s companion/tests -v
python -m platformio run -e magpie-esp32
python -m pip install -r tools/requirements.txt
python tools/preview_magpie_dashboard.py
python tools/check_docs.py
```

UI / 字体变化请更新示例图片并注明是主机预览还是实机截图。`tools/preview_desktop.py` 可在 Windows 上使用真实组件打开示例窗口，不访问 API、蓝牙、用户配置或登录启动设置。

字体已生成并提交。需要修改字形时：

```powershell
python tools/generate_dashboard_fonts.py --font path/to/DejaVuSans-Bold.ttf
python tools/preview_magpie_dashboard.py
```

不指定字体路径时生成器从 Matplotlib 安装目录找字体，此时另需安装 Matplotlib。字体许可必须保留。

## 提交内容

描述可复现触发条件、修复后的行为、执行过的检查和未验证的硬件情况。协议变化需同步更新 `docs/BLE_PROTOCOL.md` 并验证 250 字节上限与旧版本处理方式；配对 / 重连变化需覆盖首次连接和已有绑定的恢复流程。

不要提交 `.venv`、`.pio`、EXE、个人配置、真实账户统计、BLE 地址、凭据或未获授权的个人照片。使用合成测试数据。修改第三方库时保留原版权声明并说明原因。

当前 CI 覆盖 Windows 测试/打包、Linux 固件构建和文档检查。实机测试请写明开发板、屏幕批次、蓝牙适配器和操作系统；模拟测试不能替代实机验证。

发布 Windows 包时，用打包 EXE 的同一个解释器运行 `companion/.venv/Scripts/python.exe tools/package_windows.py`，得到包含许可证、依赖版本和 SHA-256 的 ZIP。二进制通过 GitHub Releases 分发，Git 仓库仅提交源码与文档素材。
