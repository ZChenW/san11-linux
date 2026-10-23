# san11-linux

在 Linux 上运行 **三國志11 威力加強版 + 血色衣冠 6.0sp12 + SIRE 2.10c** 的启动器。原生分辨率、像素 1:1，开场动画、中文、SIRE 规则和存档均可正常使用。

测试环境：Arch Linux，niri（Wayland），GE-Proton 11-7。

## 方案

| 部分 | 做法 |
| --- | --- |
| 运行器 | GE-Proton 11-7 的副本，自带 FFmpeg 换成私有编译的 FFmpeg 8.0.3（播放开场动画需要） |
| 画面 | 原生 Wayland + DXVK，显示模式直接写入注册表 |
| 焦点 | `DirectMovie=1`、`AlwaysActive=1`，避免全屏游戏被最小化 |
| 中文 | `zh_CN.UTF-8`（代码页 936），中文 Windows 字体映射到 Noto CJK |
| SIRE 加载 | s11fast：加载 mod 从约 8 秒缩短到约 1.3 秒，标题画面不再反复回弹 |

原因和测量数据见 [技术报告](docs/report.md)。

## 依赖

- 血色衣冠整包（`.zip`、`.7z`、`.rar` 或解压后的文件夹），需自行从作者处获取
- Steam（需安装，无需运行），以及解压到 `~/.steam/steam/compatibilitytools.d/` 的 [GE-Proton 11-7](https://github.com/GloriousEggroll/proton-ge-custom/releases)
- Wayland 桌面，Python 3.12+，`uv`
- gcc、make、binutils、curl、gnupg、xz、`lib32-glibc`、`lib32-gcc-libs`（编译 FFmpeg）
- Vulkan 驱动及其 32 位版本，`noto-fonts-cjk`，`lib32-pipewire`

## 使用

```sh
tools/build-ffmpeg8.sh        # → ~/.local/share/san11/ffmpeg8
tools/build-s11fast.sh        # → ~/.local/share/san11/s11fast
./launcher/san11 setup xs6 --from ~/Downloads/血色衣冠6.0sp12v261009.zip
./launcher/san11 doctor xs6
./launcher/san11 run xs6 --windowed     # 不加 --windowed 为全屏
```

- 新配置首次运行会先直接启动一次游戏以生成显卡 GUID，到标题画面后退出，随后自动打开 SIRE。
- 在 SIRE 左上角点「311」启动游戏，游戏期间保持 SIRE 打开。
- `desktop xs6` 把游戏加入应用菜单（图标取自 SIRE；`--windowed` 另加一个窗口模式条目），之后可以不用命令行启动。
- `backup xs6` 备份存档，`stop xs6` 强制结束。

导入的整包以只读方式放在 `~/Games/san11/pristine/`，每个配置都是从这里复制出的独立副本。

## 新版 mod

```sh
./launcher/san11 setup xs7 --from ~/Downloads/血色衣冠6.0sp13.zip --saves-from xs6
```

启动器按文件名查找 `san11pk.exe` 和 `San11SIRE.exe`，不依赖目录名，所以不用改代码。`--saves-from` 复制旧配置的存档；新版自带的同名文件保留新版的。作者注明旧存档不兼容时不要加这个参数。

## 已知限制

- 中文输入法未测试；niri 不提供 text-input v3。
- 只在一种环境下测试过；不在 niri 下时，分辨率检测退回 xrandr。
- 没有文件系统隔离：Proton 把整个文件系统映射为 `Z:`。

## 文档

- [技术报告](docs/report.md)：mod 结构，各问题的原因、测量与解决方法
- [启动器说明](docs/launcher.md)：参数、目录布局、实现细节

## 声明

本仓库不包含任何游戏或 mod 文件。血色衣冠介绍视频：<https://www.bilibili.com/video/BV1iH4y1U7kh/>。代码以 [MIT](LICENSE) 许可证发布。
