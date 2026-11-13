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
        self.title("首次配置 / 测试环境设置")
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
        ttk.Button(bar, text="保存并连接", command=self.save).pack(side="right")
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
        self.settings_button = ttk.Button(toolbar, text="连接设置", command=self.settings)
        self.settings_button.pack(side="right", padx=(4, 0))
        self.stop_button = ttk.Button(toolbar, text="停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=4)
        self.rerun_button = ttk.Button(toolbar, text="重新测试", command=self.rerun, state="disabled")
        self.rerun_button.pack(side="right", padx=4)
        self.resume_button = ttk.Button(toolbar, text="恢复交易", command=self.resume_trading)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        left = ttk.LabelFrame(body, text="测试点", padding=4, width=290)
        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(left, weight=0)
        body.add(right, weight=1)
        body.bind("<Map>", lambda _event: body.sashpos(0, 290))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        navigation = ttk.Frame(left)
        navigation.grid(row=0, column=0, sticky="nsew")
        self.tree = ttk.Treeview(navigation, columns=("state",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="项目")
        self.tree.heading("state", text="结果")
        self.tree.column("#0", width=180, minwidth=140)
        self.tree.column("state", width=90, minwidth=85, stretch=False)
        scroll = ttk.Scrollbar(navigation, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        for case in CASES:
            if not self.tree.exists(case.group):
                self.tree.insert("", "end", iid=case.group, text=case.group.partition(" ")[2], open=True)
            self.tree.insert(case.group, "end", iid=str(case.id), text=case.title, values=("未执行",))
        self.tree.bind("<ButtonRelease-1>", self.click)
        self.tree.bind("<<TreeviewSelect>>", self.view_selection)
        self.progress_var = tk.StringVar(value=f"共 {len(CASES)} 项，通过 0 项")
        ttk.Label(left, textvariable=self.progress_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        result = ttk.LabelFrame(right, text="结果", padding=8)
        result.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        result.columnconfigure(0, weight=1)
        heading = ttk.Frame(result)
        heading.grid(row=0, column=0, sticky="ew")
        self.result_label = ttk.Label(heading, text="待选择")
        self.result_label.pack(side="right")
        self.title_var = tk.StringVar(value="请选择测试点")
        title = ttk.Label(heading, textvariable=self.title_var, style="Header.TLabel")
        title.pack(side="left", fill="x", expand=True)
        self.purpose = tk.StringVar(value="")
        purpose_label = ttk.Label(result, textvariable=self.purpose, justify="left", wraplength=700)
        purpose_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.meta = tk.StringVar(value="")
        meta_label = ttk.Label(result, textvariable=self.meta, justify="left", wraplength=700)
        meta_label.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.summary = tk.StringVar(value="")
        summary_label = ttk.Label(result, textvariable=self.summary, wraplength=700, justify="left")
        summary_label.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.metrics = tk.StringVar(value="")
        metric_label = ttk.Label(result, textvariable=self.metrics, wraplength=700)
        metric_label.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self.evidence_var = tk.StringVar(value="")
        evidence_label = ttk.Label(result, textvariable=self.evidence_var, justify="left", wraplength=700)
        evidence_label.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        self.history_bar = ttk.Frame(result)
        history_bar = self.history_bar
        history_bar.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(history_bar, text="历史运行").pack(side="left", padx=(0, 6))
        self.history_combo = ttk.Combobox(history_bar, state="readonly", width=35)
        self.history_combo.pack(side="left", fill="x", expand=True)
        self.history_combo.bind("<<ComboboxSelected>>", self.choose_history)

        records = ttk.LabelFrame(right, text="日志", padding=4)
        records.grid(row=1, column=0, sticky="nsew")
        self.text = tk.Text(records, wrap="word", height=6, font=("Microsoft YaHei UI", 9),
                            relief="sunken", borderwidth=1, padx=4, pady=4, state="disabled")
        scrollbar = ttk.Scrollbar(records, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.wrap_labels = [title, purpose_label, meta_label, summary_label, metric_label, evidence_label]
        self.optional_result_labels = [(self.purpose, purpose_label), (self.meta, meta_label), (self.summary, summary_label),
                                       (self.metrics, metric_label), (self.evidence_var, evidence_label)]
        for variable, _label in self.optional_result_labels:
            variable.trace_add("write", lambda *_args: self.refresh_result_rows())
        self.refresh_result_rows()
        right.bind("<Configure>", self.resize_content)
        self.footer_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.footer_var, padding=(8, 4), wraplength=1050).grid(
            row=2, column=0, sticky="ew")

    def resize_content(self, event):
        width = max(240, event.width - 32)
        for label in self.wrap_labels:
            label.configure(wraplength=width - 90 if label is self.wrap_labels[0] else width)

    def set_result(self, status):
        self.result_label.configure(text=status)

    def refresh_result_rows(self):
        for variable, label in self.optional_result_labels:
            visible = bool(variable.get().strip())
            if variable is self.metrics:
                visible = visible and self.selected in (7, 8, 12, 13, 14, 15, 31)
            if visible:
                label.grid()
            else:
                label.grid_remove()
        if len(self.history_combo["values"]) > 1:
            self.history_bar.grid()
        else:
            self.history_bar.grid_remove()

    def refresh_history_choices(self):
        runs = [r for r in self.history if r["case_id"] == self.selected]
        self.history_combo["values"] = [f"{r['started']}  {r['status']}  {r['id']}" for r in runs]
        if runs:
            index = next((i for i, r in enumerate(runs) if r["id"] == getattr(self, "viewing_run", None)), 0)
            self.history_combo.current(index)
        else:
            self.history_combo.set("")
        self.refresh_result_rows()

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
        self.purpose.set(f"目的：{case.purpose}")
        runs = [r for r in self.history if r["case_id"] == case_id]
        self.refresh_history_choices()
        if runs:
            self.history_combo.current(0)
            self.show_run(runs[0])
        elif self.active_run and self.run_cache.get(self.active_run, {}).get("case_id") == case_id:
            self.show_run(self.run_cache[self.active_run])
        else:
            self.set_result("待执行")
            self.viewing_run = None
            self.meta.set("")
            self.summary.set("")
            if self.busy:
                self.summary.set("其他测试执行中")
            self.replace_text("")
            self.evidence_var.set("")
            if execute and not self.busy and self.available:
                self.start_case(case_id)
        self.buttons()

    def start_case(self, case_id):
        if self.busy or not self.available:
            return
        self.busy = True
        self.worker.stop_test.clear()
        self.set_result("执行中")
        self.summary.set("")
        self.meta.set("")
        self.evidence_var.set("")
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
        self.purpose.set(f"目的：{BY_ID[run['case_id']].purpose}")
        timestamp = str(run.get("started") or "").replace("T", " ").removesuffix("+08:00")
        self.meta.set("  ·  ".join(part for part in (timestamp, f"交易日 {run['day']}" if run.get("day") else "", run["id"]) if part))
        summary = run.get("summary") or ""
        self.summary.set("" if summary == "已取得符合本测试点判定条件的真实证据" else summary)
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
        self.evidence_var.set("\n".join(f"{key}：{value}" for key, value in key_evidence.items()))
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
            self.refresh_history_choices()
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
