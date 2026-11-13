import argparse
from dataclasses import fields, replace
import json
import os
from pathlib import Path
import queue
import uuid
import tkinter as tk
from tkinter import messagebox, ttk

from .cases import BY_ID, CASES
from .config import Config, ConfigValidationError, FIELD_LABELS, SECRETS, load_config, load_secrets, save_config
from .worker import Worker
from .timeutil import now
from .logformat import format_events


LABELS = {
    **FIELD_LABELS,
    "funds_symbol": "资金不足专用合约", "position_symbol": "持仓不足专用合约",
    "market_symbol": "市场状态专用合约",
    "funds_error_codes": "资金不足预期码（逗号分隔）",
    "position_error_codes": "持仓不足预期码（逗号分隔）",
    "market_error_codes": "市场状态预期码（逗号分隔）",
}
AUTO_PARAMETER_HELP = {
    "price_offset": "自动委托相对盘口的价位距离。",
    "quote_max_age": "超过此时长的行情不用于下单。",
    "timeout": "等待回报上限；超时不自动重发。",
}
def configure_theme(root):
    style = ttk.Style(root)
    style.theme_use("vista" if "vista" in style.theme_names() else "default")
    style.configure(".", font=("Microsoft YaHei UI", 9))
    style.configure("Treeview", rowheight=24)
    style.configure("Header.TLabel", font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("Section.TLabel", font=("Microsoft YaHei UI", 9, "bold"))


class Settings(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("配置")
        self.transient(app.root)
        self.grab_set()
        self.vars = {}
        self.entries = {}
        self.secrets = {}
        try:
            self.secrets = load_secrets(app.config)
        except Exception:
            pass
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=20, pady=14)
        pages = {}
        for name in ("账号与连接", "测试场景"):
            page = ttk.Frame(self.notebook, padding=(2, 2))
            self.notebook.add(page, text=name)
            page.columnconfigure(1, weight=1)
            pages[name] = page
        account = pages["账号与连接"]
        self.add_fields(account, ["environment", "front_url", "broker_id", "user_id",
                                  "password", "app_id", "auth_code", "token"])
        page = pages["测试场景"]
        self.add_fields(page, ["symbol"])
        ttk.Label(page, text="格式：交易所.合约。普通测试每笔一手，其余参数使用默认值。",
                  wraplength=620).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 16))
        self.advanced_button = ttk.Button(page, text="测试参数…", command=self.toggle_advanced)
        self.advanced_button.grid(row=2, column=0, columnspan=2, sticky="w")
        self.advanced = ttk.Frame(page, padding=(0, 8, 0, 0))
        self.advanced.columnconfigure(1, weight=1)
        self.add_fields(self.advanced, ["price_offset", "quote_max_age", "timeout"])
        # Error tests reuse the main symbol; specialized TOML values remain optional.
        bar = ttk.Frame(self, padding=(20, 12))
        bar.grid(row=2, column=0, sticky="ew")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(bar, text="保存", command=self.save).pack(side="right")
        # Reserve room for either tab, including expanded parameters, once.
        # Tab changes must not override the user's window size or position.
        self.advanced.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.update_idletasks()
        content_height = max(self.nametowidget(tab).winfo_reqheight() for tab in self.notebook.tabs())
        self.advanced.grid_remove()
        self.notebook.configure(height=content_height)
        width = min(640, self.winfo_screenwidth() - 40)
        height = min(max(400, content_height + bar.winfo_reqheight() + 84), self.winfo_screenheight() - 80)
        self.geometry(f"{width}x{height}+{max(0, (self.winfo_screenwidth()-width)//2)}"
                      f"+{max(0, (self.winfo_screenheight()-height)//2-20)}")

    def add_fields(self, page, names):
        row = 0
        for name in names:
            value = self.secrets.get(name, "") if name in SECRETS else getattr(self.app.config, name)
            var = tk.StringVar(value=str(value))
            self.vars[name] = var
            ttk.Label(page, text=LABELS[name], style="TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 16))
            entry = ttk.Entry(page, textvariable=var, show="●" if name in SECRETS else "")
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            self.entries[name] = entry
            row += 1
            if name in AUTO_PARAMETER_HELP:
                ttk.Label(page, text=AUTO_PARAMETER_HELP[name], wraplength=690, style="TLabel").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
                row += 1

    def toggle_advanced(self):
        if self.advanced.winfo_manager():
            self.advanced.grid_remove()
            self.advanced_button.configure(text="测试参数…")
        else:
            self.advanced.grid(row=3, column=0, columnspan=2, sticky="ew")
            self.advanced_button.configure(text="收起测试参数")

    def save(self):
        try:
            config = replace(self.app.config)
            for field in fields(Config):
                if field.name not in self.vars:
                    continue
                value = self.vars[field.name].get().strip()
                if field.type in (int, float):
                    try:
                        value = field.type(value)
                    except ValueError:
                        raise ConfigValidationError(field.name, "必须为整数" if field.type is int else "必须为数字") from None
                setattr(config, field.name, value)
            config.log_dir = str(Path(config.log_dir).expanduser().resolve())
            secrets = {name: self.vars[name].get().strip() for name in SECRETS}
            save_config(self.app.config_path, config, secrets)
        except Exception as error:
            messagebox.showerror("配置未保存", str(error), parent=self)
            if isinstance(error, ConfigValidationError):
                self.focus_field(error.field)
            return
        self.app.apply_saved_config(config)
        self.destroy()

    def focus_field(self, name):
        entry = self.entries.get(name)
        if entry is None:
            return
        if entry.master == self.advanced and not self.advanced.winfo_manager():
            self.toggle_advanced()
        page = entry.master
        tabs = self.notebook.tabs()
        while page != self and str(page) not in tabs:
            page = page.master
        if str(page) in tabs:
            self.notebook.select(page)
        entry.focus_set()
        entry.selection_range(0, "end")


class Application:
    def __init__(self, root, config_path, worker_factory=Worker, autoconnect=True):
        self.root, self.config_path = root, Path(config_path)
        self.worker_factory = worker_factory
        self.session_id = uuid.uuid4().hex
        self.output = queue.Queue()
        self.worker = None
        self.disconnecting = False
        self.config_pending = False
        self.runtime_config_pending = False
        self.config_revision = 0
        self.active_config = None
        self.closing = False
        self.destroyed = False
        self.drain_after = None
        self.setup_after = None
        self.loading_after = None
        self.loading_text = ""
        self.loading_suffix = ""
        self.loading_dots = 1
        self.busy = False
        self.stop_requested = False
        self.available = False
        self.selected = None
        self.active_run = None
        self.running_case = None
        self.history = []
        self.run_cache = {}
        self.event_cache = {}
        self.last_status = {}
        self.runtime_events = []
        self.config_error = None
        try:
            self.config = load_config(self.config_path)
            if not Path(self.config.log_dir).is_absolute():
                self.config.log_dir = str((self.config_path.parent / self.config.log_dir).resolve())
        except Exception as error:
            self.config = Config()
            self.config_error = str(error)
        self.build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self.on_destroy, add="+")
        self.drain_after = root.after(80, self.drain)
        if autoconnect:
            if self.config.credential_ref and not self.config_error:
                self.connect()
            else:
                self.setup_after = root.after(150, self.first_setup)

    def build(self):
        self.root.title("ctptest")
        configure_theme(self.root)
        width = min(1100, self.root.winfo_screenwidth() - 40)
        height = min(680, self.root.winfo_screenheight() - 80)
        self.root.geometry(f"{width}x{height}+10+10")
        self.root.minsize(min(900, width), min(560, height))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left")
        self.settings_button = ttk.Button(toolbar, text="配置", command=self.settings)
        self.settings_button.pack(side="right", padx=(4, 0))
        self.connect_button = ttk.Button(toolbar, text="连接", command=self.toggle_connection)
        self.connect_button.pack(side="right", padx=4)
        self.resume_button = ttk.Button(toolbar, text="恢复交易", command=self.resume_trading)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        left = ttk.Frame(body, padding=4, width=250)
        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(left, weight=0)
        body.add(right, weight=1)
        body.bind("<Map>", lambda _event: body.sashpos(0, 250))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        navigation = ttk.Frame(left)
        navigation.grid(row=0, column=0, sticky="nsew")
        self.tree = ttk.Treeview(navigation, columns=("state",), displaycolumns=(), show="tree", selectmode="browse")
        self.tree.column("#0", width=180, minwidth=140)
        self.tree.column("state", width=90, minwidth=85, stretch=False)
        scroll = ttk.Scrollbar(navigation, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        for case in CASES:
            if not self.tree.exists(case.group):
                self.tree.insert("", "end", iid=case.group, text=case.group.partition(" ")[2], open=True)
            self.tree.insert(case.group, "end", iid=str(case.id), text=case.title, values=("",))
        self.tree.bind("<<TreeviewSelect>>", self.view_selection)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        result = self.result_frame = ttk.Frame(right, padding=8)
        result.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        result.grid_remove()
        result.columnconfigure(0, weight=1)
        heading = ttk.Frame(result)
        heading.grid(row=0, column=0, sticky="ew")
        self.action_button = ttk.Button(heading, text="开始", command=self.toggle_test, state="disabled")
        self.action_button.pack(side="right", padx=(8, 0))
        self.title_var = tk.StringVar(value="")
        title = ttk.Label(heading, textvariable=self.title_var, style="Header.TLabel")
        title.pack(side="left", fill="x", expand=True)
        self.empty_label = ttk.Label(right, text="从左侧选择测试点", anchor="center")
        self.empty_label.grid(row=1, column=0, sticky="nsew")
        records = self.records_frame = ttk.Frame(right, padding=4)
        records.grid(row=1, column=0, sticky="nsew")
        records.grid_remove()
        self.text = tk.Text(records, wrap="word", height=6, font=("Microsoft YaHei UI", 9),
                            relief="flat", borderwidth=0, padx=8, pady=8, state="disabled")
        scrollbar = ttk.Scrollbar(records, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.wrap_labels = [title]
        right.bind("<Configure>", self.resize_content)
        footer = ttk.Frame(self.root, padding=(8, 4))
        footer.grid(row=2, column=0, sticky="ew")
        self.connection_hint = ttk.Frame(footer)
        self.connection_hint.pack(side="left", padx=(0, 16))
        self.connection_hint_var = tk.StringVar(value="")
        ttk.Label(self.connection_hint, textvariable=self.connection_hint_var).pack(side="left")
        self.footer_var = tk.StringVar(value="")
        self.footer_label = ttk.Label(footer, textvariable=self.footer_var, wraplength=1050)
        self.footer_label.pack(side="left", fill="x", expand=True)
        self.update_connection_status()

    def resize_content(self, event):
        width = max(240, event.width - 32)
        for label in self.wrap_labels:
            label.configure(wraplength=width - 160 if label is self.wrap_labels[0] else width)

    def first_setup(self):
        self.setup_after = None
        if self.closing or self.destroyed:
            return
        if self.config_error:
            messagebox.showerror("配置无法读取", self.config_error, parent=self.root)
        self.settings()

    def settings(self):
        if self.busy or self.disconnecting or self.closing or self.destroyed:
            return
        Settings(self)

    def apply_saved_config(self, config):
        self.config = config
        self.config_error = None
        self.config_revision += 1
        self.runtime_config_pending = False
        if self.worker is None:
            self.config_pending = False
            self.available = False
            self.active_config = None
            self.last_status = {}
        else:
            self.config_pending = config.connection_key != self.active_config.connection_key
            if not self.config_pending:
                self.runtime_config_pending = True
                self.worker.commands.put(("configure", {"config": replace(config), "revision": self.config_revision}))
        self.update_connection_status()
        self.buttons()

    def update_connection_status(self):
        profile = self.active_config or self.config
        status = self.last_status.get("connection", "未连接")
        waiting_day = status == "READY" and not self.last_status.get("day")
        connecting = self.worker is not None and not self.closing and (
            self.disconnecting or status in {"CONNECTING", "SYNCING"} or waiting_day)
        hint = {"CONNECTING": "正在连接柜台", "SYNCING": "正在登录并同步"}.get(status, "")
        label = {"CONNECTING": "连接中", "SYNCING": "同步中",
                 "READY": "已连接", "ERROR": "连接异常", "DISCONNECTED": "连接已断开"}.get(status, status)
        if self.disconnecting:
            label, hint = "断开中", "正在断开连接"
        elif waiting_day:
            label, hint = "同步中", "正在同步交易日"
        parts = [profile.environment]
        if profile.user_id:
            parts.append(f"账号 {profile.user_id}")
        if self.last_status.get("day"):
            parts.append(f"交易日 {self.last_status['day']}")
        connection_text = hint if connecting else label
        suffix = ""
        if self.config_pending:
            suffix = " · 连接配置待应用，断开后连接生效"
        elif self.runtime_config_pending:
            suffix = " · 测试参数应用中..."
        elif self.last_status.get("paused"):
            suffix = " · 交易已暂停"
        if connecting:
            if self.loading_text != connection_text:
                self.loading_dots = 1
            self.loading_text, self.loading_suffix = connection_text, suffix
            self.connection_hint_var.set(connection_text + "." * self.loading_dots + suffix)
            if self.loading_after is None:
                self.loading_after = self.root.after(400, self.animate_loading)
        else:
            self.cancel_callback("loading_after")
            self.loading_text = ""
            self.loading_suffix = ""
            self.connection_hint_var.set(connection_text + suffix)
        self.status_var.set("    ".join(parts))

    def animate_loading(self):
        self.loading_after = None
        if self.closing or self.destroyed or not self.loading_text:
            return
        self.loading_dots = self.loading_dots % 3 + 1
        self.connection_hint_var.set(self.loading_text + "." * self.loading_dots + self.loading_suffix)
        self.loading_after = self.root.after(400, self.animate_loading)

    def ready_for_tests(self):
        return (self.worker is not None and self.available and not self.disconnecting
                and not self.config_pending and not self.runtime_config_pending
                and not self.closing and not self.destroyed
                and self.last_status.get("connection") == "READY" and bool(self.last_status.get("day")))

    def toggle_connection(self):
        if self.busy or self.disconnecting or self.closing or self.destroyed:
            return
        if self.worker is not None:
            self.disconnecting = True
            self.available = False
            self.update_connection_status()
            self.buttons()
            self.worker.close()
        else:
            self.connect()

    def connect(self):
        if self.worker is not None or self.busy or self.disconnecting or self.closing or self.destroyed:
            return
        try:
            self.config.validate()
            if not self.config.credential_ref:
                raise ValueError("请先配置并保存账号信息")
        except ValueError as error:
            self.log_runtime_error(str(error))
            return
        self.available = False
        self.busy = False
        self.stop_requested = False
        self.last_status = {"connection": "CONNECTING"}
        self.footer_var.set("")
        self.history.clear()
        self.run_cache.clear()
        self.event_cache.clear()
        self.runtime_events.clear()
        self.viewing_run = None
        self.active_run = None
        self.running_case = None
        self.replace_text("")
        for case in CASES:
            self.tree.set(str(case.id), "state", "")
            self.tree.item(str(case.id), tags=())
        self.tree.configure(displaycolumns=())
        self.buttons()
        self.start_worker()

    def start_worker(self):
        self.active_config = replace(self.config)
        self.config_pending = False
        self.runtime_config_pending = False
        self.worker = self.worker_factory(self.active_config, self.output, session_id=self.session_id)
        self.worker.start()
        self.update_connection_status()
        self.buttons()

    def view_selection(self, _event=None):
        selected = self.tree.selection()
        if selected and selected[0].isdigit():
            self.select(int(selected[0]))

    def select(self, case_id):
        self.selected = case_id
        self.result_frame.grid()
        case = BY_ID[case_id]
        self.title_var.set(f"{case.title}：{case.purpose}")
        runs = [r for r in self.history if r["case_id"] == case_id]
        if self.busy and self.running_case == case_id:
            if self.active_run and self.run_cache.get(self.active_run, {}).get("case_id") == case_id:
                self.show_run(self.run_cache[self.active_run])
            else:
                self.viewing_run = None
                self.replace_text("")
        elif runs:
            self.show_run(runs[0])
        else:
            self.viewing_run = None
            self.replace_text("")
        self.buttons()

    def start_case(self, case_id):
        if self.busy or not self.ready_for_tests():
            return
        self.busy = True
        self.running_case = case_id
        self.stop_requested = False
        self.worker.stop_test.clear()
        self.viewing_run = None
        self.replace_text("")
        self.footer_var.set("")
        self.worker.commands.put(("run", case_id))
        self.buttons()

    def toggle_test(self):
        if self.busy:
            if self.selected == self.running_case:
                self.stop()
        elif self.selected is not None:
            self.start_case(self.selected)

    def stop(self):
        if self.worker and self.busy and self.selected == self.running_case and not self.stop_requested:
            self.stop_requested = True
            self.worker.stop_test.set()
            self.footer_var.set("停止已请求；不再发送后续步骤，仍跟踪已发委托并清理本次可撤辅助单。")
            self.buttons()

    def resume_trading(self):
        if self.ready_for_tests() and not self.busy:
            self.worker.commands.put(("resume", None))
            self.footer_var.set("已请求恢复交易入口；不会重发旧请求。")

    def buttons(self):
        selected_running = self.busy and self.running_case is not None and self.selected == self.running_case
        self.action_button.configure(text="停止" if selected_running else "开始",
            state="normal" if (selected_running and not self.stop_requested) or (
                not self.busy and self.ready_for_tests() and self.selected is not None) else "disabled")
        self.settings_button.configure(state="disabled" if self.busy or self.disconnecting else "normal")
        self.connect_button.configure(text="断开" if self.worker is not None else "连接",
            state="disabled" if self.busy or self.disconnecting or self.closing else "normal")
        self.resume_button.configure(state="normal" if self.ready_for_tests() and not self.busy else "disabled")

    def show_run(self, run):
        self.result_frame.grid()
        self.viewing_run = run["id"]
        case = BY_ID[run["case_id"]]
        self.title_var.set(f"{case.title}：{case.purpose}")
        self.run_cache[run["id"]] = run
        self.render_events(run["id"])
        if self.worker and run["id"] != self.active_run:
            self.worker.commands.put(("view", run["id"]))

    def replace_text(self, value):
        if self.selected is not None or value:
            self.empty_label.grid_remove()
            self.records_frame.grid()
        else:
            self.records_frame.grid_remove()
            self.empty_label.grid()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", value)
        self.text.configure(state="disabled")

    def log_runtime_error(self, message):
        run_id = getattr(self, "viewing_run", None)
        event = {"at": now(), "run_id": run_id, "kind": "runtime_error", "category": "error",
                 "payload": {"message": message}}
        if run_id:
            self.event_cache.setdefault(run_id, []).append(event)
            self.render_events(run_id)
        else:
            self.runtime_events.append(event)
            self.replace_text(format_events(self.runtime_events))

    def render_events(self, run_id):
        events = list(self.event_cache.get(run_id, []))
        run = self.run_cache.get(run_id)
        if run and run.get("status") != "执行中" and not any(e["kind"] == "test_result" for e in events):
            events.append({"at": run.get("ended") or "", "run_id": run_id,
                           "kind": "test_result", "payload": {"status": run["status"],
                                                               "summary": run.get("summary") or ""}})
        self.replace_text(format_events(events))
        if run_id == self.active_run:
            self.text.see("end")

    def drain(self):
        self.drain_after = None
        if self.destroyed:
            return
        try:
            while not self.destroyed:
                kind, value = self.output.get_nowait()
                self.handle(kind, value)
        except queue.Empty:
            pass
        if not self.destroyed:
            self.drain_after = self.root.after(80, self.drain)

    def cancel_callback(self, name):
        callback = getattr(self, name)
        setattr(self, name, None)
        if callback is not None:
            try:
                self.root.after_cancel(callback)
            except tk.TclError:
                # The interpreter may already be shutting down on external destroy.
                pass

    def on_destroy(self, event):
        if event.widget is not self.root:
            return
        self.destroyed = True
        self.cancel_callback("drain_after")
        self.cancel_callback("setup_after")
        self.cancel_callback("loading_after")
        if self.worker and self.worker.is_alive():
            self.worker.close()

    def destroy_window(self):
        if self.destroyed:
            return
        self.destroyed = True
        self.cancel_callback("drain_after")
        self.cancel_callback("setup_after")
        self.cancel_callback("loading_after")
        self.root.destroy()

    def handle(self, kind, value):
        if self.destroyed:
            return
        if kind == "available":
            # The worker can process commands; login and synchronization may still be pending.
            self.available = not self.disconnecting and not self.closing
            self.update_connection_status()
        elif kind in ("config_applied", "config_error"):
            if value["revision"] != self.config_revision:
                return
            self.runtime_config_pending = False
            if kind == "config_applied":
                self.active_config = replace(self.config)
            else:
                self.config_pending = True
                self.log_runtime_error("测试参数应用失败：" + value["message"])
            self.update_connection_status()
        elif kind == "fault":
            self.available = False
            self.last_status["connection"] = "ERROR"
            self.update_connection_status()
            self.log_runtime_error(value["message"])
        elif kind == "connection_error":
            self.available = False
            self.last_status["connection"] = "ERROR"
            self.update_connection_status()
            self.log_runtime_error(value["message"])
        elif kind == "status":
            self.last_status = value
            if value["paused"]:
                self.resume_button.pack(side="right", padx=6)
            else:
                self.resume_button.pack_forget()
            self.update_connection_status()
        elif kind == "history":
            self.history = value
            self.tree.configure(displaycolumns=("state",) if value else ())
            for run in reversed(value):
                self.run_cache[run["id"]] = run
                self.tree.set(str(run["case_id"]), "state", run["status"])
                self.tree.item(str(run["case_id"]), tags=(run["status"],))
            if self.selected is not None:
                self.select(self.selected)
        elif kind == "run_started":
            self.tree.configure(displaycolumns=("state",))
            run_id = value["run_id"]
            self.busy = True
            self.running_case = value["case_id"]
            self.active_run = run_id
            self.run_cache[run_id] = dict(id=run_id, case_id=value["case_id"], status="执行中", summary="")
            self.event_cache[run_id] = []
            self.tree.set(str(value["case_id"]), "state", "执行中")
            self.tree.item(str(value["case_id"]), tags=("执行中",))
            if self.selected == value["case_id"]:
                self.show_run(self.run_cache[run_id])
        elif kind in ("event", "evidence"):
            run_id = self.active_run if kind == "evidence" else value.get("run_id")
            if run_id:
                self.event_cache.setdefault(run_id, []).append(value)
                if getattr(self, "viewing_run", None) == run_id:
                    self.render_events(run_id)
        elif kind == "run_finished":
            run_id = value["run_id"]
            run = self.run_cache.get(run_id, {}) | value | {"id": run_id, "ended": now()}
            self.run_cache[run_id] = run
            self.tree.set(str(value["case_id"]), "state", value["status"])
            self.tree.item(str(value["case_id"]), tags=(value["status"],))
            self.busy = False
            self.stop_requested = False
            self.active_run = None
            self.running_case = None
            if self.selected == value["case_id"]:
                self.show_run(run)
        elif kind == "view":
            self.event_cache[value["run_id"]] = value["events"]
            if getattr(self, "viewing_run", None) == value["run_id"]:
                self.render_events(value["run_id"])
        elif kind == "closed":
            self.worker = None
            self.disconnecting = False
            self.available = False
            self.busy = False
            self.stop_requested = False
            self.running_case = None
            if self.closing:
                self.destroy_window()
                return
            self.active_config = None
            self.config_pending = False
            self.runtime_config_pending = False
            self.last_status = {}
            self.resume_button.pack_forget()
            self.update_connection_status()
        self.buttons()

    def close(self):
        if self.closing or self.destroyed:
            return
        resources = self.last_status.get("resources", {})
        if self.busy or any(resources.values()):
            detail = json.dumps(resources, ensure_ascii=False)
            if not messagebox.askyesno("退出前核对", "退出不会自动平仓或撤销全部委托。\n"
                    + detail + "\n确定停止并退出？", parent=self.root):
                return
        self.closing = True
        self.available = False
        self.cancel_callback("setup_after")
        self.cancel_callback("loading_after")
        if self.worker and self.worker.is_alive():
            self.footer_var.set("正在停止测试并释放连接，请等待…")
            self.worker.close()
        else:
            self.destroy_window()


def main():
    parser = argparse.ArgumentParser(description="CTP 图形测试验收工具")
    default = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ctptest" / "config.toml"
    parser.add_argument("--config", type=Path, default=default, help="非敏感 TOML 配置路径")
    args = parser.parse_args()
    root = tk.Tk()
    Application(root, args.config)
    root.mainloop()


if __name__ == "__main__":
    main()
