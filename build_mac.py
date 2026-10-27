#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 macOS 上打包 AppCrashLogTool 的脚本。

用法：
    1) 把本仓库（含 app/、config.json 等）复制到 Mac 上
    2) 确保 Mac 上已安装 Python 3
    3) 在终端里运行：python3 build_mac.py
    4) 打包完成后，dist/AppCrashLogTool 就是可发给别人的文件夹

注意：
    - Mac 上需要自备 macOS 版本的 platform-tools（adb 等二进制文件）
    - 如果没有，脚本会提示你从 Google 下载并放到 platform-tools/ 目录
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def fail(msg: str) -> None:
    print(f"[ERROR] {msg}")
    sys.exit(1)


def run(cmd: list[str], **kwargs) -> None:
    print(f">>> {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def check_platform() -> None:
    if platform.system() != "Darwin":
        fail("这个脚本只能在 macOS 上运行。请把代码复制到 Mac 后再执行。")


def check_platform_tools() -> None:
    adb = ROOT / "platform-tools" / "adb"
    if adb.exists():
        print("[OK] 发现 platform-tools/adb")
        return

    print("""
[WARNING] 找不到 platform-tools/adb

Mac 上需要 macOS 版本的 platform-tools，请按下面步骤操作：

1) 打开浏览器，下载 macOS 版 platform-tools：
   https://developer.android.com/studio/releases/platform-tools

2) 解压下载的 zip，把里面的 adb、fastboot 等文件放到：
   {platform_tools_dir}

3) 重新运行这个脚本。
""".format(platform_tools_dir=ROOT / "platform-tools"))
    sys.exit(1)


def install_deps() -> None:
    print("[1/4] 安装依赖...")
    run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])


def build_app() -> None:
    print("[2/4] 用 PyInstaller 打包...")
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        str(ROOT / "build_mac.spec"),
    ])


def bundle_files() -> None:
    print("[3/4] 复制运行时文件到 .app 内...")
    # PyInstaller 生成的 .app/Contents/MacOS/ 是实际运行目录
    macos_dir = ROOT / "dist" / "AppCrashLogTool.app" / "Contents" / "MacOS"
    if not macos_dir.exists():
        fail("找不到 .app/Contents/MacOS/，打包似乎失败了")

    # platform-tools (Mac 版)
    pt_dest = macos_dir / "platform-tools"
    if pt_dest.exists():
        shutil.rmtree(pt_dest)
    shutil.copytree(ROOT / "platform-tools", pt_dest)

    # config.json
    shutil.copy2(ROOT / "config.json", macos_dir / "config.json")

    # 使用说明
    readme_src = ROOT / "使用说明.txt"
    if readme_src.exists():
        shutil.copy2(readme_src, macos_dir / "使用说明.txt")

    # output-logs 空目录
    (macos_dir / "output-logs").mkdir(exist_ok=True)

    # 同时也在 .app 同级目录放一份，方便手动查看
    app_dir = ROOT / "dist" / "AppCrashLogTool"
    app_dir.mkdir(parents=True, exist_ok=True)

    pt_app = app_dir / "platform-tools"
    if pt_app.exists():
        shutil.rmtree(pt_app)
    shutil.copytree(ROOT / "platform-tools", pt_app)
    shutil.copy2(ROOT / "config.json", app_dir / "config.json")
    if readme_src.exists():
        shutil.copy2(readme_src, app_dir / "使用说明.txt")
    (app_dir / "output-logs").mkdir(exist_ok=True)


def fix_permissions() -> None:
    print("[4/4] 修复可执行权限...")
    # .app/Contents/MacOS/platform-tools/
    pt_macos = ROOT / "dist" / "AppCrashLogTool.app" / "Contents" / "MacOS" / "platform-tools"
    for binary in ("adb", "fastboot"):
        path = pt_macos / binary
        if path.exists():
            path.chmod(0o755)
    # 同级目录的也修一下
    pt_dist = ROOT / "dist" / "AppCrashLogTool" / "platform-tools"
    for binary in ("adb", "fastboot"):
        path = pt_dist / binary
        if path.exists():
            path.chmod(0o755)


def main() -> None:
    check_platform()
    check_platform_tools()
    install_deps()
    build_app()
    bundle_files()
    fix_permissions()

    print("\n" + "=" * 50)
    print("DONE")
    print("=" * 50)
    print(f"打包完成，可发送的文件夹：")
    print(f"  {ROOT / 'dist' / 'AppCrashLogTool'}")
    print("=" * 50)
    print("\n提示：")
    print("- 首次在 Mac 上打开时，可能会提示“无法验证开发者”，")
    print("  右键点击 AppCrashLogTool.app -> 打开 即可。")
    print("- 如果用不了 adb，请确保 platform-tools 是 macOS 版本。")


if __name__ == "__main__":
    main()
