# App 测试运维助手

给测试和运维使用的图形界面工具。连上手机后可以查看当前设备、重连、安装 APK、打开开发者选项，并一键采集崩溃日志。

## 发给对方

打包结果目录：

`dist\AppCrashLogTool\`

或直接发送：

`AppCrashLogTool-发给对方.zip`

对方解压后双击 `AppCrashLogTool.exe` 即可，无需安装 Python / Android SDK。

## 开发者本地

```bat
run_gui.bat          # 直接运行界面
build_exe.bat        # 重新打包 exe
```

修改包名：编辑 `config.json` 的 `package` 字段。日志采集和“查看当前设备”都会用这个包名。
