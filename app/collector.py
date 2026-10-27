from __future__ import annotations

import json
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from adb_helper import AdbHelper, app_root


ProgressCb = Callable[[str], None]
ShouldStopCb = Callable[[], bool]


@dataclass
class CaptureResult:
    ok: bool
    message: str
    zip_path: Optional[Path] = None
    out_dir: Optional[Path] = None


def load_config() -> dict:
    cfg_path = app_root() / "config.json"
    default = {"package": "com.example.myapplication", "max_seconds": 300}
    if not cfg_path.is_file():
        return default
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        default.update(data or {})
    except Exception:
        pass
    return default


class CrashCollector:
    def __init__(self, adb: Optional[AdbHelper] = None) -> None:
        self.adb = adb or AdbHelper()

    def capture(
        self,
        serial: str,
        on_progress: Optional[ProgressCb] = None,
        should_stop: Optional[ShouldStopCb] = None,
    ) -> CaptureResult:
        def progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        cfg = load_config()
        package = (cfg.get("package") or "").strip()
        max_seconds = int(cfg.get("max_seconds") or 300)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_root = app_root() / "output-logs"
        out_dir = out_root / f"crash_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        progress("正在保存设备信息...")
        info_lines = [
            f"time={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"serial={serial}",
            f"package={package}",
        ]
        for key in (
            "ro.product.model",
            "ro.product.brand",
            "ro.product.manufacturer",
            "ro.build.version.release",
            "ro.build.version.sdk",
            "ro.build.display.id",
        ):
            info_lines.append(f"{key}={self.adb.getprop(serial, key)}")
        (out_dir / "device_info.txt").write_text("\n".join(info_lines), encoding="utf-8")

        if package:
            path_line = self.adb.app_installed(serial, package)
            (out_dir / "app_path.txt").write_text(path_line or f"NOT_INSTALLED: {package}", encoding="utf-8")
            if path_line:
                self.adb.dumpsys(serial, f"package {package}", out_dir / "package_dumpsys.txt")

        progress("正在清空旧日志...")
        self.adb.logcat_clear(serial)
        time.sleep(0.4)

        progress("开始采集，请在手机上复现崩溃...")
        procs = []
        try:
            procs.append(self.adb.start_logcat_process(serial, out_dir / "logcat_full.txt"))
            procs.append(
                self.adb.start_logcat_process(
                    serial, out_dir / "logcat_crash.txt", ["-b", "crash"]
                )
            )
            procs.append(
                self.adb.start_logcat_process(
                    serial, out_dir / "logcat_main.txt", ["-b", "main"]
                )
            )
            procs.append(
                self.adb.start_logcat_process(
                    serial,
                    out_dir / "logcat_runtime.txt",
                    ["AndroidRuntime:E", "FATAL:E", "System.err:W", "*:S"],
                )
            )
            app_pid = self.adb.app_pid(serial, package) if package else None
            if app_pid:
                (out_dir / "app_pid.txt").write_text(app_pid, encoding="utf-8")
                procs.append(
                    self.adb.start_logcat_process(
                        serial, out_dir / "logcat_app_pid.txt", ["--pid", app_pid]
                    )
                )

            started = time.time()
            while True:
                if should_stop and should_stop():
                    progress("已收到结束指令，正在整理日志...")
                    break
                elapsed = int(time.time() - started)
                if elapsed >= max_seconds:
                    progress("已到最长采集时间，正在整理日志...")
                    break
                crash_file = out_dir / "logcat_crash.txt"
                if crash_file.exists() and crash_file.stat().st_size > 80:
                    progress(f"采集中... {elapsed} 秒（好像已抓到崩溃，可点结束）")
                else:
                    progress(f"采集中... {elapsed} 秒（崩溃后请点【结束并保存】）")
                time.sleep(0.5)
        finally:
            for p in procs:
                try:
                    if p.poll() is None:
                        p.terminate()
                except Exception:
                    pass
            time.sleep(0.6)
            for p in procs:
                try:
                    if p.poll() is None:
                        p.kill()
                except Exception:
                    pass
                try:
                    if p.stdout:
                        p.stdout.close()
                    if p.stderr:
                        p.stderr.close()
                except Exception:
                    pass

        progress("正在补充抓取崩溃缓冲...")
        self.adb.logcat_dump(serial, out_dir / "logcat_dump_after.txt")
        self.adb.logcat_dump(serial, out_dir / "logcat_crash_dump.txt", ["-b", "crash"])
        self.adb.logcat_dump(
            serial,
            out_dir / "logcat_runtime_dump.txt",
            ["AndroidRuntime:E", "FATAL:E", "System.err:W", "*:S"],
        )
        self.adb.dumpsys(serial, "dropbox --print", out_dir / "dropbox.txt")
        self._write_keywords(out_dir / "logcat_dump_after.txt", out_dir / "logcat_keywords.txt", package)

        readme = [
            "请把整个 zip 发给开发人员。",
            "开发优先查看：",
            "1) logcat_crash_dump.txt",
            "2) logcat_keywords.txt",
            "3) logcat_runtime_dump.txt",
            "4) logcat_full.txt",
            "5) device_info.txt",
        ]
        (out_dir / "README_请先看我.txt").write_text("\n".join(readme), encoding="utf-8")

        progress("正在打包 zip...")
        zip_path = out_root / f"crash_{stamp}.zip"
        self._zip_dir(out_dir, zip_path)

        return CaptureResult(
            ok=True,
            message="采集完成，请把下面的 zip 发给开发人员",
            zip_path=zip_path if zip_path.exists() else None,
            out_dir=out_dir,
        )

    def dump_existing(self, serial: str, on_progress: Optional[ProgressCb] = None) -> CaptureResult:
        def progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        cfg = load_config()
        package = (cfg.get("package") or "").strip()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_root = app_root() / "output-logs"
        out_dir = out_root / f"dump_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        progress("正在补抓当前日志...")
        self.adb.logcat_dump(serial, out_dir / "logcat_dump.txt")
        self.adb.logcat_dump(serial, out_dir / "logcat_crash.txt", ["-b", "crash"])
        self.adb.logcat_dump(
            serial,
            out_dir / "logcat_runtime.txt",
            ["AndroidRuntime:E", "FATAL:E", "System.err:W", "*:S"],
        )
        self.adb.dumpsys(serial, "dropbox --print", out_dir / "dropbox.txt")
        self._write_keywords(out_dir / "logcat_dump.txt", out_dir / "logcat_keywords.txt", package)

        zip_path = out_root / f"dump_{stamp}.zip"
        self._zip_dir(out_dir, zip_path)
        return CaptureResult(
            ok=True,
            message="补抓完成，请把下面的 zip 发给开发人员",
            zip_path=zip_path if zip_path.exists() else None,
            out_dir=out_dir,
        )

    @staticmethod
    def _write_keywords(src: Path, dest: Path, package: str) -> None:
        if not src.exists():
            dest.write_text("source missing", encoding="utf-8")
            return
        keys = [
            "FATAL EXCEPTION",
            "AndroidRuntime",
            "Process: ",
            "java.lang.",
            "Caused by:",
            "ANR in",
            "am_crash",
            "am_anr",
        ]
        if package:
            keys.append(re.escape(package))
        pattern = re.compile("|".join(keys))
        matched: List[str] = []
        try:
            for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
                if pattern.search(line):
                    matched.append(line)
        except Exception:
            pass
        if matched:
            dest.write_text("\n".join(matched), encoding="utf-8")
        else:
            dest.write_text("未匹配到明显崩溃关键字，请查看完整日志。", encoding="utf-8")

    @staticmethod
    def _zip_dir(src_dir: Path, zip_path: Path) -> None:
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file in src_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, arcname=str(file.relative_to(src_dir)))
