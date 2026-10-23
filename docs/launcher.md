# 开始玩

1. `./launcher/san11 setup xs6 --from <mod 的 .zip/.7z/.rar 或解压后的文件夹>`
2. `./launcher/san11 run xs6`（`--windowed` 为窗口模式）
3. **在 SIRE 左上角点「311」**，确认加载血色衣冠包；游戏期间保持 SIRE 打开。
4. 第一次用之前先运行 `tools/build-s11fast.sh`。之后 run 会通过 `s11inject.exe` 启动 SIRE，SIRE 加载 mod 数据从约 8 秒缩到约 1.5 秒；这期间点击标题会被打回，无害，再点一下即可。`--no-s11fast` 可关闭，doctor 会报告它是否就绪。

## 应用菜单

`./launcher/san11 desktop xs6` 写入 `~/.local/share/applications/san11-xs6.desktop`，`--windowed` 另写 `san11-xs6-windowed.desktop`，`--remove` 删除。
图标是 SIRE exe 里最大的图标（没有则用游戏的），存为 `~/.local/share/san11/icons/xs6.png`；PNG 格式的图标直接保存，旧式位图图标用 `magick` 或 `ffmpeg` 转换。
条目运行 `san11 run xs6 --notify`：没有终端时，错误和首次启动提示以桌面通知显示（`notify-send`）。
名称用繁体，通用名用简体（fuzzel 默认只匹配文件名、名称和通用名），所以「三国」「三國」「san11」都能搜到。

## 新版 mod

作者每次发布完整的整包：`San11Pk/`（游戏本体，含剧本、列传、头像等改动）和 `SIRE vX/`（SIRE 与规则包 `.seal`）。
用户数据只有存档。换新版时新建配置，旧配置保留到确认新版正常为止：

```sh
./launcher/san11 setup xs7 --from ~/Downloads/血色衣冠6.0sp13.zip --saves-from xs6
./launcher/san11 run xs7
```

- `--from` 只解压一次，只读放在 `~/Games/san11/pristine/<压缩包名>/`；同一个包再导入会直接复用。
  之后可以用名字代替路径：`--from 血色衣冠6.0sp13`。压缩包可以删掉。
- 不认目录名：启动器自己找 `san11pk.exe` 和 `San11SIRE.exe`，SIRE 升到 v2.11 或外面多一层文件夹都没关系。
- `--saves-from xs6` 复制 xs6 的存档；新版自带的同名文件（如 `SysSavePK.s11`）保留新版的，并提示一句。
  **先看作者的更新说明**：有的版本写明旧存档不能用（如 sp9「本次更新需要重开游戏」），那就不加这个参数。
- 新配置第一次启动会先直接开游戏一次：**看到标题画面后退出**，之后自动打开 SIRE。
- s11fast 不依赖 SIRE 版本；新版 SIRE 出来后可用 `--no-s11fast` 对比一次。

安装了 GE-Proton11-* 时优先选择准备好的专用副本（`san11 prepare-runner`，内含私有 FFmpeg 8，过场动画靠它），
否则选择最新数字版本；用 **原生 Wayland + DXVK**，直接在宿主机运行，不经过 Steam Linux Runtime。
**默认是物理分辨率全屏**（本机 2560×1600，像素 1:1），已从 SIRE 实测：两段开场动画、标题、菜单、鼠标坐标都正常。
启动器每次写入 `DirectMovie=1`：动画画在游戏自己的画面里。若改回 0，动画会另开 ActiveMovie 窗口抢走焦点，
DXVK 把全屏游戏最小化，回到 SIRE 后再也恢复不了（niri 没有任务栏可以点回来）。
`--windowed` 是能放进屏幕的最大窗口（本机 2456×1535），同样像素 1:1。
若新前缀还没有适配器 GUID，启动器会先直接窗口启动游戏一次：**看到标题画面后退出**，
随后自动读取 GUID、写入显示设置，再打开 SIRE；不要在初始化窗口开始战役。

```sh
./launcher/san11 doctor xs6
./launcher/san11 run xs6 --resolution 2560x1600 --dry-run
./launcher/san11 run xs6 --runner ge --proton GE-Proton11-7-x86_64
./launcher/san11 run xs6 --runner ge --x11          # GE 的 X11 回退
./launcher/san11 run xs6 --runner proton --windowed # Valve 回退
./launcher/san11 backup xs6                        # 游戏和 SIRE 退出后
./launcher/san11 stop xs6                          # 另一终端强制结束当前前缀，未保存进度会丢失
```

没有 GE-Proton11-* 时默认回退到 Valve Proton；`--runner ge|proton` 可明确选择。
`--proton NAME` 覆盖自动版本选择，可用目录名或兼容工具显示名。固定版本时每次带上该参数；
对应版本已有专用副本时使用副本。GE 按数字排序（11-10 高于 11-9），优先最新的专用副本。
`--runner` 与指定工具种类冲突会报错。

## 技术说明

Python 3.12+，运行时代码只用标准库。需要已安装的 Proton、GNU `cp`、Fontconfig 和 glibc locale 工具；
无需系统 Wine、winetricks、运行中的 Steam 客户端或 sudo。Wine/Proton 策略集中在 `launcher/proton.py`。

游戏工作副本位于 `~/Games/san11/<profile>/game/{San11Pk,SIRE vX}/`。
setup 从 `pristine/<release>/` 里同时装着 San11Pk 与 SIRE 的那一层用 `cp -a --reflink=auto` 复制，只给副本增加所有者写权限；
.zip 由 Python 解压（无 UTF-8 标记的文件名按 GBK 解码），.7z/.rar 交给 bsdtar；拒绝绝对路径、`..` 和符号链接。
pristine 里只有一个版本时可省略 `--from`；已有游戏文件的配置不接受 `--from`。
重复 setup 保留游戏修改和存档。旧版根目录游戏树会迁移到 game/，旧元数据自动升级。
再次 setup 或迁移前，先关闭游戏和 SIRE。配置名为 1–64 个 ASCII 字母/数字/点/下划线/连字符，
以字母或数字开头，保留 pristine。

**两种 runner 分开前缀**：GE 用 `<profile>/compat-ge/pfx/`，Valve 用 `<profile>/compat/pfx/`。
两者都将 `g:` 映射到 `<profile>/game`，以对应目录为 `STEAM_COMPAT_DATA_PATH`，
`STEAM_COMPAT_CLIENT_INSTALL_PATH=~/.steam/steam`，执行 `proton run 'G:\SIRE vX\San11SIRE.exe'`，
cwd 为 SIRE 目录。`--game` 直接启动游戏，不附加 SIRE 补丁。目标前缀缺少 San11Option 时，
从另一前缀用其 Wine `reg export HKCU\Software\KOEI`，再用目标 Wine `reg import`；已有游戏设置不覆盖。
不会把 GE 与 Valve 指向同一前缀。切换 runner 时无需重新复制游戏或存档。

GE 默认 `PROTON_ENABLE_WAYLAND=1`、`PROTON_USE_WINED3D=0`；`--x11` 禁用 Wayland。
Valve 默认 X11/WineD3D，写 `UseXVidMode=N` 防止模式切换断言；全屏仍有焦点和窗口矩形/点击映射限制，
可能需要先聚焦 SIRE 再切回游戏，建议使用 `--windowed`。GE Wayland 不需要 UseXVidMode，也无需焦点切换。
`--wined3d` / `--dxvk` 可明确覆盖渲染器；本机 Valve DXVK 全屏黑屏。

**电影需要私有 FFmpeg 8**：GE 的 32 位 winedmo 依赖以下 soname，主机 FFmpeg 9 无法替代：
`libavutil.so.60`、`libavformat.so.62`、`libavcodec.so.62`、`libswscale.so.9`、`libswresample.so.6`。
默认目录为 `~/.local/share/san11/ffmpeg8/i386` 和 `~/.local/share/san11/ffmpeg8/x86_64`，
每个目录需包含对应位数的五个库及其符号链接。**LD_LIBRARY_PATH 无效**：GE 会优先加载自己的
`files/lib/{i386,x86_64}-linux-gnu/`。启动器不再设置或继承 LD_LIBRARY_PATH。

setup 检测到两种架构的私有库后，自动用 `cp -a --reflink=auto` 创建
`~/.local/share/san11/runners/<GE目录名>-san11/`，替换副本中五个库族的 `.so*`，保留符号链接，
并写入 `san11-runner.json`（来源、FFmpeg 目录、soname、日期）。Steam 中的原始 GE 保持不变。
缺库时先使用原始 GE，doctor 会提示 **movies will not play**；补齐私有库后执行：

```sh
./launcher/san11 prepare-runner
# 可指定来源 GE（目录名、显示名或路径）和 FFmpeg 根目录；已有副本用 --force 重建：
./launcher/san11 prepare-runner --ge GE-Proton11-7-x86_64 --ffmpeg "$HOME/.local/share/san11/ffmpeg8" --force
```

prepare-runner 默认从 Steam 自定义工具中选择最新 GE-Proton11-*；已有副本不会自动更新，
更换 FFmpeg 构建后需加 `--force`，并先退出所有使用该副本的游戏/SIRE。
setup/doctor 的 `--ffmpeg-i386`、`--ffmpeg-x86_64` 仍可指定不同父目录的私有库；
setup 将这些路径保存在配置中，供 doctor 比对。现有的手工准备副本（如 GE-Proton11-7-san11）也可自动识别。

启动前等待 wineserver 退出，读取 user.reg 并保留 DisplayMode 中的 16 字节 GUID，再用
Proton 的 `files/bin/wine reg add` 写 HKCU\Software\KOEI\San11PK Tc\San11Option：
DisplayMode 0 = GUID + 小端 u32 `(0,1,22,22,77,0,W,H)`，WindowMode=0。
`--windowed` 改写 DisplayMode 1 与 WindowMode=1，选择屏宽、屏高减 64 内面积最大的精确 4:3/16:10 请求；
游戏仍可能钳制窗口尺寸。物理分辨率优先用 niri 当前模式（多屏选 focused output），再用 xrandr/xdpyinfo；
不使用 niri 缩放后的 logical 尺寸。`--resolution WxH` 可覆盖；`--virtual-desktop WxH` 仍供排查使用。

`--codepage 936|950` 分别设置 `LANG=LC_ALL=zh_CN.UTF-8/zh_TW.UTF-8`，缺失 locale 会用 localedef
在 `~/.local/share/san11/locale` 编译并设置 LOCPATH。全局 `--games-root PATH`、`--steam-root PATH`
放在子命令前。所有 Wine/wineserver 命令带正确的 WINEPREFIX、WINEFSYNC=1、WINEESYNC=1。

run 等待同一前缀的 Windows 进程全部退出，记录 Proton 与 wineserver 的退出码（无法单独获得 SIRE 派生游戏的退出码）。
stop 默认结束最后活动的 runner，`stop xs6 --runner proton` 可明确指定；初始化期间 stop 也不会再自动续启 SIRE。
日志在 `<profile>/logs/`；dry-run 不启动 Wine、不写文件。尚无 GUID 时只打印初始化及后续动作说明，
不会编造未来的 REG_BINARY。存档共享于 `game/San11Pk/Koei/San11 Tc/SaveData/`，
backup 在配置空闲时生成 `<profile>/backups/SaveData-<UTC时间>-<id>.zip`。

doctor 检查 GE 目录、winewayland.drv、WAYLAND_DISPLAY、两种架构的五个 FFmpeg 8 库及 ELF 位数，
并将 runner 内两种架构的 `libavformat.so.62` 解析至实际文件，与私有构建比较 SHA256。
另检查字体、locale、Vulkan、分辨率和所选前缀的显示值。注册表是磁盘快照，关闭游戏和 SIRE 后最准确；
`doctor [profile] --runner proton` 可检查 Valve 回退。未使用的 GE/Wayland/私有库检查标为 OPTIONAL。

**s11fast**：SIRE 加载 mod 时约 5 万次 `WriteProcessMemory`，以及每条窗口消息上 Delphi 的 `GlobalFindAtomW` + `GetPropW`；这三个调用在 Wine 里都要经过 wineserver 或游戏进程（每次 7–65 µs，Windows 上近乎为零）。`s11fast.dll` 只改 SIRE 自己的导入表：先直接写内存，写不进去才交给原函数；缓存原子与窗口属性，SIRE 的 `SetPropW`/`RemovePropW`/`GlobalAddAtomW`/`GlobalDeleteAtom` 同步更新缓存，缺任何一个就不启用该缓存。不改 Wine、SIRE 或 mod 文件，与它们的版本无关；`S11FAST_LOG=C:\...` 可记录写入时间线。

**TODO：真正的文件系统隔离需要 bwrap。** 本版不删除 Proton 会重建的 z:、可移动盘映射或主目录链接。
