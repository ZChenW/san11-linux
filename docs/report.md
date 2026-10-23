# 技术报告

对象：三國志11 威力加強版（San11PK）+ 血色衣冠 6.0sp12 + SIRE 2.10c。
测试环境：Arch Linux，niri（Wayland），2560×1600 屏幕，GE-Proton 11-7，2026-10。

## 1. mod 的结构

血色衣冠以完整整包发布，每个版本都包含：

- `San11Pk/`：修改后的完整游戏，包括剧本（`Media/scenario`）、列传与对白（`Media/msg`）、头像（`Media/face`）、资源包（`Media/san11pkres.bin`）。`san11pk.exe` 是内存转储版（已脱壳），不需要 SafeDisc 驱动（`SECDRV.SYS`、`DrvMgt.dll` 是遗留文件）。
- `SIRE v2.10/`：SIRE 2.10c（Delphi 编写的原生 Win32 程序）和规则包 `血色衣冠6.0(SIRE2.10)sp12.seal`。SIRE 是外部进程补丁程序：「311」按钮启动游戏后，SIRE 通过 `WriteProcessMemory` 把规则写入游戏内存，不修改文件。游戏期间 SIRE 必须保持运行。

在 Valve Proton 10 下比对运行中的游戏内存与 exe 文件：代码段有 1,777 处、共 14,244 字节不同，即 SIRE 写入的补丁。

存档位于游戏目录 `San11Pk/Koei/San11 Tc/SaveData/`，随游戏文件复制即可迁移。

## 2. 中文

游戏和 SIRE 依赖中文代码页。启动环境设 `LANG=LC_ALL=zh_CN.UTF-8`，Wine 即使用代码页 936。宋体、新宋体、微软雅黑、黑体、细明体等字体通过 `FontSubstitutes` 和 `Wine\Fonts\Replacements` 映射到 Noto CJK。游戏菜单为繁体中文，显示正常；只有 X11 窗口标题乱码，不影响使用。

## 3. 显示设置

显示设置位于 `HKCU\Software\KOEI\San11PK Tc\San11Option`：

| 值 | 格式 |
| --- | --- |
| `DisplayMode 0`（全屏）、`DisplayMode 1`（窗口） | 48 字节：16 字节显卡 GUID + 8 个小端 u32 `(0, 1, 后台缓冲格式, 显示格式, 深度格式, 是否窗口, 宽, 高)` |
| `WindowMode` | 0 全屏，1 窗口 |

游戏自带的设置工具（`S11PKLauncher.exe`）在 2560×1600 上选择了格式 35（A2R10G10B10），游戏随后退回 1024×768 10 位色并黑屏。写入 `(0, 1, 22, 22, 77, 0, 2560, 1600)`（X8R8G8B8 / D24X8）后，游戏按原生分辨率运行。GUID 由游戏首次运行时生成，因此新前缀需要先运行一次游戏。

各运行方式的结果：

| 运行方式 | 结果 |
| --- | --- |
| Valve Proton 10，X11，全屏切换分辨率 | `xvidmode.c` 断言失败；需要 `UseXVidMode=N` |
| Valve Proton 10，DXVK，全屏 | 黑屏，DXVK 不开始呈现 |
| Valve Proton 10，WineD3D，全屏 | 画面正常，但 Wine 窗口仍为 1024×768，点击坐标按此换算 |
| **GE-Proton 11-7，原生 Wayland + DXVK，全屏** | 2560×1600，像素 1:1，点击坐标正确 |

## 4. 开场动画

开场动画是 MPEG-1 程序流（`Media/movie/*.mpg`）。

| 尝试 | 结果 |
| --- | --- |
| Valve Proton 10，直接在主机运行 | winegstreamer 的 `wg_parser_create` 返回 `E_OUTOFMEMORY`，无动画 |
| Valve Proton 10，在 Steam Linux Runtime 中运行 | GStreamer 可用，但缺少 MPEG-1 System Stream 解封装器 |
| 无损转封装为 MPEG-TS | 可以解封装，但 Proton 的媒体转换器把未知视频替换为空白视频 |
| GE-Proton 11-7 原版 | winedmo 加载失败，`0xc000007a` |

GE 的 winedmo 依赖 FFmpeg 8 的五个库（`libavutil.so.60`、`libavformat.so.62`、`libavcodec.so.62`、`libswscale.so.9`、`libswresample.so.6`）。GE 自带这些库，但其 32 位 `libavcodec` 依赖 32 位 `libvdpau.so.1`，测试主机没有这个库。GE 会把自带库目录放在搜索路径最前面，所以 `LD_LIBRARY_PATH` 无法替换。

解决方法：编译不依赖外部库的 FFmpeg 8.0.3（只启用这些视频需要的解封装器和解码器，`tools/build-ffmpeg8.sh`），用 reflink 复制一份 GE，在副本中替换自带的五个库。Steam 中的 GE 和视频文件均不修改。游戏内的 movie003、movie000 都能完整播放。

GE-Proton 11-11 原版在同一主机上同样无法播放（`0xc000007a`、`0x80040218`），换用新版 GE 不能免去这一步。

## 5. 动画窗口与焦点

- `DirectMovie=0` 时，动画在单独的 ActiveMovie 窗口中播放并取得焦点；全屏游戏失去焦点后被 DXVK 最小化，之后无法恢复（niri 没有任务栏）。`DirectMovie=1` 让动画画在游戏自己的 D3D 画面上。
- 从 SIRE 启动时，焦点会回到 SIRE；不设 `AlwaysActive=1`，游戏会在失去焦点时自行最小化。

启动器每次启动前都会写入这两个值。

## 6. 标题画面回弹

**现象**：出现标题后点击，镜头开始移向主菜单，约 0.5 秒后又回到标题。开始后的 7–8 秒内反复出现，Windows 上没有。

**原因**：标题出现时，SIRE 才开始向游戏写入 mod 数据（SIRE 状态栏显示 `ExtMem=[…]`），写完之前游戏会回到标题。写入分三段，共 49,009 次 `WriteProcessMemory`（17,721 + 29,256 + 2,032）。合成点击测试中，第 2 至第 8 次点击都被弹回，ExtMem 之后 7.7 秒的那次点击才进入菜单。这与触摸板和 Wayland 输入无关。

**耗时分析**（Wine relay 跟踪、strace、perf、`/proc/<pid>/task/*/wchan` 采样）：

| 调用 | Wine 中的单次耗时 | 原因 |
| --- | ---: | --- |
| `WriteProcessMemory` 内部的跨进程 `NtQueryVirtualMemory` | 约 64 µs | 以 APC 方式在游戏进程内执行 |
| `NtWriteVirtualMemory` | 约 12–15 µs | 经 wineserver（`process_vm_writev`） |
| `GetPropW` | 7.2 µs | wineserver 往返 |
| `GlobalFindAtomW` | 7.1 µs | wineserver 往返 |
| `SendMessageW`（同线程） | 0.68 µs | — |

SIRE 读取自己的 owner-data 列表控件时发出几十万条消息。Delphi VCL 每路由一条消息都要调用 `GlobalFindAtomW` 和 `GetPropW` 查找控件对象。这些调用在 Windows 上几乎没有开销，在 Wine 中合计达数秒。

GE-Proton 11-7、GE-Proton 11-11、Valve Proton 11.0 的耗时相同（29,256 次写入约 4 秒，每次 137–142 µs），换运行器无效。

**s11fast**（`tools/s11fast`）：`s11inject.exe` 启动 SIRE，等它空闲后用 `CreateRemoteThread` 加载 `s11fast.dll`，由它改写 SIRE 自己导入表中的函数地址。Wine、SIRE 和 mod 文件均不修改。

| 函数组 | 替换为 |
| --- | --- |
| `WriteProcessMemory` | 直接调用 `NtWriteVirtualMemory` 并刷新指令缓存；失败时（如只读代码页）调用原函数 |
| `GetPropW` / `SetPropW` / `RemovePropW` | 以原子为键缓存 SIRE 自己窗口的属性；SIRE 的 `SetPropW`/`RemovePropW` 同步更新；窗口不存在时不用缓存 |
| `GlobalFindAtomW` / `GlobalAddAtomW` / `GlobalDeleteAtom` | 缓存名称到原子的映射，按码元比较；有任何新增或删除时清空 |

导入槽按函数地址匹配，不依赖 SIRE 的固定地址或代码特征。一组函数只有在 SIRE 全部导入时才启用。

从 ExtMem 到最后一次写入的耗时：

| 配置 | 耗时 |
| --- | ---: |
| 不加速 | 7–8 s |
| 只替换写内存 | 5.8 s |
| + 窗口属性缓存 | 3.6 s |
| + 原子缓存 | 约 1.5 s |
| + 原子名称按码元比较（代替 `lstrcmpW`） | 1.28 s（三次中位数） |

加速后，ExtMem 之后约 1–1.25 秒的点击即可进入菜单。

## 7. 剩余等待

- **标题前的黑屏**：SIRE 每秒读一次游戏的两个状态值（最多 300 次），值有效后才开始写入；读取本身只要几十微秒。这段时间是游戏自身的启动时间：从「等待SAN11PK加载数据...」到 ExtMem，GE-Proton 11-7 为 4.0 秒，原版 GE-Proton 11-11 为 5.0 秒（各三次中位数）。
- **标题后的 1.28 秒**：约 19 万条列表消息进入 SIRE 的 Delphi 处理函数（0.66–0.79 s），31,288 次写入（0.41–0.43 s），两者有重叠。要再缩短，就得缓存列表内容、推迟或合并写入，或直接调用窗口过程，都可能改变 SIRE 的行为，因此没有采用。

测过但未采用的改动：

| 改动 | 结果 | 未采用原因 |
| --- | --- | --- |
| 跳过 SIRE 2.10c 进度条完成后的 `Sleep(200)` | 1.282 → 1.075 s | 依赖 SIRE 2.10c 的函数位置；复测时写入的栈残留超出参考运行之间的差异范围，等价性未得到证明 |
| 原子缓存命中时省去长度检查 | 1.287 → 1.296 s | 没有收益 |
| 合并相邻写入 | — | 31,288 次写入分属 25,277 段不连续区域 |

等价性的判断方法：不加速的参考运行之间本身就有差异（字符串结束符之后未初始化的字节，以及一块 97,200 字节的栈缓冲区）。比较时，已确认的文本字段比较到第一个结束符，栈缓冲区只比较 SIRE 实际初始化的部分（900 条记录各 8 字节），其余字节严格比较。

## 8. 声音

32 位的 `winepulse.so` 需要 `lib32-libpulse`，缺少时 Wine 退回 winealsa，经 `lib32-pipewire` 的 ALSA 插件接到 PipeWire，播放正常。

## 9. 其他

- GE 下外部进程无法读取游戏的 `/proc/<pid>/mem`（只有 wineserver 可以 ptrace），内存比对只能在 Valve Proton 下进行。
- Proton 每次启动都会重建 `z:` 和可移动盘的盘符映射，删除无效。真正隔离文件系统需要 bwrap 之类的沙箱，目前没有实现。
- xwayland-satellite 下 xdotool 无法移动指针。自动测试改用在前缀内运行的 Win32 小工具，通过 `SendInput` 模拟点击。
