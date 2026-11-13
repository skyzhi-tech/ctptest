import argparse
from dataclasses import fields, replace
import json
import os
from pathlib import Path
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from .cases import BY_ID, CASES
from .config import Config, ConfigValidationError, FIELD_LABELS, SECRETS, load_config, load_secrets, save_config
from .worker import Worker


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
COLORS = {"通过": "#08734b", "未通过": "#ba303b", "待环境准备": "#996500",
          "结果待核对": "#996500", "SDK 限制": "#8452a0", "已停止": "#64748b", "执行中": "#1764a4"}
KINDS = {"request_intent": "委托参数", "submission_result": "SDK即时结果", "order": "柜台委托回报",
         "trade": "真实成交回报",
         "counter_error": "柜台原始错误", "order_error": "委托错误原文（status_msg）",
         "counter_message_verified": "柜台错误信息验证", "counter_error_verified": "柜台错误码及信息验证",
         "sdk_order_error": "委托错误（历史记录）", "local_reject": "本地拒绝（未发送）",
         "sdk_reject": "SDK本地拒绝（TradingResult.message）",
         "statistics": "笔数统计", "warning": "阈值预警", "threshold_set": "阈值配置",
         "test_start": "测试说明", "test_result": "测试结论", "connection": "连接状态变化",
         "cancel_intent": "撤单参数", "cleanup": "辅助委托清理", "sdk_limitation": "SDK能力缺口",
         "pricing": "委托定价依据", "log_search": "日志检索", "pause": "暂停", "resume": "恢复",
         "pause_verified": "暂停拦截证据", "validation_verified": "本地检查证据"}

PAGE = "#ffffff"
SURFACE = "#ffffff"
INK = "#182d46"
MUTED = "#708198"
BLUE = "#2563eb"


def configure_theme(root):
    root.configure(background=PAGE)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei UI", 10), background=PAGE, foreground=INK)
    style.configure("TFrame", background=PAGE)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Card.TFrame", background=SURFACE, borderwidth=0, relief="flat")
    style.configure("TLabel", background=PAGE, foreground=INK)
    style.configure("Surface.TLabel", background=SURFACE)
    style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=("Microsoft YaHei UI", 9))
    style.configure("Section.TLabel", background=SURFACE, foreground=INK, font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("Header.TLabel", background=SURFACE, font=("Microsoft YaHei UI", 16, "bold"))
    style.configure("TButton", padding=(14, 8), background=SURFACE, foreground=INK,
                    bordercolor="#d7e0ec", relief="flat", focuscolor="#9ab7f6")
    style.map("TButton", background=[("active", "#edf3ff"), ("disabled", "#f1f4f8")],
              foreground=[("disabled", "#9aa8b9")])
    style.configure("Primary.TButton", background=BLUE, foreground="white", bordercolor=BLUE)
    style.map("Primary.TButton", background=[("disabled", "#dce5f6"), ("active", "#1d4ed8")],
              foreground=[("disabled", "#8b9db9"), ("!disabled", "white")])
    style.configure("Danger.TButton", foreground="#ba303b")
    style.configure("Header.TButton", background=SURFACE, foreground=INK, bordercolor="#d7e0ec")
    style.map("Header.TButton", background=[("active", "#f3f5f8"), ("disabled", "#f8f9fb")],
              foreground=[("disabled", "#9aa8b9"), ("!disabled", INK)])
    style.configure("TEntry", padding=(9, 7), fieldbackground=SURFACE, bordercolor="#d7e0ec", lightcolor=SURFACE)
    style.map("TEntry", bordercolor=[("focus", BLUE)])
    style.configure("TCombobox", padding=(8, 6), fieldbackground=SURFACE, background=SURFACE,
                    bordercolor="#d7e0ec", arrowsize=13)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)], selectbackground=[("readonly", SURFACE)],
              selectforeground=[("readonly", INK)])
    style.configure("TNotebook", background=PAGE, borderwidth=0, tabmargins=(0, 0, 0, 10))
    style.configure("TNotebook.Tab", padding=(20, 10), background=PAGE, foreground=MUTED, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", BLUE)])
    style.configure("Treeview", rowheight=30, background=SURFACE, fieldbackground=SURFACE,
                    borderwidth=0, foreground=INK, indent=12)
    style.map("Treeview", background=[("selected", "#eaf1ff")], foreground=[("selected", "#1d4ed8")])
    style.configure("Treeview.Heading", background="#f7f9fc", foreground=MUTED,
                    font=("Microsoft YaHei UI", 9), padding=(8, 8), relief="flat")
    style.configure("Vertical.TScrollbar", arrowsize=10, background="#d6dfeb", troughcolor=PAGE, borderwidth=0)
    style.configure("TPanedwindow", background=PAGE)


def section(parent, title):
    frame = ttk.Frame(parent, style="Surface.TFrame", padding=(8, 6))
    if title:
        ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 8))
    content = ttk.Frame(frame, style="Surface.TFrame")
    content.columnconfigure(1, weight=1)
    content.pack(fill="both", expand=True)
    return frame, content


class Settings(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("首次配置 / 测试环境设置")
        self.configure(background=PAGE)
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
        header = ttk.Frame(self, style="Surface.TFrame", padding=(24, 16))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="连接设置", style="Header.TLabel").pack(anchor="w")
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=20, pady=14)
        pages = {}
        for name in ("账号与连接", "测试场景"):
            page = ttk.Frame(self.notebook, padding=(2, 2))
            self.notebook.add(page, text=name)
            page.columnconfigure(1, weight=1)
            pages[name] = page
        account = pages["账号与连接"]
        account.columnconfigure(0, weight=1, uniform="account")
        account.columnconfigure(1, weight=1, uniform="account")
        connection_card, connection = section(account, "连接")
        connection_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.add_fields(connection, ["environment", "front_url", "broker_id"])
        credentials_card, credentials = section(account, "账号")
        credentials_card.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=(0, 10))
        self.add_fields(credentials, ["user_id", "password"])
        auth_card, auth = section(account, "认证")
        auth_card.grid(row=1, column=1, sticky="nsew", padx=(5, 0), pady=(0, 10))
        self.add_fields(auth, ["app_id", "auth_code"])
        sdk_card, sdk = section(account, None)
        sdk_card.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.add_fields(sdk, ["token"])
        page = pages["测试场景"]
        contract_card, contract = section(page, None)
        contract_card.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.add_fields(contract, ["symbol"])
        ttk.Label(page, text="格式：交易所.合约。普通测试每笔一手，其余参数使用默认值。",
                  wraplength=620).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 16))
        self.advanced_button = ttk.Button(page, text="自动测试参数（通常无需修改） ▸", command=self.toggle_advanced)
        self.advanced_button.grid(row=2, column=0, columnspan=2, sticky="w")
        self.advanced = ttk.Frame(page, style="Card.TFrame", padding=16)
        self.advanced.columnconfigure(1, weight=1)
        self.add_fields(self.advanced, ["price_offset", "quote_max_age", "timeout"])
        # Error tests reuse the main symbol; specialized TOML values remain optional.
        bar = ttk.Frame(self, style="Surface.TFrame", padding=(20, 12))
        bar.grid(row=2, column=0, sticky="ew")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(bar, text="保存并连接", style="Primary.TButton", command=self.save).pack(side="right")
        self.update_idletasks()
        width = min(760, self.winfo_screenwidth() - 40)
        self._window_width = width
        self._header = header
        self._bar = bar
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self.fit_height())
        self.fit_height()

    def fit_height(self):
        self.update_idletasks()
        page = self.nametowidget(self.notebook.select())
        content_height = page.winfo_reqheight()
        self.notebook.configure(height=content_height)
        height = min(max(400, content_height + self._header.winfo_reqheight()
                         + self._bar.winfo_reqheight() + 84), self.winfo_screenheight() - 80)
        width = self._window_width
        self.geometry(f"{width}x{height}+{max(0, (self.winfo_screenwidth()-width)//2)}"
                      f"+{max(0, (self.winfo_screenheight()-height)//2-20)}")

    def add_fields(self, page, names):
        row = 0
        for name in names:
            value = self.secrets.get(name, "") if name in SECRETS else getattr(self.app.config, name)
            var = tk.StringVar(value=str(value))
            self.vars[name] = var
            ttk.Label(page, text=LABELS[name], style="Surface.TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 16))
            entry = ttk.Entry(page, textvariable=var, show="●" if name in SECRETS else "")
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            self.entries[name] = entry
            row += 1
            if name in AUTO_PARAMETER_HELP:
                ttk.Label(page, text=AUTO_PARAMETER_HELP[name], wraplength=690, style="Muted.TLabel").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
                row += 1

    def toggle_advanced(self):
        if self.advanced.winfo_manager():
            self.advanced.grid_remove()
            self.advanced_button.configure(text="自动测试参数（通常无需修改） ▸")
        else:
            self.advanced.grid(row=3, column=0, columnspan=2, sticky="ew")
            self.advanced_button.configure(text="自动测试参数（通常无需修改） ▾")
        self.fit_height()

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
        self.app.config = config
        self.destroy()
        self.app.reconnect()

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
        self.output = queue.Queue()
        self.worker = None
        self.pending_reconnect = False
        self.closing = False
        self.busy = False
        self.available = False
        self.selected = None
        self.active_run = None
        self.history = []
        self.run_cache = {}
        self.event_cache = {}
        self.last_status = {}
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
        root.after(80, self.drain)
        if autoconnect:
            if self.config.credential_ref and not self.config_error:
                self.reconnect()
            else:
                root.after(150, self.first_setup)

    def build(self):
        self.root.title("ctptest · CTP 测试验收")
        configure_theme(self.root)
        width = min(1200, self.root.winfo_screenwidth() - 40)
        height = min(720, self.root.winfo_screenheight() - 80)
        self.root.geometry(f"{width}x{height}+10+10")
        self.root.minsize(min(1060, width), min(650, height))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = tk.Frame(self.root, bg=SURFACE, padx=22, pady=10)
        header.grid(row=0, column=0, sticky="ew")
        brand = tk.Frame(header, bg=SURFACE)
        brand.pack(side="left")
        tk.Label(brand, text="ctptest", bg=SURFACE, fg=INK,
                 font=("Segoe UI", 18, "bold")).pack(side="left")
        self.settings_button = ttk.Button(header, text="连接设置", style="Header.TButton", command=self.settings)
        self.settings_button.pack(side="right")
        self.stop_button = ttk.Button(header, text="停止测试", style="Header.TButton", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=10)
        self.resume_button = ttk.Button(header, text="恢复交易", style="Header.TButton", command=self.resume_trading)

        connection = ttk.Frame(self.root, style="Surface.TFrame", padding=(22, 4))
        connection.grid(row=1, column=0, sticky="ew")
        self.connection_dot = tk.Label(connection, text="●", bg=SURFACE, fg="#a0aec0", font=("Segoe UI", 11))
        self.connection_dot.pack(side="left", padx=(0, 8))
        self.status_var = tk.StringVar(value="尚未连接   ·   请在连接设置中配置测试环境")
        ttk.Label(connection, textvariable=self.status_var, style="Surface.TLabel").pack(side="left")

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=10)
        left = ttk.Frame(body, style="Card.TFrame", padding=(10, 14, 6, 10), width=310)
        right = ttk.Frame(body, padding=(16, 0, 0, 0))
        body.add(left, weight=0)
        body.add(right, weight=1)
        body.bind("<Map>", lambda _event: body.sashpos(0, 310))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        ttk.Label(left, text="测试目录", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=6)
        ttk.Label(left, text="首次选择执行，已有结果只查看", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", padx=6, pady=(5, 12))
        navigation = ttk.Frame(left, style="Surface.TFrame")
        navigation.grid(row=2, column=0, sticky="nsew")
        self.tree = ttk.Treeview(navigation, columns=("state",), show="tree headings", selectmode="browse", height=16)
        self.tree.heading("#0", text="测试点")
        self.tree.heading("state", text="结果")
        self.tree.column("#0", width=190, minwidth=150)
        self.tree.column("state", width=90, minwidth=85, stretch=False)
        self.tree.tag_configure("group", foreground=MUTED, font=("Microsoft YaHei UI", 9, "bold"))
        for status, color in COLORS.items():
            self.tree.tag_configure(status, foreground=color)
        scroll = ttk.Scrollbar(navigation, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        for case in CASES:
            if not self.tree.exists(case.group):
                self.tree.insert("", "end", iid=case.group, text=case.group.partition(" ")[2], open=True, tags=("group",))
            self.tree.insert(case.group, "end", iid=str(case.id), text=f"{case.id:02d}  {case.title}", values=("未执行",))
        self.tree.bind("<ButtonRelease-1>", self.click)
        self.tree.bind("<<TreeviewSelect>>", self.view_selection)
        self.progress_var = tk.StringVar(value=f"{len(CASES)} 个测试点 · 已通过 0 项")
        ttk.Label(left, textvariable=self.progress_var, style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", padx=6, pady=(12, 0))

        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self.wrap_labels = []
        result = ttk.Frame(right, style="Surface.TFrame", padding=(10, 6))
        result.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        heading = ttk.Frame(result, style="Surface.TFrame")
        heading.pack(fill="x")
        self.result_label = tk.Label(heading, text="待选择", font=("Microsoft YaHei UI", 11, "bold"),
                                    bg=SURFACE, fg=MUTED, padx=8, pady=4)
        self.result_label.pack(side="right", padx=(10, 0))
        self.title_var = tk.StringVar(value="选择测试点")
        title = ttk.Label(heading, textvariable=self.title_var, style="Header.TLabel")
        title.pack(side="left", fill="x", expand=True)
        self.meta = tk.StringVar(value="选择后自动执行，完成后截图留存。")
        meta_label = ttk.Label(result, textvariable=self.meta, style="Muted.TLabel", justify="left", wraplength=800)
        meta_label.pack(anchor="w", fill="x", pady=(10, 6))
        self.summary = tk.StringVar(value="")
        summary_label = ttk.Label(result, textvariable=self.summary, style="Surface.TLabel", wraplength=800, justify="left")
        summary_label.pack(anchor="w", fill="x", pady=(0, 12))
        toolbar = ttk.Frame(result, style="Surface.TFrame")
        toolbar.pack(fill="x")
        self.rerun_button = ttk.Button(toolbar, text="重新测试", style="Primary.TButton", command=self.rerun, state="disabled")
        self.rerun_button.pack(side="right", padx=(12, 0))
        ttk.Label(toolbar, text="历史运行", style="Muted.TLabel").pack(side="left", padx=(0, 10))
        self.history_combo = ttk.Combobox(toolbar, state="readonly", width=30)
        self.history_combo.pack(side="left", fill="x", expand=True)
        self.history_combo.bind("<<ComboboxSelected>>", self.choose_history)

        metrics_card = ttk.Frame(right, style="Surface.TFrame", padding=(10, 2))
        metrics_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.metrics = tk.StringVar(value="当前账户统计    报单 —    撤单 —    阈值 —")
        metric_label = ttk.Label(metrics_card, textvariable=self.metrics, style="Surface.TLabel", wraplength=800)
        metric_label.pack(fill="x")
        evidence_card = ttk.Frame(right, style="Surface.TFrame", padding=(10, 6))
        evidence_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(evidence_card, text="关键证据", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.evidence_var = tk.StringVar(value="执行后展示下单参数、委托回报、错误原因及监测结果。")
        evidence_label = ttk.Label(evidence_card, textvariable=self.evidence_var, style="Surface.TLabel",
                                   justify="left", wraplength=800)
        evidence_label.pack(fill="x")
        records = ttk.Frame(right, style="Surface.TFrame", padding=(10, 6))
        records.grid(row=3, column=0, sticky="nsew")
        records.rowconfigure(1, weight=1)
        records.columnconfigure(0, weight=1)
        record_heading = ttk.Frame(records, style="Surface.TFrame")
        record_heading.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(record_heading, text="执行记录", style="Section.TLabel").pack(side="left")
        detail = ttk.Frame(records, style="Surface.TFrame")
        detail.grid(row=1, column=0, sticky="nsew")
        self.text = tk.Text(detail, wrap="word", height=5, font=("Microsoft YaHei UI", 9), bg=SURFACE,
                            fg="#475b73", relief="flat", padx=4, pady=4, borderwidth=0,
                            selectbackground="#dce9ff", state="disabled", spacing3=3)
        scrollbar = ttk.Scrollbar(detail, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.wrap_labels = [title, meta_label, summary_label, metric_label, evidence_label]
        right.bind("<Configure>", self.resize_content)
        self.footer_var = tk.StringVar(value="就绪后选择测试点即可执行。已有结果只查看，不会重复发单。")
        ttk.Label(self.root, textvariable=self.footer_var, padding=(22, 8), foreground=MUTED, wraplength=1200).grid(
            row=3, column=0, sticky="ew")

    def resize_content(self, event):
        width = max(240, event.width - 56)
        for label in self.wrap_labels:
            label.configure(wraplength=width - 110 if label is self.wrap_labels[0] else width)

    def set_result(self, status):
        color = COLORS.get(status, MUTED)
        self.result_label.configure(text=status, fg=color, bg=SURFACE)

    def first_setup(self):
        if self.config_error:
            messagebox.showerror("配置无法读取", self.config_error, parent=self.root)
        self.settings()

    def settings(self):
        if self.busy:
            return
        Settings(self)

    def reconnect(self):
        self.available = False
        self.busy = False
        self.status_var.set("正在连接测试柜台…")
        self.connection_dot.configure(fg="#d69a24")
        self.history.clear()
        self.run_cache.clear()
        self.event_cache.clear()
        self.selected = None
        self.active_run = None
        for case in CASES:
            self.tree.set(str(case.id), "state", "未执行")
            self.tree.item(str(case.id), tags=())
        self.progress_var.set(f"{len(CASES)} 个测试点 · 已通过 0 项")
        self.buttons()
        if self.worker and self.worker.is_alive():
            self.pending_reconnect = True
            self.worker.close()
        else:
            self.start_worker()

    def start_worker(self):
        self.pending_reconnect = False
        self.worker = self.worker_factory(self.config, self.output)
        self.worker.start()

    def click(self, event):
        item = self.tree.identify_row(event.y)
        if item.isdigit():
            self.root.after_idle(lambda: self.select(int(item), execute=True))

    def view_selection(self, _event=None):
        selected = self.tree.selection()
        if selected and selected[0].isdigit():
            self.select(int(selected[0]), execute=False)

    def select(self, case_id, execute=False):
        self.selected = case_id
        case = BY_ID[case_id]
        self.title_var.set(f"{case.id:02d}  {case.title}")
        runs = [r for r in self.history if r["case_id"] == case_id]
        self.history_combo["values"] = [f"{r['started']}  {r['status']}  {r['id']}" for r in runs]
        if runs:
            self.history_combo.current(0)
            self.show_run(runs[0])
        elif self.active_run and self.run_cache.get(self.active_run, {}).get("case_id") == case_id:
            self.show_run(self.run_cache[self.active_run])
        else:
            self.set_result("待执行")
            self.meta.set(f"目的：{case.purpose}\n前置条件：{case.prerequisite}")
            self.summary.set("选择后将自动执行本项测试所需的操作。")
            if self.busy:
                self.summary.set("另一测试正在执行；当前只预览本项说明，不会启动新的交易。")
            self.replace_text("")
            self.evidence_var.set("尚无本次测试证据")
            if execute and not self.busy and self.available:
                self.start_case(case_id)
        self.buttons()

    def start_case(self, case_id):
        if self.busy or not self.available:
            return
        self.busy = True
        self.worker.stop_test.clear()
        self.set_result("执行中")
        self.summary.set("正在检查前置条件并自动执行，请等待真实回报。")
        self.viewing_run = None
        self.replace_text("")
        self.worker.commands.put(("run", case_id))
        self.buttons()

    def rerun(self):
        if self.selected is not None:
            self.start_case(self.selected)

    def stop(self):
        if self.worker:
            self.worker.stop_test.set()
            self.footer_var.set("停止已请求；不再发送后续步骤，仍跟踪已发委托并清理本次可撤辅助单。")

    def resume_trading(self):
        if self.worker and self.available and not self.busy:
            self.worker.commands.put(("resume", None))
            self.footer_var.set("已请求恢复交易入口；不会重发旧请求。")

    def buttons(self):
        self.stop_button.configure(state="normal" if self.busy else "disabled")
        self.settings_button.configure(state="disabled" if self.busy or self.pending_reconnect else "normal")
        self.rerun_button.configure(state="normal" if self.available and not self.busy and self.selected is not None else "disabled")
        self.resume_button.configure(state="normal" if self.available and not self.busy else "disabled")

    def choose_history(self, _event=None):
        runs = [r for r in self.history if r["case_id"] == self.selected]
        index = self.history_combo.current()
        if 0 <= index < len(runs):
            self.show_run(runs[index])

    def show_run(self, run):
        self.viewing_run = run["id"]
        self.set_result(run["status"])
        case = BY_ID[run["case_id"]]
        self.meta.set(f"运行 {run['id']}   开始 {run.get('started', '刚刚')}   交易日 {run.get('day') or '—'}\n"
                      f"目的：{case.purpose}；条件：{case.prerequisite}")
        self.summary.set(run.get("summary") or "正在执行，等待真实回报…")
        self.render_events(run["id"])
        if self.worker and run["id"] != self.active_run:
            self.worker.commands.put(("view", run["id"]))

    def replace_text(self, value):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", value)
        self.text.configure(state="disabled")

    def render_events(self, run_id):
        lines = []
        key_evidence = {}
        for event in self.event_cache.get(run_id, []):
            payload = event["payload"]
            lines.append(f"{event.get('at', '')}  [{KINDS.get(event['kind'], event['kind'])}]\n"
                         + json.dumps(payload, ensure_ascii=False, default=str))
            kind = event["kind"]
            if kind == "request_intent":
                key_evidence["参数"] = (f"{payload.get('symbol')}  {payload.get('direction')} / {payload.get('offset')}  "
                    f"价格 {payload.get('limit_price')}  手数 {payload.get('volume')}")
            elif kind == "cancel_intent":
                key_evidence["操作"] = "撤单 " + str(payload.get("order_id"))
            elif kind == "order":
                key_evidence["回报"] = (f"委托 {payload.get('order_id')}  状态 {payload.get('status')}  "
                    f"成交 {payload.get('volume_traded')} / {payload.get('volume_original')}  {payload.get('status_msg') or ''}")
            elif kind in ("local_reject", "validation_verified"):
                key_evidence["检查"] = str(payload.get("message")) + "（未发送柜台）"
            elif kind == "sdk_reject":
                key_evidence["SDK本地拒绝"] = "TradingResult.message：" + str(payload.get("message") or "（空）")
            elif kind == "counter_error":
                key_evidence["柜台错误"] = f"原始码 {payload.get('error_code')}  {payload.get('error_message')}"
            elif kind in ("order_error", "sdk_order_error"):
                key_evidence["status_msg"] = str(payload.get("status_msg") or "（空）")
                if payload.get("cancel_error"):
                    key_evidence["cancel_error"] = str(payload["cancel_error"])
            elif kind == "trade":
                key_evidence["成交"] = (f"成交号 {payload.get('trade_id')}  实际价格 {payload.get('price')}  "
                    f"手数 {payload.get('volume')}")
            elif kind == "statistics":
                key_evidence[payload.get("metric", "统计")] = (f"计数 {payload.get('count')} / 阈值 {payload.get('threshold')}  "
                    + ("已触发预警" if payload.get("warning") else "未触发预警"))
            elif kind == "sdk_limitation":
                key_evidence["SDK限制"] = str(payload.get("missing"))
            elif kind == "connection":
                key_evidence["连接"] = f"{payload.get('before')} → {payload.get('status')}"
        self.evidence_var.set("\n".join(f"{key}：{value}" for key, value in key_evidence.items())
                              or "本项证据见下方执行记录")
        self.replace_text("\n\n".join(lines))
        # Latest evidence remains visible during execution; stable on history revisit.
        if run_id == self.active_run:
            self.text.see("end")

    def drain(self):
        try:
            while True:
                kind, value = self.output.get_nowait()
                self.handle(kind, value)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(80, self.drain)

    def handle(self, kind, value):
        if kind == "available":
            self.available = not self.pending_reconnect
        elif kind == "fault":
            self.footer_var.set(value["message"])
        elif kind == "status":
            self.last_status = value
            self.connection_dot.configure(fg={"READY": "#12a373", "SYNCING": "#d69a24",
                                               "DISCONNECTED": "#dc5261", "ERROR": "#dc5261"}.get(value["connection"], MUTED))
            if value["paused"]:
                self.resume_button.pack(side="right", padx=6)
            else:
                self.resume_button.pack_forget()
            self.status_var.set(f"环境 {self.config.environment}  |  账号 {self.config.masked_user}  |  "
                f"交易日 {value['day'] or '—'}  |  {value['connection']}  |  "
                + ("交易已暂停" if value["paused"] else "交易入口启用"))
            counts, thresholds = value["counts"], value["thresholds"]
            parts = []
            for kind, label in (("order", "报单"), ("cancel", "撤单")):
                count, unknown = counts[kind]
                suffix = f"（提交时未知 {unknown}）" if unknown else ""
                parts.append(f"{label} {count}{suffix} / 阈值 {thresholds[kind] or '未设'}")
            self.metrics.set("当前统计    " + "      ".join(parts))
            if any(value["resources"].values()):
                self.footer_var.set("存量测试资源：" + json.dumps(value["resources"], ensure_ascii=False))
        elif kind == "history":
            self.history = value
            for run in reversed(value):
                self.run_cache[run["id"]] = run
                self.tree.set(str(run["case_id"]), "state", run["status"])
                self.tree.item(str(run["case_id"]), tags=(run["status"],))
            latest = {}
            for run in value:
                latest.setdefault(run["case_id"], run["status"])
            self.progress_var.set(f"{len(CASES)} 个测试点 · 已通过 {sum(s == '通过' for s in latest.values())} 项")
        elif kind == "run_started":
            run_id = value["run_id"]
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
            run = self.run_cache.get(run_id, {}) | value | {"id": run_id}
            self.run_cache[run_id] = run
            self.tree.set(str(value["case_id"]), "state", value["status"])
            self.tree.item(str(value["case_id"]), tags=(value["status"],))
            self.busy = False
            self.active_run = None
            if self.selected == value["case_id"]:
                self.show_run(run)
        elif kind == "view":
            self.event_cache[value["run_id"]] = value["events"]
            if getattr(self, "viewing_run", None) == value["run_id"]:
                self.render_events(value["run_id"])
        elif kind == "closed":
            self.available = False
            self.busy = False
            if self.closing:
                self.root.destroy()
                return
            if self.pending_reconnect:
                self.start_worker()
        self.buttons()

    def close(self):
        resources = self.last_status.get("resources", {})
        if self.busy or any(resources.values()):
            detail = json.dumps(resources, ensure_ascii=False)
            if not messagebox.askyesno("退出前核对", "退出不会自动平仓或撤销全部委托。\n"
                    + detail + "\n确定停止并退出？", parent=self.root):
                return
        self.closing = True
        self.available = False
        if self.worker and self.worker.is_alive():
            self.footer_var.set("正在停止测试并释放连接，请等待…")
            self.worker.close()
        else:
            self.root.destroy()


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
