from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def adb_path() -> Path:
    name = "adb.exe" if sys.platform == "win32" else "adb"
    return app_root() / "platform-tools" / name


@dataclass
class DisplayInfo:
    resolution: str
    dpi: str


@dataclass
class DeviceStatus:
    state: str  # connected / unauthorized / offline / none / error
    serial: Optional[str] = None
    message: str = ""
    serials: List[str] = field(default_factory=list)


class AdbHelper:
    def __init__(self) -> None:
        self.adb = adb_path()

    def available(self) -> bool:
        return self.adb.is_file()

    def _run(
        self,
        args: List[str],
        timeout: Optional[float] = 20,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        return subprocess.run(
            [str(self.adb), *args],
            capture_output=True,
            text=text,
            timeout=timeout,
            creationflags=creationflags,
            encoding="utf-8",
            errors="replace",
        )

    def start_server(self) -> None:
        try:
            self._run(["start-server"], timeout=30)
        except Exception:
            pass

    @staticmethod
    def _output(result: subprocess.CompletedProcess) -> str:
        parts = [result.stdout or "", result.stderr or ""]
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()

    def _query_devices(self) -> Tuple[List[Tuple[str, str]], Optional[str]]:
        try:
            result = self._run(["devices"], timeout=15)
        except Exception as exc:
            return [], str(exc)
        found: List[Tuple[str, str]] = []
        for line in (result.stdout or "").splitlines():
            parts = line.strip().split()
            if len(parts) < 2 or parts[0] == "List":
                continue
            found.append((parts[0], parts[1]))
        return found, None

    def get_status(self, preferred: Optional[str] = None) -> DeviceStatus:
        if not self.available():
            return DeviceStatus("error", message="工具文件不完整，找不到 adb.exe")

        try:
            self.start_server()
        except Exception:
            pass

        found, err = self._query_devices()
        if err and not found:
            return DeviceStatus("error", message=f"检查失败：{err}")

        authorized = [serial for serial, state in found if state == "device"]
        unauthorized = any(state == "unauthorized" for _, state in found)
        offline = any(state == "offline" for _, state in found)

        if authorized:
            serial = preferred if preferred in authorized else authorized[0]
            if len(authorized) == 1:
                message = "手机已连接，可以使用下方功能"
            else:
                message = f"已连接 {len(authorized)} 台设备，可在列表中切换当前设备"
            if unauthorized:
                message += "。还有手机在等待点允许"
            return DeviceStatus("connected", serial=serial, message=message, serials=authorized)
        if unauthorized:
            return DeviceStatus(
                "unauthorized",
                message="手机已插入，请在手机上点【允许 USB 调试】",
            )
        if offline:
            return DeviceStatus(
                "offline",
                message="手机状态异常。可以点【重连设备】，或拔掉数据线再插上",
            )
        return DeviceStatus(
            "none",
            message="未检测到手机。请用数据线连接，并打开 USB 调试",
        )

    def reconnect(self) -> str:
        if not self.available():
            return "工具文件不完整，找不到 adb.exe"
        for args in (["reconnect", "offline"], ["reconnect"]):
            try:
                self._run(args, timeout=20)
            except Exception:
                pass
        time.sleep(1.5)
        found, _err = self._query_devices()
        if any(state == "device" for _, state in found):
            return "重连完成，设备已恢复连接"
        try:
            self._run(["kill-server"], timeout=15)
        except Exception:
            pass
        try:
            self._run(["start-server"], timeout=30)
        except Exception as exc:
            return f"重连失败：{exc}"
        time.sleep(1.0)
        return "已重启连接服务。如果手机再次弹出提示，请点允许"

    def short_summary(self, serial: str) -> str:
        brand = self.getprop(serial, "ro.product.brand")
        model = self.getprop(serial, "ro.product.model") or "未知型号"
        release = self.getprop(serial, "ro.build.version.release") or "?"
        name = " ".join(part for part in (brand, model) if part).strip()
        display = self.read_display(serial)
        parts = [name, f"Android {release}"]
        if display.resolution != "未知":
            parts.append(display.resolution)
        if display.dpi != "未知":
            parts.append(display.dpi)
        parts.append(serial)
        return " · ".join(parts)

    def describe_device(self, serial: str, package: str = "") -> str:
        def prop(key: str) -> str:
            try:
                return self.getprop(serial, key) or "未知"
            except Exception:
                return "未知"

        lines = [
            f"序列号：{serial}",
            f"品牌：{prop('ro.product.brand')}",
            f"厂商：{prop('ro.product.manufacturer')}",
            f"型号：{prop('ro.product.model')}",
            f"设备代号：{prop('ro.product.device')}",
        ]
        display = self.read_display(serial)
        lines.extend(
            [
            f"分辨率：{display.resolution}",
            f"DPI：{display.dpi}",
            f"Android 版本：{prop('ro.build.version.release')}",
            f"SDK：{prop('ro.build.version.sdk')}",
            f"系统版本号：{prop('ro.build.display.id')}",
            f"安全补丁：{prop('ro.build.version.security_patch')}",
            self._battery_line(serial),
            self._wlan_ip(serial),
            self._flag(serial, "development_settings_enabled", "开发者选项"),
            self._flag(serial, "adb_enabled", "USB 调试"),
            ]
        )
        if package:
            try:
                installed = self.app_installed(serial, package)
            except Exception:
                installed = None
            state = "已安装" if installed else "未安装"
            lines.append("")
            lines.append(f"目标应用：{state} {package}")
        return "\n".join(lines)

    def read_display(self, serial: str) -> "DisplayInfo":
        size = self._wm_map(serial, "wm size")
        density = self._wm_map(serial, "wm density")
        physical_size = size.get("physical size", "")
        current_size = size.get("override size", "")
        physical_dpi = density.get("physical density", "")
        current_dpi = density.get("override density", "")
        if not physical_size or not (physical_dpi or current_dpi):
            dumped = self._display_from_dumpsys(serial)
            physical_size = physical_size or dumped[0]
            current_size = current_size or dumped[2]
            physical_dpi = physical_dpi or dumped[1]
            current_dpi = current_dpi or dumped[3]
        if not physical_dpi and not current_dpi:
            try:
                physical_dpi = self.getprop(serial, "ro.sf.lcd_density")
            except Exception:
                physical_dpi = ""
        return DisplayInfo(
            resolution=self._format_display_value(physical_size, current_size, ""),
            dpi=self._format_display_value(physical_dpi, current_dpi, " dpi"),
        )

    def _wm_map(self, serial: str, command: str) -> dict:
        found = {}
        for raw in self._shell_text(serial, command, timeout=8).splitlines():
            if ":" in raw:
                key, value = raw.split(":", 1)
            elif "：" in raw:
                key, value = raw.split("：", 1)
            else:
                continue
            found[key.strip().lower()] = value.strip()
        return found

    def _display_from_dumpsys(self, serial: str) -> Tuple[str, str, str, str]:
        text = self._shell_text(serial, "dumpsys window displays", timeout=12)
        if "init=" not in text and "dpi" not in text.lower():
            text = self._shell_text(serial, "dumpsys display", timeout=15)
        physical_size = ""
        physical_dpi = ""
        current_size = ""
        current_dpi = ""
        init_match = re.search(r"init=(\d+x\d+)\s+(\d+)dpi", text)
        if init_match:
            physical_size = init_match.group(1)
            physical_dpi = init_match.group(2)
        current_match = re.search(r"\bcur=(\d+x\d+)", text)
        if current_match:
            current_size = current_match.group(1)
        if not physical_size:
            size_match = re.search(r"(\d{3,4})\s*x\s*(\d{3,5})", text)
            if size_match:
                physical_size = f"{size_match.group(1)}x{size_match.group(2)}"
        if not physical_dpi:
            density_match = re.search(r"density\s+(\d+)", text) or re.search(r"(\d+)\s*dpi", text, re.I)
            if density_match:
                physical_dpi = density_match.group(1)
        return physical_size, physical_dpi, current_size, current_dpi

    @staticmethod
    def _format_display_value(physical: str, current: str, suffix: str) -> str:
        physical = (physical or "").strip()
        current = (current or "").strip()
        if physical and current and current != physical:
            return f"{physical}{suffix}（当前 {current}{suffix}）"
        value = physical or current
        if not value:
            return "未知"
        return f"{value}{suffix}"

    def _battery_line(self, serial: str) -> str:
        try:
            text = self.shell("dumpsys battery", serial=serial, timeout=12)
        except Exception:
            return "电量：未知"
        level = ""
        status = ""
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("level:"):
                level = line.split(":", 1)[1].strip()
            elif line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
        status_name = {
            "2": "充电中",
            "3": "未在充电",
            "4": "未充电",
            "5": "已充满",
        }.get(status, "")
        if not level:
            return "电量：未知"
        extra = f"（{status_name}）" if status_name else ""
        return f"电量：{level}%{extra}"

    def _wlan_ip(self, serial: str) -> str:
        try:
            route = self.shell("ip route", serial=serial, timeout=8)
        except Exception:
            return "WLAN IP：未知"
        for line in route.splitlines():
            if " src " not in line:
                continue
            ip = line.split(" src ", 1)[1].split()[0]
            if ip:
                return f"WLAN IP：{ip}"
        return "WLAN IP：未获取到"

    def _flag(self, serial: str, key: str, label: str) -> str:
        try:
            value = self.shell(f"settings get global {key}", serial=serial, timeout=8).strip()
        except Exception:
            return f"{label}：未知"
        if value == "1":
            return f"{label}：已开启"
        if value == "0":
            return f"{label}：未开启"
        return f"{label}：未知"

    def install_apk(self, serial: str, apk_path: Path) -> Tuple[bool, str]:
        if not apk_path.is_file():
            return False, "找不到这个 APK 文件"
        try:
            result = self._run(
                ["-s", serial, "install", "-r", "-t", "-d", str(apk_path)],
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return False, "安装超时。请看手机上是否还有确认弹窗，点允许后再试一次。"
        except Exception as exc:
            return False, f"安装失败：{exc}"

        output = self._output(result)
        if result.returncode == 0 and "Success" in (result.stdout or ""):
            return True, "安装成功。同名应用会被覆盖，手机上的数据会保留。"
        if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in output:
            return False, "安装失败：签名和手机上已有的版本不一致。需要先卸载旧版本，再安装这个 APK。"
        if "INSTALL_FAILED_USER_RESTRICTED" in output or "INSTALL_FAILED_ABORTED" in output:
            return False, "手机拦住了这次安装。请在手机上允许通过 USB 安装，或点掉弹出的确认后再试。"
        tail = output[-500:] if output else "没有返回结果"
        return False, f"安装失败：\n{tail}"

    def open_developer_options(self, serial: str) -> Tuple[bool, str]:
        """Open the phone's developer options page through the activity it actually exports.

        Shell is not allowed to start a non-exported activity on Android 14+, so a
        hardcoded old class name fails with Permission Denial. Ask the device which
        component handles the public settings action, then confirm that page is showing.
        """
        self._shell_text(serial, "input keyevent KEYCODE_WAKEUP", timeout=8)
        flag_on = self._enable_developer_flag(serial)

        launches = [
            "-a android.settings.APPLICATION_DEVELOPMENT_SETTINGS -c android.intent.category.DEFAULT",
            "-a com.android.settings.APPLICATION_DEVELOPMENT_SETTINGS -c android.intent.category.DEFAULT",
        ]
        discovered = self._discover_dev_components(serial)
        for component in discovered:
            launches.append(f"-n {self._shell_quote(component)}")
        if not discovered:
            for component in (
                "com.android.settings/.development.DevelopmentSettingsDashboardActivity",
                "com.android.settings/.Settings$DevelopmentSettingsDashboardActivity",
            ):
                launches.append(f"-n {self._shell_quote(component)}")
        launches.append(
            "-n com.android.settings/.Settings "
            "-e :settings:show_fragment com.android.settings.development.DevelopmentSettingsDashboardFragment"
        )

        use_user = True
        saw_permission = False
        last_error = ""
        for args in launches:
            code, output, use_user = self._am_start(serial, args, use_user)
            lowered = output.lower()
            if "permission denial" in lowered or "securityexception" in lowered or "not exported" in lowered:
                saw_permission = True
            if not self._launch_looks_ok(code, output):
                if output:
                    last_error = output
                continue
            state = self._dev_page_state(serial)
            if state == "visible":
                return True, "已在手机上打开开发者选项。"
            if state == "locked":
                return True, "开发者选项已经打开，手机还在锁屏。解锁后就能看到。"
            if state == "unknown" and "status: ok" in lowered and "Development" in output:
                return True, "已向手机发送打开指令。请解锁屏幕，确认是否停在开发者选项。"
            if output:
                last_error = output

        return False, self._developer_failure_message(flag_on, saw_permission, last_error)

    def _enable_developer_flag(self, serial: str) -> bool:
        for command in (
            "settings put global development_settings_enabled 1",
            "settings put secure development_settings_enabled 1",
            "settings put system development_settings_enabled 1",
        ):
            self._shell_text(serial, command, timeout=10)
        value = self._shell_text(serial, "settings get global development_settings_enabled", timeout=10)
        return value.strip() == "1"

    def _discover_dev_components(self, serial: str) -> List[str]:
        found: List[str] = []
        for command in (
            "cmd package resolve-activity --brief -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS -c android.intent.category.DEFAULT",
            "pm resolve-activity --brief -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS -c android.intent.category.DEFAULT",
        ):
            for line in self._shell_text(serial, command, timeout=15).splitlines():
                candidate = line.strip()
                if "/" in candidate and " " not in candidate and not candidate.lower().startswith("no "):
                    found.append(candidate)
            if found:
                break
        if found:
            return self._unique(found)

        for package in ("com.android.settings", "com.oplus.settings", "com.coloros.settings"):
            path_text = self._shell_text(serial, f"pm path {package}", timeout=10)
            if "package:" not in path_text:
                continue
            dump = self._shell_text(serial, f"dumpsys package {package}", timeout=25)
            found.extend(self._extract_dev_components(dump))
        return self._unique(found)

    @staticmethod
    def _extract_dev_components(text: str) -> List[str]:
        pattern = re.compile(r"[\w.]+/[\w.$]*[Dd]evelopment[\w.$]*")
        found: List[str] = []
        for match in pattern.findall(text):
            class_name = match.split("/", 1)[1]
            if any(token in class_name for token in ("Service", "Receiver", "Provider")):
                continue
            found.append(match)
        return found

    def _am_start(self, serial: str, args: str, use_user: bool) -> Tuple[int, str, bool]:
        prefix = "am start -W --user current " if use_user else "am start -W "
        try:
            result = self._run(["-s", serial, "shell", prefix + args], timeout=20)
        except subprocess.TimeoutExpired:
            return 1, "等待页面打开超时", use_user
        except Exception as exc:
            return 1, str(exc), use_user
        output = self._output(result)
        if use_user and "unknown option" in output.lower():
            return self._am_start(serial, args, False)
        return result.returncode, output, use_user

    @staticmethod
    def _launch_looks_ok(code: int, output: str) -> bool:
        lowered = output.lower()
        if any(token in lowered for token in ("permission denial", "securityexception", "not exported")):
            return False
        if any(token in lowered for token in ("unable to resolve", "does not exist", "error type")):
            return False
        if "error:" in lowered and "status: ok" not in lowered:
            return False
        if "status: ok" in lowered:
            return True
        return code == 0 and "starting:" in lowered

    def _dev_page_state(self, serial: str) -> str:
        top = self._shell_text(serial, "dumpsys activity top", timeout=15)
        activity_lines = [line for line in top.splitlines() if "ACTIVITY " in line]
        head = "\n".join(activity_lines[:3]) if activity_lines else top[:500]
        if "DevelopmentSettings" in head or "APPLICATION_DEVELOPMENT_SETTINGS" in head:
            return "visible"
        policy = self._shell_text(serial, "dumpsys window policy", timeout=15)
        if not top and not policy:
            return "unknown"
        locked = any(
            token in policy
            for token in (
                "mKeyguardShowing=true",
                "mKeyguardShown=true",
                "isKeyguardShowing=true",
                "mShowingLockscreen=true",
            )
        )
        if not locked:
            return "no"
        activities = self._shell_text(serial, "dumpsys activity activities", timeout=20)
        for line in activities.splitlines():
            if "ResumedActivity" in line and "Development" in line:
                return "locked"
        return "no"

    @staticmethod
    def _developer_failure_message(flag_on: bool, saw_permission: bool, last_error: str) -> str:
        if saw_permission:
            reason = "手机拒绝 shell 直接点开这个页面。安卓 14 之后，未导出的设置页不能靠壳权限硬开，这不是电脑程序缺权限。"
        elif not flag_on:
            reason = "开发者选项开关没有写进去。当前用户可能不是机主，或手机的管理策略禁止了调试功能。"
        else:
            reason = "系统接到了打开指令，但页面没有停住。厂商可能换了入口，或页面打开后被系统立刻关掉。"
        detail = " ".join(last_error.split())
        if len(detail) > 180:
            detail = detail[:180] + "..."
        if detail:
            return reason + "\n手机返回：" + detail
        return reason

    def _shell_text(self, serial: str, command: str, timeout: float) -> str:
        try:
            result = self._run(["-s", serial, "shell", command], timeout=timeout)
        except Exception:
            return ""
        return self._output(result)

    @staticmethod
    def _shell_quote(value: str) -> str:
        return "'" + value.replace("'", "'\\''") + "'"

    @staticmethod
    def _unique(items: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def shell(self, command: str, serial: Optional[str] = None, timeout: float = 30) -> str:
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", command])
        result = self._run(args, timeout=timeout)
        return (result.stdout or "").strip()

    def logcat_clear(self, serial: str) -> None:
        self._run(["-s", serial, "logcat", "-c"], timeout=15)

    def logcat_dump(self, serial: str, out_file: Path, extra_args: Optional[List[str]] = None) -> None:
        args = ["-s", serial, "logcat", "-d", "-v", "threadtime"]
        if extra_args:
            args.extend(extra_args)
        result = self._run(args, timeout=60)
        out_file.write_text(result.stdout or "", encoding="utf-8", errors="replace")

    def start_logcat_process(self, serial: str, out_file: Path, extra_args: Optional[List[str]] = None) -> subprocess.Popen:
        args = [str(self.adb), "-s", serial, "logcat", "-v", "threadtime"]
        if extra_args:
            args.extend(extra_args)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        out_file.parent.mkdir(parents=True, exist_ok=True)
        stdout = open(out_file, "w", encoding="utf-8", errors="replace")
        stderr = open(str(out_file) + ".err.txt", "w", encoding="utf-8", errors="replace")
        return subprocess.Popen(
            args,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )

    def dumpsys(self, serial: str, service: str, out_file: Path) -> None:
        result = self._run(["-s", serial, "shell", "dumpsys", service], timeout=60)
        out_file.write_text(result.stdout or "", encoding="utf-8", errors="replace")

    def getprop(self, serial: str, key: str) -> str:
        return self.shell(f"getprop {key}", serial=serial, timeout=10)

    def app_installed(self, serial: str, package: str) -> Optional[str]:
        text = self.shell(f"pm path {package}", serial=serial, timeout=15)
        return text or None

    def app_pid(self, serial: str, package: str) -> Optional[str]:
        text = self.shell(f"pidof -s {package}", serial=serial, timeout=10)
        if text.isdigit():
            return text
        return None

    def list_installed_apps(
        self, serial: str, include_system: bool = False
    ) -> List[Tuple[str, str, str]]:
        """返回已安装应用列表，每个元素: (package_name, app_label, app_type)"""
        user_pkgs = self._parse_packages(serial, ["pm", "list", "packages", "-3", "-f"])
        all_pkgs = user_pkgs[:]
        if include_system:
            sys_pkgs = self._parse_packages(serial, ["pm", "list", "packages", "-s", "-f"])
            all_pkgs.extend(sys_pkgs)

        result: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for pkg, _apk, app_type in all_pkgs:
            if pkg in seen:
                continue
            seen.add(pkg)
            label = self.get_app_label(serial, pkg)
            result.append((pkg, label or pkg, app_type))
        return result

    def _parse_packages(
        self, serial: str, args: List[str]
    ) -> List[Tuple[str, str, str]]:
        """解析 pm list packages 输出，返回 [(pkg, apk_path, type)]"""
        apps: List[Tuple[str, str, str]] = []
        try:
            result = self._run(args, timeout=20)
            for line in (result.stdout or "").splitlines():
                line = line.strip()
                if not line.startswith("package:"):
                    continue
                # 格式: package:/path/to/apk=com.example
                parts = line.split("=", 1)
                if len(parts) != 2:
                    continue
                apk_path = parts[0].replace("package:", "")
                pkg = parts[1]
                app_type = "user" if "-3" in args else "system"
                apps.append((pkg, apk_path, app_type))
        except Exception:
            pass
        return apps

    def get_app_label(self, serial: str, package: str) -> str:
        """获取应用显示名称，失败返回空字符串"""
        try:
            text = self._shell_text(serial, f"pm dump {package}", timeout=10)
            # 尝试多种模式匹配应用名
            for pattern in [
                r"nonLocalizedLabel=([^\\n]+)",
                r"labelRes=\\S+\\s+label=([^\\n]+)",
            ]:
                match = re.search(pattern, text)
                if match:
                    return match.group(1).strip()
        except Exception:
            pass
        return ""

    def uninstall_app(self, serial: str, package: str) -> Tuple[bool, str]:
        """卸载应用，返回 (是否成功, 消息)"""
        try:
            result = self._run(
                ["-s", serial, "uninstall", package], timeout=120
            )
            output = self._output(result)
            if result.returncode == 0 and "Success" in output:
                return True, "卸载成功"
            if "DELETE_FAILED" in output:
                return False, f"卸载失败: {output}"
            return False, f"卸载失败: {output}"
        except Exception as exc:
            return False, f"卸载失败: {exc}"
