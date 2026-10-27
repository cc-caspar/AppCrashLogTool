# App 测试运维助手

给测试和运维使用的图形界面工具。连上手机后可以查看当前设备、重连、安装 APK、打开开发者选项，并一键采集崩溃日志。

## 发给对方

打包结果目录：

`dist\AppCrashLogTool\`

或直接发送：

`AppCrashLogTool-发给对方.zip`

对方解压后双击 `AppCrashLogTool.exe` 即可，无需安装 Python / Android SDK。

## Mac 版打包

本项目支持通过 GitHub Actions 在云端自动打包 macOS 版本。

### 自动打包（推荐）

1. 推送代码到 GitHub 后，进入仓库 **Actions** 页面
2. 点击左侧 **Build macOS App**
3. 点击右上角 **Run workflow → Run workflow**
4. 等待约 3~5 分钟，打包完成后在页面下方 **Artifacts** 区域下载 `AppCrashLogTool-macOS`

> **Artifacts 下载后怎么用？**
> - 下载的 zip 解压后就是 `AppCrashLogTool.app`（不需要再解压）
> - 把 `AppCrashLogTool.app` 拖到「应用程序」文件夹，或者双击直接运行

### 本地打包（需要 Mac）

```bash
# 先下载 macOS 版 platform-tools 替换掉 Windows 版本
# https://developer.android.com/studio/releases/platform-tools

python3 build_mac.py
```

打包完成后 `dist/AppCrashLogTool/` 就是可发送的文件夹。

### Mac 首次运行注意事项

由于应用没有苹果开发者签名，macOS 可能会阻止运行。

**情况 1：提示"无法验证开发者"**
- 右键点击 `AppCrashLogTool.app` → **打开**
- 在弹出的提示里选择**"打开"**

**情况 2：提示"已损坏，无法打开"（如下图所示）**
- 打开终端（Terminal），执行：
  ```bash
  xattr -cr /Applications/AppCrashLogTool.app
  ```
  或者如果你把 app 放在桌面：
  ```bash
  xattr -cr ~/Desktop/AppCrashLogTool.app
  ```
- 然后重新双击打开即可

## 开发者本地

```bat
run_gui.bat          # 直接运行界面
build_exe.bat        # 重新打包 exe（Windows）
```

修改包名：编辑 `config.json` 的 `package` 字段。日志采集和"查看当前设备"都会用这个包名。
