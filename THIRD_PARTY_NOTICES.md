# 来源与第三方声明 / Provenance and third-party notices

## 项目来源

本仓库是 [jayyao97/codex-usage-display](https://github.com/jayyao97/codex-usage-display) 的 GitHub fork，保留其历史，发布起点为 `8bd4ec7adc39ab985bf743da6464152ca70698bb`。原作者为 Jay Yao，原项目使用 MIT 许可，完整声明保存在 [LICENSE.magpie-usage-display](LICENSE.magpie-usage-display)。根目录 [LICENSE](LICENSE) 同时保留 Jay Yao 版权并声明本移植的新增贡献。

当前数据适配与 BLE v4 逻辑来自 [peterroe/magpie-usage-display](https://github.com/peterroe/magpie-usage-display)，本地移植记录中的基线为 [`5940d479afeb89affc04d13c01f3f644b3f28cc7`](https://github.com/peterroe/magpie-usage-display/tree/5940d479afeb89affc04d13c01f3f644b3f28cc7)。该版本的 MIT 文件同样声明 Jay Yao 版权；这里另明确致谢 peterroe 对 Magpie 数据聚合和界面的贡献。

本 fork 新增或适配了普通 ESP32 / ST7789 的 TFT 界面、双窗口额度、灰度字形渲染、实体按键，以及 Windows GUI、系统配对保护、WinRT 端点恢复、重连清理、测试、打包与文档。未在当前分支使用上游 AMOLED 驱动、LVGL、Montserrat 字体或原实机照片，避免让不同硬件的图片与说明产生混淆。

本地工程原先还包含天气时钟与个人贺卡实验。这次公开包只收录 `src/magpie/`、`companion/`、相关工具与必要依赖；原开发目录仍保留这些内容。板级引脚与 TFT 配置沿用本地时钟硬件。

## 随源码分发的库

| 内容 | 版本 / 来源 | 许可与原始声明 |
| --- | --- | --- |
| ArduinoJson | 本地随附 7.0.3 / Benoit Blanchon | [MIT](lib/ArduinoJson/LICENSE.txt) |
| OneButton | 本地副本；`library.json` 为 2.0.3，`library.properties` 为 2.1.0，保留原样 | [BSD 3-Clause](lib/OneButton/LICENSE) |
| TFT_eSPI | 本地随附 2.5.0 / Bodmer；项目定制 `User_Setup.h` | [FreeBSD / MIT / BSD 原始说明](lib/TFT_eSPI/license.txt)；[附带字体声明](lib/TFT_eSPI/Fonts/GFXFF/license.txt) |
| Dashboard 字形 | DejaVu Sans Bold 的生成位图，含主机 JSON 夹具 | [Bitstream Vera / Arev 声明](LICENSE.dashboard-font)，DejaVu 修改为公有领域 |

库目录中的其他版权和许可文件继续有效；为缩小发行内容，省略了未用于构建的第三方示例、工具和测试目录。根目录 MIT 不覆盖这些独立许可条款。正常固件编译无需重新生成字形或安装字体工具。

## 构建或运行时下载的依赖

| 依赖 | 固定版本或范围 | 许可 |
| --- | --- | --- |
| PlatformIO Core | 验证 / CI 使用 6.2.0 | Apache-2.0 |
| platform-espressif32 | 6.10.0 | Apache-2.0 |
| Arduino-ESP32 | 2.0.17，由平台安装 | LGPL-2.1；其他组件按各自声明 |
| Bleak | 1.1.1 | MIT |
| Python / Tk | 打包机 Python 环境随 EXE 分发 | PSF / Tcl-Tk 等各自许可 |
| PyInstaller | 6.22.3 | GPL-2.0-or-later，含分发生成程序的例外 |
| Pillow | 文档预览工具 | HPND |

版本以 `platformio.ini`、`companion/requirements.txt`、`companion/build_desktop.ps1` 和 `tools/requirements.txt` 为准。打包时应随发布包保留本文件和相关许可证；这些依赖不因打包而改用项目 MIT 许可。`tools/package_windows.py` 收集构建环境中的依赖许可、Python 与 Tk 许可并生成依赖版本清单；Tcl 8.6 原始声明来自 [tcltk/tcl](https://github.com/tcltk/tcl/blob/core-8-6-branch/license.terms)，保存在 [LICENSES/Tcl-license.terms](LICENSES/Tcl-license.terms)。
