# 硬件与接线

[返回首页](../README.md)

目标：ESP32 Dev Module、4 MB Flash、ST7789 SPI 240×320 屏幕，横屏 320×240。无需 PSRAM。构建目标为 `esp32dev`，Arduino-ESP32 2.0.17。

![ESP32 与 ST7789 接线示意](images/wiring.svg)

*这是信号接线示意，不是 PCB 原理图或模块实物照片。按键位置按从正面观察的左、中、右定义。*

| 模块信号 | ESP32 GPIO | 说明 |
| --- | --- | --- |
| MOSI / SDA / DIN | 23 | SPI 数据输出，SDA 在这里不是 I²C |
| SCLK / SCL / CLK | 18 | SPI 时钟 |
| MISO / SDO | 19 | 屏幕没有 SDO 时可不接 |
| DC / A0 | 2 | 数据 / 命令 |
| RST / RES | 4 | 屏幕复位 |
| CS | 5 | 片选；须选有相应信号的模块或调整配置 |
| 背光控制 | 17 | 当前硬件的 PWM 背光控制输入，默认 50/255 |
| 左 / 中 / 右按键 | 25 / 26 / 27 | 另一端接 GND，低电平有效，使用内部上拉 |
| GND | GND | 开发板、屏幕和按键共地 |

ESP32 GPIO 为 3.3 V 逻辑。屏幕 VCC 按模块规格供电；不要将 5 V 信号接入 GPIO。GPIO17 应连接模块的背光控制或驱动电路输入；如果裸屏 LED 需要较大电流，应经适当的晶体管 / MOSFET 驱动，不能直接由 GPIO 供电。USB 负责 ESP32 供电和烧录。

原时钟硬件的蜂鸣器 GPIO13 和传感器电源 GPIO12，在此固件中保持低电平；新接线无需安装这些器件。GPIO2、5、12 属于启动相关引脚，外部模块电平不能妨碍正常启动。

## 配置位置

- [lib/TFT_eSPI/User_Setup.h](../lib/TFT_eSPI/User_Setup.h)：ST7789、尺寸、BGR、反色、SPI 引脚和 80 MHz SPI 设置。
- [src/magpie/board_config.h](../src/magpie/board_config.h)：背光、按键、传感器电源与蜂鸣器。
- [src/magpie/main.cpp](../src/magpie/main.cpp)：`setRotation(1)`，横屏缓冲 320×240。

屏幕花屏或长线不稳定时，可先把 `SPI_FREQUENCY` 从 80000000 降到 40000000，再编译。颜色错误时检查 `TFT_RGB_ORDER` 和 `TFT_INVERSION_ON`。不同屏幕批次可能需要调整这两项。

## 烧录问题

选择 USB 转串口的真实 COM 端口。下载失败时可尝试按住 BOOT 发起 Upload，进入下载后松开；具体复位操作取决于开发板。串口日志为 115200 baud。需要时安装与你的 USB 转串口芯片匹配的驱动。

`huge_app.csv` 提供约 3 MB 应用分区，不支持 OTA。使用 PlatformIO Upload 自动处理写入地址。升级只写应用通常保留绑定；整片擦除 Flash 会清除设备端绑定，此时应同时在 Windows 删除旧设备并重新配对。
