from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from adb_helper import AdbHelper, app_root
from collector import CrashCollector, load_config


class CrashLogApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("App 测试运维助手")
        self.geometry("780x760")
        self.minsize(740, 680)
        self.configure(bg="#F7F8FA")

        self.adb = AdbHelper()
        self.collector = CrashCollector(self.adb)
        self.current_serial: str | None = None
        self.preferred_serial: str | None = None
        self.capturing = False
        self.busy = False
        self.stop_flag = False
        self._poll_after_id = None
        self._summary_loading = False
        self.summary_serial: str | None = None
        self.summary_text = ""
        self._serials: list[str] = []
        self._updating_picker = False
        self.device_win: tk.Toplevel | None = None
        self.package = (load_config().get("package") or "").strip()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self.refresh_status)
        self._schedule_poll()

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg="#F7F8FA")
        header.pack(fill="x", padx=24, pady=(16, 4))
        tk.Label(
            header,
            text="App 测试运维助手",
            font=("Microsoft YaHei UI", 20, "bold"),
            bg="#F7F8FA",
            fg="#1F2937",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="查看设备、重连、安装 APK、打开开发者选项，并采集崩溃日志",
            font=("Microsoft YaHei UI", 11),
            bg="#F7F8FA",
            fg="#6B7280",
        ).pack(anchor="w", pady=(4, 0))

        status_card = self._card()
        row = tk.Frame(status_card, bg="#FFFFFF")
        row.pack(fill="x", padx=18, pady=16)

        self.status_dot = tk.Canvas(row, width=22, height=22, bg="#FFFFFF", highlightthickness=0)
        self.status_dot.pack(side="left")
        self._dot_id = self.status_dot.create_oval(3, 3, 19, 19, fill="#9CA3AF", outline="")

        text_col = tk.Frame(row, bg="#FFFFFF")
        text_col.pack(side="left", padx=(12, 0), fill="x", expand=True)

        self.status_title = tk.Label(
            text_col,
            text="正在检查手机连接...",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#FFFFFF",
            fg="#111827",
            anchor="w",
        )
        self.status_title.pack(fill="x")

        self.status_detail = tk.Label(
            text_col,
            text="",
            font=("Microsoft YaHei UI", 10),
            bg="#FFFFFF",
            fg="#6B7280",
            anchor="w",
            justify="left",
        )
        self.status_detail.pack(fill="x", pady=(4, 0))

        self.device_pick = ttk.Combobox(text_col, state="readonly", width=42)
        self.device_pick.bind("<<ComboboxSelected>>", self._on_pick_device)

        self.refresh_btn = ttk.Button(row, text="重新检查", command=lambda: self.refresh_status(reload_summary=True))
        self.refresh_btn.pack(side="right")

        device_card = self._card()
        self._section_title(device_card, "设备")
        device_row = tk.Frame(device_card, bg="#FFFFFF")
        device_row.pack(fill="x", padx=16, pady=(0, 16))

        self.reconnect_btn = self._action_button(
            device_row, "重连设备", "#2563EB", "white", self.reconnect_device, bold=True
        )
        self.reconnect_btn.pack(side="left")

        self.view_btn = self._action_button(
            device_row, "查看当前设备", "#E5E7EB", "#111827", self.view_device
        )
        self.view_btn.pack(side="left", padx=(12, 0))

        self.install_btn = self._action_button(
            device_row, "安装 APK", "#E5E7EB", "#111827", self.install_apk
        )
        self.install_btn.pack(side="left", padx=(12, 0))

        self.uninstall_btn = self._action_button(
            device_row, "卸载应用", "#E5E7EB", "#111827", self.uninstall_app
        )
        self.uninstall_btn.pack(side="left", padx=(12, 0))

        self.dev_btn = self._action_button(
            device_row, "打开开发者选项", "#E5E7EB", "#111827", self.open_developer_options
        )
        self.dev_btn.pack(side="left", padx=(12, 0))

        log_card = self._card()
        self._section_title(log_card, "日志采集")
        package_text = f"目标应用：{self.package}" if self.package else "目标应用：未设置，可在 config.json 里填写 package"
        tk.Label(
            log_card,
            text=package_text,
            font=("Microsoft YaHei UI", 10),
            bg="#FFFFFF",
            fg="#6B7280",
            anchor="w",
        ).pack(fill="x", padx=16)
        tk.Label(
            log_card,
            text="点【开始采集日志】后，在手机上把问题操作一遍，再点【结束并保存】。",
            font=("Microsoft YaHei UI", 11),
            bg="#FFFFFF",
            fg="#374151",
            anchor="w",
        ).pack(fill="x", padx=16, pady=(4, 0))

        action = tk.Frame(log_card, bg="#FFFFFF")
        action.pack(fill="x", padx=16, pady=(12, 16))

        self.start_btn = self._action_button(
            action, "开始采集日志", "#16A34A", "white", self.start_capture, bold=True, pady=10
        )
        self.start_btn.pack(side="left")
        self.start_btn.configure(state="disabled")

        self.stop_btn = self._action_button(
            action, "结束并保存", "#DC2626", "white", self.stop_capture, bold=True, pady=10
        )
        self.stop_btn.pack(side="left", padx=(12, 0))
        self.stop_btn.configure(state="disabled", disabledforeground="white")

        self.dump_btn = self._action_button(action, "补抓已有日志", "#E5E7EB", "#111827", self.dump_existing)
        self.dump_btn.pack(side="left", padx=(12, 0))
        self.dump_btn.configure(state="disabled")

        self.open_btn = self._action_button(action, "打开结果文件夹", "#E5E7EB", "#111827", self.open_output)
        self.open_btn.pack(side="right")

        self.view_btn.configure(state="disabled")
        self.install_btn.configure(state="disabled")
        self.uninstall_btn.configure(state="disabled")
        self.dev_btn.configure(state="disabled")

        tip = tk.Frame(self, bg="#FFFFFF", highlightbackground="#E5E7EB", highlightthickness=1)
        tip.pack(fill="both", expand=True, padx=24, pady=(6, 20))

        tk.Label(
            tip,
            text="当前提示",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg="#FFFFFF",
            fg="#111827",
        ).pack(anchor="w", padx=16, pady=(14, 6))

        self.tip_var = tk.StringVar(value="请先用数据线连接手机，并打开 USB 调试。连接成功后，上方会变成绿色“已连接”。")
        self.tip_label = tk.Label(
            tip,
            textvariable=self.tip_var,
            font=("Microsoft YaHei UI", 11),
            bg="#FFFFFF",
            fg="#374151",
            justify="left",
            wraplength=700,
            anchor="nw",
        )
        self.tip_label.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self.result_var = tk.StringVar(value="")
        self.result_label = tk.Label(
            tip,
            textvariable=self.result_var,
            font=("Microsoft YaHei UI", 10),
            bg="#FFFFFF",
            fg="#047857",
            justify="left",
            wraplength=700,
            anchor="w",
        )
        self.result_label.pack(fill="x", padx=16, pady=(0, 14))
        self.bind("<Configure>", self._on_resize)

    def _card(self) -> tk.Frame:
        card = tk.Frame(self, bg="#FFFFFF", highlightbackground="#E5E7EB", highlightthickness=1)
        card.pack(fill="x", padx=24, pady=6)
        return card

    @staticmethod
    def _section_title(parent: tk.Frame, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#FFFFFF",
            fg="#111827",
        ).pack(anchor="w", padx=16, pady=(12, 8))

    @staticmethod
    def _action_button(
        parent: tk.Misc,
        text: str,
        bg: str,
        fg: str,
        command,
        bold: bool = False,
        pady: int = 8,
    ) -> tk.Button:
        font = ("Microsoft YaHei UI", 12 if bold else 11, "bold" if bold else "normal")
        return tk.Button(
            parent,
            text=text,
            font=font,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            padx=14,
            pady=pady,
            cursor="hand2",
            command=command,
        )

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        width = max(480, event.width - 80)
        self.tip_label.configure(wraplength=width)
        self.result_label.configure(wraplength=width)

    def _set_status(self, color: str, title: str, detail: str) -> None:
        self.status_dot.itemconfigure(self._dot_id, fill=color)
        self.status_title.configure(text=title)
        self.status_detail.configure(text=detail)

    def _sync_device_picker(self, serials: list[str], current: str | None) -> None:
        self._updating_picker = True
        try:
            if len(serials) > 1:
                self.device_pick["values"] = serials
                if current:
                    self.device_pick.set(current)
                if not self.device_pick.winfo_ismapped():
                    self.device_pick.pack(fill="x", pady=(8, 0))
            elif self.device_pick.winfo_ismapped():
                self.device_pick.pack_forget()
        finally:
            self._updating_picker = False

    def _set_connected_actions(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.view_btn, self.install_btn, self.uninstall_btn, self.dev_btn, self.start_btn, self.dump_btn):
            btn.configure(state=state)

    def _schedule_poll(self) -> None:
        if self._poll_after_id:
            self.after_cancel(self._poll_after_id)
        self._poll_after_id = self.after(2000, self._poll_status)

    def _poll_status(self) -> None:
        if not self.capturing and not self.busy:
            self.refresh_status(silent=True)
        self._schedule_poll()

    def _request_summary(self, serial: str) -> None:
        self._summary_loading = True

        def worker() -> None:
            try:
                text = self.adb.short_summary(serial)
            except Exception:
                text = ""

            def apply() -> None:
                self._summary_loading = False
                if not self.winfo_exists() or self.current_serial != serial:
                    return
                self.summary_serial = serial
                if not text:
                    return
                self.summary_text = text
                detail = text
                if len(self._serials) > 1:
                    detail = f"{text}（可在下方切换）"
                self.status_detail.configure(text=detail)

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_status(self, silent: bool = False, reload_summary: bool = False) -> None:
        if self.capturing or self.busy:
            return
        if reload_summary:
            self.summary_serial = None
            self.summary_text = ""

        status = self.adb.get_status(preferred=self.preferred_serial)
        self.current_serial = status.serial
        self._serials = list(status.serials)
        if self.preferred_serial and self.preferred_serial not in status.serials:
            self.preferred_serial = status.serial
        self._sync_device_picker(status.serials, status.serial)
        self.reconnect_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

        detail = status.message
        if status.state == "connected" and self.summary_serial == status.serial and self.summary_text:
            detail = self.summary_text
            if len(status.serials) > 1:
                detail += "（可在下方切换）"

        if status.state == "connected":
            self._set_status("#22C55E", "已连接", detail)
            self._set_connected_actions(True)
            if status.serial and self.summary_serial != status.serial and not self._summary_loading:
                self._request_summary(status.serial)
            if not silent:
                self.tip_var.set("手机已连接。可以查看设备、安装 APK、打开开发者选项，或开始采集日志。")
        elif status.state == "unauthorized":
            self._set_status("#F59E0B", "等待手机确认", detail)
            self._set_connected_actions(False)
            if not silent:
                self.tip_var.set("请看手机屏幕，点【允许 USB 调试】。点完后这里会变成绿色“已连接”。")
        elif status.state == "offline":
            self._set_status("#F97316", "连接异常", detail)
            self._set_connected_actions(False)
            if not silent:
                self.tip_var.set("可以点【重连设备】。如果还是不行，拔掉数据线再插上。")
        elif status.state == "error":
            self._set_status("#EF4444", "工具异常", detail)
            self._set_connected_actions(False)
            if "找不到 adb.exe" in status.message:
                self.reconnect_btn.configure(state="disabled")
            if not silent:
                self.tip_var.set(status.message)
        else:
            self._set_status("#EF4444", "未连接", detail)
            self._set_connected_actions(False)
            if not silent:
                self.tip_var.set(
                    "还没检测到手机。请用数据线连接电脑，打开【开发者选项】里的 USB 调试，"
                    "并在弹出提示时点允许。"
                )

    def _on_pick_device(self, _event=None) -> None:
        if self._updating_picker:
            return
        chosen = self.device_pick.get().strip()
        if not chosen or chosen == self.current_serial:
            self.preferred_serial = chosen or self.preferred_serial
            return
        self.preferred_serial = chosen
        self.summary_serial = None
        self.summary_text = ""
        self.refresh_status(silent=True)

    def _require_device(self, title: str) -> str | None:
        if self.capturing or self.busy:
            return None
        self.refresh_status(silent=True)
        if not self.current_serial:
            messagebox.showwarning(title, "请先把手机连上，等到显示“已连接”。")
            return None
        return self.current_serial

    def reconnect_device(self) -> None:
        if self.capturing or self.busy:
            return
        self.busy = True
        self._set_connected_actions(False)
        self.reconnect_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.result_var.set("")
        self.tip_var.set("正在重连设备，请稍等几秒...")

        def worker() -> None:
            try:
                message = self.adb.reconnect()
            except Exception as exc:
                message = f"重连失败：{exc}"
            self.after(0, lambda msg=message: self._on_reconnect_done(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_reconnect_done(self, message: str) -> None:
        self.busy = False
        self.refresh_btn.configure(state="normal")
        self.summary_serial = None
        self.summary_text = ""
        self.refresh_status(silent=True)
        if self.current_serial:
            self.tip_var.set(message if message else "重连完成，当前设备已连接。")
        else:
            self.tip_var.set(message)

    def view_device(self) -> None:
        serial = self._require_device("还不能查看")
        if not serial:
            return
        if self.device_win is not None and self.device_win.winfo_exists():
            self.device_win.lift()
            self.device_win.focus_force()
            return

        win = tk.Toplevel(self)
        self.device_win = win
        win.title("当前设备")
        win.geometry("520x560")
        win.minsize(420, 420)
        win.configure(bg="#FFFFFF")
        win.transient(self)

        heading = tk.Label(
            win,
            text="正在读取设备信息...",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg="#FFFFFF",
            fg="#111827",
            anchor="w",
        )
        heading.pack(fill="x", padx=16, pady=(16, 8))

        box = tk.Text(
            win,
            font=("Microsoft YaHei UI", 11),
            bg="#F9FAFB",
            fg="#111827",
            relief="flat",
            padx=12,
            pady=12,
            wrap="word",
        )
        box.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        box.insert("1.0", "请稍等，正在向手机读取信息。")
        box.configure(state="disabled")

        buttons = tk.Frame(win, bg="#FFFFFF")
        buttons.pack(fill="x", padx=16, pady=(0, 16))
        copy_btn = tk.Button(
            buttons,
            text="复制全部",
            font=("Microsoft YaHei UI", 11),
            bg="#E5E7EB",
            fg="#111827",
            relief="flat",
            padx=14,
            pady=6,
            state="disabled",
            command=lambda: self._copy_device_text(box, copy_btn),
        )
        copy_btn.pack(side="left")
        tk.Button(
            buttons,
            text="关闭",
            font=("Microsoft YaHei UI", 11),
            bg="#E5E7EB",
            fg="#111827",
            relief="flat",
            padx=14,
            pady=6,
            command=win.destroy,
        ).pack(side="right")

        package = self.package

        def worker() -> None:
            try:
                text = self.adb.describe_device(serial, package=package)
            except Exception as exc:
                text = f"读取失败：{exc}"

            def apply() -> None:
                if not win.winfo_exists():
                    return
                heading.configure(text="这是当前手机的信息，可以复制后发给同事")
                box.configure(state="normal")
                box.delete("1.0", "end")
                box.insert("1.0", text)
                box.configure(state="disabled")
                copy_btn.configure(state="normal")

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _copy_device_text(self, box: tk.Text, button: tk.Button) -> None:
        content = box.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)
        self.update()
        button.configure(text="已复制")

    def install_apk(self) -> None:
        serial = self._require_device("还不能安装")
        if not serial:
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="选择要安装的 APK",
            filetypes=[("Android APK", "*.apk"), ("所有文件", "*.*")],
        )
        if not path:
            return
        apk = Path(path)
        self.busy = True
        self._set_connected_actions(False)
        self.reconnect_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.result_var.set("")
        self.tip_var.set(f"正在安装 {apk.name}。如果手机弹出确认，请点允许。")

        def worker() -> None:
            try:
                ok, message = self.adb.install_apk(serial, apk)
            except Exception as exc:
                ok, message = False, f"安装失败：{exc}"
            self.after(0, lambda: self._on_install_done(ok, message, apk.name))

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_done(self, ok: bool, message: str, name: str) -> None:
        self.busy = False
        self.refresh_btn.configure(state="normal")
        self.refresh_status(silent=True)
        self.tip_var.set(message)
        self.result_var.set(name)
        if ok:
            messagebox.showinfo("安装完成", f"{name}\n\n{message}")
        else:
            messagebox.showerror("安装失败", message)

    def uninstall_app(self) -> None:
        serial = self._require_device("还不能卸载")
        if not serial:
            return
        if self.capturing or self.busy:
            return

        self.busy = True
        self._set_connected_actions(False)
        self.reconnect_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.result_var.set("")
        self.tip_var.set("正在读取已安装应用列表...")

        def worker() -> None:
            try:
                apps = self.adb.list_installed_apps(serial, include_system=False)
            except Exception as exc:
                apps = []
                self.after(0, lambda: self._on_uninstall_list_done([], str(exc)))
                return
            self.after(0, lambda: self._on_uninstall_list_done(apps, ""))

        threading.Thread(target=worker, daemon=True).start()

    def _on_uninstall_list_done(self, apps: list, err: str) -> None:
        self.busy = False
        self.reconnect_btn.configure(state="normal")
        self.refresh_btn.configure(state="normal")
        self.refresh_status(silent=True)

        if err:
            self.tip_var.set(f"读取应用列表失败：{err}")
            return

        if not apps:
            self.tip_var.set("没有读取到已安装的第三方应用。")
            messagebox.showinfo("卸载应用", "没有读取到已安装的第三方应用。")
            return

        win = tk.Toplevel(self)
        win.title("卸载应用")
        win.geometry("560x480")
        win.minsize(480, 360)
        win.configure(bg="#FFFFFF")
        win.transient(self)

        tk.Label(
            win,
            text="选择要卸载的应用",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#FFFFFF",
            fg="#111827",
            anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 8))

        search_frame = tk.Frame(win, bg="#FFFFFF")
        search_frame.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(search_frame, text="搜索：", bg="#FFFFFF", font=("Microsoft YaHei UI", 11)).pack(side="left")
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, font=("Microsoft YaHei UI", 11))
        search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

        tree_frame = tk.Frame(win, bg="#FFFFFF")
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        columns = ("app_name", "package_name")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12)
        tree.heading("app_name", text="应用名")
        tree.heading("package_name", text="包名")
        tree.column("app_name", width=200)
        tree.column("package_name", width=300)
        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        all_apps = apps[:]
        for pkg, label, _app_type in apps:
            display = label if label != pkg else pkg
            tree.insert("", "end", values=(display, pkg))

        def filter_apps(*_args) -> None:
            keyword = search_var.get().strip().lower()
            for item in tree.get_children():
                tree.delete(item)
            for pkg, label, _app_type in all_apps:
                display = label if label != pkg else pkg
                if not keyword or keyword in display.lower() or keyword in pkg.lower():
                    tree.insert("", "end", values=(display, pkg))

        search_var.trace_add("write", filter_apps)

        btn_frame = tk.Frame(win, bg="#FFFFFF")
        btn_frame.pack(fill="x", padx=16, pady=(0, 16))

        def do_uninstall() -> None:
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("没有选择", "请先在列表中选择要卸载的应用。")
                return
            item = tree.item(selected[0])
            pkg = item["values"][1]
            display_name = item["values"][0]
            if not messagebox.askyesno("确认卸载", f"确定要卸载 {display_name} 吗？\n\n包名：{pkg}"):
                return
            win.destroy()
            self._do_uninstall(pkg, display_name)

        tk.Button(
            btn_frame,
            text="卸载选中应用",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg="#DC2626",
            fg="white",
            relief="flat",
            padx=14,
            pady=6,
            command=do_uninstall,
        ).pack(side="left")

        tk.Button(
            btn_frame,
            text="关闭",
            font=("Microsoft YaHei UI", 11),
            bg="#E5E7EB",
            fg="#111827",
            relief="flat",
            padx=14,
            pady=6,
            command=win.destroy,
        ).pack(side="right")

    def _do_uninstall(self, package: str, display_name: str) -> None:
        serial = self.current_serial
        if not serial:
            return
        self.busy = True
        self._set_connected_actions(False)
        self.reconnect_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.result_var.set("")
        self.tip_var.set(f"正在卸载 {display_name}...")

        def worker() -> None:
            try:
                ok, message = self.adb.uninstall_app(serial, package)
            except Exception as exc:
                ok, message = False, f"卸载失败：{exc}"
            self.after(0, lambda: self._on_uninstall_done(ok, message, display_name))

        threading.Thread(target=worker, daemon=True).start()

    def _on_uninstall_done(self, ok: bool, message: str, display_name: str) -> None:
        self.busy = False
        self.reconnect_btn.configure(state="normal")
        self.refresh_btn.configure(state="normal")
        self.refresh_status(silent=True)
        self.tip_var.set(message)
        self.result_var.set(display_name)
        if ok:
            messagebox.showinfo("卸载完成", f"{display_name}\n\n{message}")
        else:
            messagebox.showerror("卸载失败", message)

    def open_developer_options(self) -> None:
        serial = self._require_device("还不能打开")
        if not serial:
            return
        self.busy = True
        self._set_connected_actions(False)
        self.reconnect_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.result_var.set("")
        self.tip_var.set("正在打开手机上的开发者选项...")

        def worker() -> None:
            try:
                ok, message = self.adb.open_developer_options(serial)
            except Exception as exc:
                ok, message = False, f"打开失败：{exc}"
            self.after(0, lambda: self._on_developer_done(ok, message))

        threading.Thread(target=worker, daemon=True).start()

    def _on_developer_done(self, ok: bool, message: str) -> None:
        self.busy = False
        self.refresh_btn.configure(state="normal")
        self.refresh_status(silent=True)
        self.tip_var.set(message)
        if not ok:
            messagebox.showwarning("没能打开", message)

    def _enter_capture(self, tip: str, allow_stop: bool) -> None:
        self.capturing = True
        self._set_connected_actions(False)
        self.reconnect_btn.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal" if allow_stop else "disabled")
        self.result_var.set("")
        self.tip_var.set(tip)

    def start_capture(self) -> None:
        if self.capturing or self.busy:
            return
        self.refresh_status(silent=True)
        if not self.current_serial:
            messagebox.showwarning("还不能开始", "请先把手机连上，等到显示“已连接”。")
            return

        self.stop_flag = False
        self._enter_capture("采集已开始。请现在去手机上操作，把崩溃再触发一次。崩溃后点【结束并保存】。", True)
        serial = self.current_serial

        def worker() -> None:
            try:
                result = self.collector.capture(
                    serial=serial,
                    on_progress=lambda msg: self.after(0, lambda m=msg: self.tip_var.set(m)),
                    should_stop=lambda: self.stop_flag,
                )
                self.after(0, lambda: self._on_capture_done(result))
            except Exception as exc:
                self.after(0, lambda: self._on_capture_fail(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def stop_capture(self) -> None:
        if not self.capturing:
            return
        self.stop_flag = True
        self.stop_btn.configure(state="disabled")
        self.tip_var.set("正在结束并保存，请稍等几秒...")

    def dump_existing(self) -> None:
        if self.capturing or self.busy:
            return
        self.refresh_status(silent=True)
        if not self.current_serial:
            messagebox.showwarning("还不能补抓", "请先把手机连上，等到显示“已连接”。")
            return

        self._enter_capture("正在补抓当前日志，请稍等...", False)
        serial = self.current_serial

        def worker() -> None:
            try:
                result = self.collector.dump_existing(
                    serial=serial,
                    on_progress=lambda msg: self.after(0, lambda m=msg: self.tip_var.set(m)),
                )
                self.after(0, lambda: self._on_capture_done(result))
            except Exception as exc:
                self.after(0, lambda: self._on_capture_fail(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_capture_done(self, result) -> None:
        self.capturing = False
        self.stop_flag = False
        self.stop_btn.configure(state="disabled")
        self.refresh_btn.configure(state="normal")
        self.reconnect_btn.configure(state="normal")
        self.refresh_status(silent=True)

        if result.zip_path and result.zip_path.exists():
            self.tip_var.set(result.message)
            self.result_var.set(f"文件位置：{result.zip_path}")
            messagebox.showinfo(
                "采集完成",
                "日志已保存完成。\n\n请把 output-logs 文件夹里最新的 zip 发给开发人员。\n\n"
                f"{result.zip_path}",
            )
        else:
            self.tip_var.set(result.message)
            self.result_var.set(f"文件夹：{result.out_dir}")
            messagebox.showinfo("采集完成", f"请把这个文件夹打包发回：\n{result.out_dir}")

    def _on_capture_fail(self, err: str) -> None:
        self.capturing = False
        self.stop_flag = False
        self.stop_btn.configure(state="disabled")
        self.refresh_btn.configure(state="normal")
        self.reconnect_btn.configure(state="normal")
        self.refresh_status(silent=True)
        self.tip_var.set(f"采集失败：{err}")
        messagebox.showerror("采集失败", err)

    def open_output(self) -> None:
        out_dir = app_root() / "output-logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(out_dir))
        else:
            subprocess.run(["open", str(out_dir)])

    def _on_close(self) -> None:
        if self.capturing or self.busy:
            if not messagebox.askyesno("确认退出", "正在执行操作，确定要退出吗？"):
                return
            self.stop_flag = True
        if self._poll_after_id:
            self.after_cancel(self._poll_after_id)
        self.destroy()


def main() -> None:
    os.chdir(app_root())
    app = CrashLogApp()
    app.mainloop()


if __name__ == "__main__":
    main()
