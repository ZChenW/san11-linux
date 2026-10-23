"""Proton/Wine adapter. Keep backend-specific policy here for a future umu backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import uuid


DEFAULT_PROTON = "Proton 10.0"
FFMPEG_LIBS = ("libavutil.so.60", "libavformat.so.62", "libavcodec.so.62", "libswscale.so.9", "libswresample.so.6")
RUNNER_MANIFEST = "san11-runner.json"
OPTIONS = r"HKCU\Software\KOEI\San11PK Tc\San11Option"
X11_DRIVER = r"HKCU\Software\Wine\X11 Driver"
# Deep enough for an archive's top folder above San11Pk/ and SIRE vX/; the game's own data stays unscanned.
RELEASE_DEPTH = 3


@dataclass(frozen=True)
class Release:
    """san11pk.exe and SIRE of one mod release, relative to the directory they were found in."""
    game: Path
    sire: Path

    @property
    def root(self) -> Path:
        # SIRE finds the game by a relative path (..\San11Pk\san11pk.exe), so the folder holding both moves whole.
        return Path(os.path.commonpath([self.game.parent, self.sire.parent]))

    @property
    def saves(self) -> Path:
        return self.game.parent / "Koei/San11 Tc/SaveData"


def find_release(directory: Path) -> Release:
    """Locate the game and SIRE whatever a release calls its folders (SIRE v2.10, SIRE v2.11, ...)."""
    found: dict[str, list[Path]] = {"san11pk.exe": [], "san11sire.exe": []}
    for folder, folders, files in os.walk(directory):
        if len(Path(folder).relative_to(directory).parts) >= RELEASE_DEPTH:
            folders.clear()
        for name in files:
            path = Path(folder) / name
            if name.casefold() in found and not path.is_symlink():
                found[name.casefold()].append(path.relative_to(directory))
    for name, paths in found.items():
        if not paths:
            raise ValueError(f"No {name} in {directory}; pass the mod release's archive or extracted folder")
        if len(paths) > 1:
            raise ValueError(f"Several {name} in {directory}: " + ", ".join(map(str, sorted(paths))) +
                             "; pass the folder of the release to use")
    return Release(found["san11pk.exe"][0], found["san11sire.exe"][0])


@dataclass(frozen=True)
class Proton:
    directory: Path

    @property
    def runner(self) -> str:
        return "ge" if ge_version(self.directory.name) else "proton"

    def supports_wayland(self) -> bool:
        return any(path.is_file() for path in self.directory.glob("files/lib*/wine/*/winewayland.drv*"))

    @property
    def script(self) -> Path:
        return self.directory / "proton"

    def identity(self) -> dict[str, str]:
        version = self.directory / "version"
        identity = {
            "directory": str(self.directory),
            "version": version.read_text().strip() if version.is_file() else "unknown",
        }
        manifest = self.directory / RUNNER_MANIFEST
        if manifest.is_file():
            identity["prepared"] = sha256(manifest)
        return identity

    @property
    def wine(self) -> Path:
        return self.directory / "files/bin/wine"

    @property
    def wineserver(self) -> Path:
        return self.directory / "files/bin/wineserver"

    def validate(self) -> None:
        for executable in (self.script, self.wine, self.wineserver):
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise ValueError(f"Missing executable {executable}; repair this Proton installation in Steam")

    def command(self, *arguments: str) -> list[str]:
        return [str(self.script), "run", *arguments]

    def server(self, option: str) -> list[str]:
        return [str(self.wineserver), option]


def installations(steam: Path) -> dict[str, Proton]:
    """Find folder names and custom-tool display names, including Steam libraries."""
    libraries = [steam]
    manifest = steam / "steamapps/libraryfolders.vdf"
    if manifest.is_file():
        for value in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"', manifest.read_text()):
            libraries.append(Path(value.replace("\\\\", "\\")))
    candidates = []
    for library in libraries:
        candidates.extend(sorted((library / "steamapps/common").glob("*/proton")))
    candidates.extend(sorted((steam / "compatibilitytools.d").glob("*/proton")))
    found = {}
    for script in candidates:
        if not script.is_file() or not os.access(script, os.X_OK):
            continue
        tool = Proton(script.parent.resolve())
        found.setdefault(script.parent.name, tool)
        info = script.parent / "compatibilitytool.vdf"
        if info.is_file():
            match = re.search(r'"display_name"\s+"([^"\r\n]+)"', info.read_text())
            if match:
                found.setdefault(match[1], tool)
    return found


def select(steam: Path, name: str) -> Proton:
    found = installations(steam)
    found.update({tool.directory.name: tool for tool in prepared_installations()})
    if name not in found:
        available = ", ".join(found) or "none"
        raise ValueError(
            f"Proton {name!r} not found under {steam}; available: {available}. "
            "Install it with Steam's Tools library, or use --steam-root / --proton."
        )
    return found[name]


def ge_version(name: str) -> tuple[int, ...]:
    match = re.match(r"GE-Proton(\d+(?:-\d+)*)", name, re.IGNORECASE)
    return tuple(map(int, match[1].split("-"))) if match else ()


def ge_installations(steam: Path) -> list[Proton]:
    tools = {tool.directory: tool for tool in installations(steam).values() if tool.runner == "ge"}
    return sorted(tools.values(), key=lambda tool: (ge_version(tool.directory.name), tool.directory.name))


def runner_root() -> Path:
    return Path.home() / ".local/share/san11/runners"


def prepared_installations() -> list[Proton]:
    # Also recognize the hub's manually prepared GE-Proton11-7-san11 copy,
    # which predates san11-runner.json. Doctor verifies the actual library bytes.
    return sorted(
        (Proton(path.parent) for path in runner_root().glob("GE-Proton*-san11/proton")
         if path.is_file() and os.access(path, os.X_OK) and ge_version(path.parent.name)),
        key=lambda tool: (ge_version(tool.directory.name), tool.directory.name),
    )


def default_runner(steam: Path) -> str:
    return "ge" if any(ge_version(tool.directory.name)[0] == 11
                       for tool in ge_installations(steam) + prepared_installations()) else "proton"


def select_runner(steam: Path, runner: str | None = None, name: str | None = None) -> Proton:
    if name:
        tool = select(steam, name)
        if runner and tool.runner != runner:
            raise ValueError(f"--runner {runner} conflicts with {name!r} ({tool.runner}); prefixes cannot be shared")
        if tool.runner == "ge" and tool.directory.parent != runner_root():
            prepared = [item for item in prepared_installations()
                        if ge_version(item.directory.name) == ge_version(tool.directory.name)]
            exact = runner_root() / (tool.directory.name + "-san11")
            return next((item for item in prepared if item.directory == exact), prepared[-1] if prepared else tool)
        return tool
    if (runner or default_runner(steam)) == "proton":
        return select(steam, DEFAULT_PROTON)
    found = prepared_installations() or ge_installations(steam)
    if not found:
        raise ValueError(f"GE-Proton not found; install GE-Proton11-* under {steam / 'compatibilitytools.d'}, or use --runner proton")
    return found[-1]


def select_ge_source(steam: Path, name: str | None) -> Proton:
    if name:
        path = Path(name).expanduser()
        tool = Proton(path.resolve()) if path.is_dir() else installations(steam).get(name)
        if tool is None:
            raise ValueError(f"GE source {name!r} not found; pass --ge NAME_OR_PATH")
    else:
        custom = (steam / "compatibilitytools.d").resolve()
        tools = [tool for tool in ge_installations(steam)
                 if ge_version(tool.directory.name)[0] == 11 and tool.directory.parent == custom]
        if not tools:
            raise ValueError(f"No GE-Proton11-* source under {steam / 'compatibilitytools.d'}; pass --ge NAME_OR_PATH")
        tool = tools[-1]
    if tool.runner != "ge" or tool.directory.name.endswith("-san11"):
        raise ValueError(f"Choose an original GE-Proton source, not {tool.directory}")
    tool.validate()
    return tool


def ffmpeg_directories() -> dict[str, Path]:
    root = Path.home() / ".local/share/san11/ffmpeg8"
    return {arch: root / arch for arch in ("i386", "x86_64")}


def driver_environment(runner: str, *, x11: bool = False, wined3d: bool | None = None) -> dict[str, str]:
    return {
        "PROTON_ENABLE_WAYLAND": "1" if runner == "ge" and not x11 else "0",
        "PROTON_USE_WINED3D": "1" if (runner == "proton" if wined3d is None else wined3d) else "0",
    }


def ffmpeg_errors(directory: Path, arch: str) -> list[str]:
    errors = []
    for name in FFMPEG_LIBS:
        path = directory / name
        try:
            with path.open("rb") as library:
                header = library.read(5)
        except OSError:
            errors.append(f"missing {name}")
            continue
        if header != b"\x7fELF" + (b"\x01" if arch == "i386" else b"\x02"):
            errors.append(f"{name}: expected {'32' if arch == 'i386' else '64'}-bit ELF")
    return errors


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def movie_library_error(tool: Proton, directory: Path, arch: str) -> str | None:
    bundled = tool.directory / f"files/lib/{arch}-linux-gnu/libavformat.so.62"
    private = directory / "libavformat.so.62"
    try:
        actual = bundled.resolve(strict=True)
        expected = private.resolve(strict=True)
        if sha256(actual) == sha256(expected):
            return None
        return f"{actual}: SHA256 differs from {expected}"
    except OSError as error:
        return f"{bundled}: cannot verify private FFmpeg build ({error})"


def prepare_runner(source: Proton, directories: dict[str, Path], *, force: bool = False) -> Proton:
    """Build a separate GE tree. Unlink bundled symlinks before copying libraries.

    Never mutate Steam's runner or follow one of its library links for writing.
    Stage beside the destination so a failed rebuild leaves the old copy intact.
    """
    source.validate()
    for arch in ("i386", "x86_64"):
        errors = ffmpeg_errors(directories[arch], arch)
        if errors:
            raise ValueError(f"FFmpeg 8 {arch}: {', '.join(errors)} ({directories[arch]})")
    root = runner_root()
    destination = root / (source.directory.name + "-san11")
    if destination.is_symlink() or source.directory.resolve().is_relative_to(destination.resolve()):
        raise ValueError(f"Refusing unsafe runner destination {destination}")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists() and not force:
            if not (destination / RUNNER_MANIFEST).is_file():
                raise ValueError(f"Runner destination exists without {RUNNER_MANIFEST}; use prepare-runner --force")
            result = Proton(destination)
            result.validate()
            return result
        stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=root))
        backup = root / (".previous-" + uuid.uuid4().hex)
        installed = False
        try:
            subprocess.run(["cp", "-a", "--reflink=auto", "--", str(source.directory) + "/.", str(stage)], check=True)
            for arch, private in directories.items():
                target = stage / f"files/lib/{arch}-linux-gnu"
                if not target.resolve().is_relative_to(stage.resolve()):
                    raise ValueError(f"GE library directory links outside the copied runner: {target}")
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(target.stat().st_mode | 0o200)
                for soname in FFMPEG_LIBS:
                    family = soname.split(".so")[0] + ".so*"
                    for bundled in target.glob(family):
                        bundled.unlink()  # Unlink the link itself; never truncate its target.
                    inputs = sorted(private.glob(family))
                    subprocess.run(["cp", "-a", "--reflink=auto", "--remove-destination", "--",
                                    *(str(path) for path in inputs), str(target)], check=True)
            parents = {path.parent for path in directories.values()}
            manifest = {
                "source_ge": str(source.directory),
                "ffmpeg_dir": str(next(iter(parents))) if len(parents) == 1 else None,
                "ffmpeg_directories": {arch: str(path) for arch, path in directories.items()},
                "sonames": list(FFMPEG_LIBS), "date": datetime.now(timezone.utc).isoformat(),
            }
            stage.chmod(stage.stat().st_mode | 0o200)
            (stage / RUNNER_MANIFEST).unlink(missing_ok=True)
            (stage / RUNNER_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
            Proton(stage).validate()
            if destination.exists():
                destination.rename(backup)
            try:
                stage.rename(destination)
                installed = True
            except OSError:
                if backup.exists():
                    backup.rename(destination)
                raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
            if installed and backup.exists():
                shutil.rmtree(backup)
    return Proton(destination)


def environment(
    base: dict[str, str], profile: Path, steam: Path, logs: Path, *, wined3d: bool | None = None,
    runner: str = "proton"
) -> dict[str, str]:
    settings = {**driver_environment(runner), **base}
    # Round-three metadata may still contain the ineffective FFmpeg path.
    settings.pop("LD_LIBRARY_PATH", None)
    if wined3d is not None:
        settings["PROTON_USE_WINED3D"] = "1" if wined3d else "0"
    return {
        **settings,
        "WINEPREFIX": str(prefix(profile, runner)),
        "WINEFSYNC": "1",
        "WINEESYNC": "1",
        "STEAM_COMPAT_DATA_PATH": str(prefix(profile, runner).parent),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(steam),
        "STEAM_COMPAT_INSTALL_PATH": str(profile / "game"),
        "STEAM_COMPAT_APP_ID": "0",
        "SteamAppId": "0",
        "SteamGameId": "0",
        "PROTON_LOG": "1",
        "PROTON_LOG_DIR": str(logs),
        "DXVK_LOG_PATH": str(logs),
        "VKD3D_LOG_FILE": str(logs / "vkd3d.log"),
    }


def windows_path(relative: Path) -> str:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Windows paths must stay inside the profile")
    return "G:\\" + "\\".join(relative.parts)


def prefix(profile: Path, runner: str = "proton") -> Path:
    return profile / ("compat-ge" if runner == "ge" else "compat") / "pfx"


# s11fast (tools/s11fast): s11inject.exe starts SIRE and loads s11fast.dll into it, which makes SIRE's memory
# writes and window lookups cheap under Wine. Without it the title keeps bouncing back for several seconds while
# SIRE loads the mod.
S11FAST_FILES = ("s11fast.dll", "s11inject.exe")
S11FAST_TARGET = Path("drive_c/san11-tools")
S11INJECT = r"C:\san11-tools\s11inject.exe"


def s11fast_source() -> Path:
    return Path.home() / ".local/share/san11/s11fast"


def s11fast_ready(source: Path) -> bool:
    return all((source / name).is_file() for name in S11FAST_FILES)


def install_s11fast(source: Path, profile: Path, runner: str) -> None:
    target = prefix(profile, runner) / S11FAST_TARGET
    target.mkdir(parents=True, exist_ok=True)
    for name in S11FAST_FILES:
        shutil.copy2(source / name, target / name)


def launch(tool: Proton, release: Release, *, sire: bool, desktop: str | None,
           s11fast: bool = False) -> tuple[list[str], Path]:
    executable = release.sire if sire else release.game
    args = [windows_path(executable)]
    if sire and s11fast:
        args = [S11INJECT, *args]
    if desktop:
        args = ["explorer.exe", f"/desktop=san11,{desktop}", *args]
    return tool.command(*args), executable.parent


def map_game(profile: Path, runner: str = "proton") -> None:
    """Add G: without interfering with drives or home links maintained by Proton.

    TODO: real filesystem isolation requires a bwrap launch boundary. Deleting
    Z: is ineffective: Proton/Wine recreates it, along with removable drives.
    """
    devices = prefix(profile, runner) / "dosdevices"
    if devices.is_symlink() or not (prefix(profile, runner) / "drive_c").is_dir():
        raise ValueError(f"Proton did not create {prefix(profile, runner) / 'drive_c'}; inspect setup logs")
    devices.mkdir(exist_ok=True)
    drive = devices / "g:"
    target = profile / "game"
    if drive.is_symlink() and drive.resolve() == target:
        return
    if drive.exists() and not drive.is_symlink():
        raise ValueError(f"Refusing to replace a non-symlink drive: {drive}")
    if drive.is_symlink():
        drive.unlink()
    drive.symlink_to(target, target_is_directory=True)


def read_registry(profile: Path, runner: str = "proton") -> dict[str, dict[str, bytes | int | str]]:
    """Read Wine's on-disk HKCU snapshot. Caller waits for wineserver first.

    Doctor/dry-run only inspect the snapshot; they never start Wine. Unknown or
    malformed entries are ignored, never replaced with an invented adapter GUID.
    """
    registry = prefix(profile, runner) / "user.reg"
    if not registry.is_file():
        return {}
    text = registry.read_text(encoding="utf-8").replace("\\\n", "")
    sections: dict[str, dict[str, bytes | int | str]] = {}
    current = None
    for line in text.splitlines():
        section = re.match(r"\[(.*)\](?:\s.*)?$", line)
        if section:
            key = section[1].replace("\\\\", "\\").casefold()
            current = sections.setdefault("hkcu\\" + key, {})
            continue
        value = re.fullmatch(r'"((?:\\.|[^"\\])*)"=(.*)', line.strip())
        if value is None or current is None:
            continue
        name, raw = value[1].casefold(), value[2].strip()
        try:
            if raw.startswith("hex:"):
                current[name] = bytes.fromhex(raw[4:].replace(",", " "))
            elif raw.startswith("dword:"):
                current[name] = int(raw[6:], 16)
            elif raw.startswith('"') and raw.endswith('"'):
                current[name] = re.sub(r'\\([\\"])', r'\1', raw[1:-1])
        except ValueError:
            continue
    return sections


def decode_display(value: object) -> tuple[bytes, tuple[int, ...]] | None:
    if not isinstance(value, bytes) or len(value) != 48:
        return None
    return value[:16], struct.unpack("<8I", value[16:])


def adapter_guid(registry: dict, *, windowed: bool) -> bytes | None:
    options = registry.get(OPTIONS.casefold(), {})
    for mode in ((1, 0) if windowed else (0, 1)):
        decoded = decode_display(options.get(f"displaymode {mode}"))
        if decoded is not None:
            return decoded[0]
    return None


def display_commands(tool: Proton, guid: bytes | None, size: tuple[int, int],
                     *, windowed: bool, x11: bool = True) -> list[list[str]]:
    """Write the exact format measured on the host using Proton's own wine.

    A prefix without a saved GUID must be seeded with a windowed first run;
    WindowMode/UseXVidMode can be set without fabricating a DisplayMode value.
    """
    commands = []
    if guid is not None:
        if len(guid) != 16:
            raise ValueError("Adapter GUID must be exactly 16 bytes")
        payload = guid + struct.pack("<8I", 0, 1, 22, 22, 77, int(windowed), *size)
        commands.append([str(tool.wine), "reg", "add", OPTIONS, "/v", f"DisplayMode {int(windowed)}",
                         "/t", "REG_BINARY", "/d", payload.hex(), "/f"])
    elif not windowed:
        raise ValueError("No adapter GUID; run the game once windowed first")
    commands.append([str(tool.wine), "reg", "add", OPTIONS, "/v", "WindowMode", "/t", "REG_DWORD", "/d", str(int(windowed)), "/f"])
    # Started from SIRE, the game loses focus to SIRE and minimises itself unless it keeps running when inactive.
    commands.append([str(tool.wine), "reg", "add", OPTIONS, "/v", "AlwaysActive", "/t", "REG_DWORD", "/d", "1", "/f"])
    # Draw movies inside the game's own surface. With 0 they get a separate ActiveMovie window that takes focus, and
    # DXVK minimises the fullscreen game for good once SIRE gets the focus back.
    commands.append([str(tool.wine), "reg", "add", OPTIONS, "/v", "DirectMovie", "/t", "REG_DWORD", "/d", "1", "/f"])
    if x11:
        commands.append([str(tool.wine), "reg", "add", X11_DRIVER, "/v", "UseXVidMode", "/t", "REG_SZ", "/d", "N", "/f"])
    return commands


def font_substitutions(families: dict[str, set[str]]) -> dict[str, str]:
    def choose(language: str, preferred: tuple[str, ...]) -> str:
        available = families[language]
        for family in preferred:
            if family in available:
                return family
        if not available:
            raise ValueError(f"No CJK fonts for {language}; install: sudo pacman -S noto-fonts-cjk")
        return sorted(available)[0]

    sc_serif = choose("zh-cn", ("Noto Serif CJK SC", "Source Han Serif CN", "WenQuanYi Zen Hei"))
    tc_serif = choose("zh-tw", ("Noto Serif CJK TC", "Source Han Serif TW", "WenQuanYi Zen Hei"))
    sc_sans = choose("zh-cn", ("Noto Sans CJK SC", "Source Han Sans CN", "WenQuanYi Zen Hei"))
    tc_sans = choose("zh-tw", ("Noto Sans CJK TC", "Source Han Sans TW", "WenQuanYi Zen Hei"))
    groups = (
        (sc_serif, ("SimSun", "NSimSun", "宋体", "宋體", "新宋体", "新宋體", "MS Song", "FangSong", "KaiTi")),
        (tc_serif, ("MingLiU", "PMingLiU", "MingLiU_HKSCS", "新細明體", "細明體")),
        (sc_sans, ("Microsoft YaHei", "Microsoft YaHei UI", "微软雅黑", "微軟雅黑", "SimHei", "黑体")),
        (tc_sans, ("Microsoft JhengHei", "Microsoft JhengHei UI", "微軟正黑體")),
    )
    return {alias: target for target, aliases in groups for alias in (*aliases, *("@" + a for a in aliases))}


def registry(substitutions: dict[str, str], release: Release) -> str:
    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    install = r"Software\KOEI\San11PK TC\Install"
    lines = ["Windows Registry Editor Version 5.00", ""]
    # The supplied .reg specifies HKCU. Mirror the install value for older
    # tools that may read HKLM, including the 32-bit view in a 64-bit prefix.
    for key in (
        "HKEY_CURRENT_USER\\" + install,
        "HKEY_LOCAL_MACHINE\\" + install,
        "HKEY_LOCAL_MACHINE\\Software\\Wow6432Node\\" + install.removeprefix("Software\\"),
    ):
        lines.extend([f"[{key}]", '"InstallInfo"=' + quote(windows_path(release.game.parent)), ""])
    lines.extend([r"[HKEY_CURRENT_USER\Software\KOEI\San11PK TC\PL]", '"10"=dword:00000000', ""])
    for key in (
        r"HKEY_LOCAL_MACHINE\Software\Microsoft\Windows NT\CurrentVersion\FontSubstitutes",
        r"HKEY_CURRENT_USER\Software\Wine\Fonts\Replacements",
    ):
        lines.append(f"[{key}]")
        lines.extend(f"{quote(alias)}={quote(target)}" for alias, target in sorted(substitutions.items()))
        lines.append("")
    return "\r\n".join(lines)
