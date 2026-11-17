"""
月报引擎 · 桌面客户端

面向企业的使用方式：
   双击桌面上的「月报引擎」→ 选数据（或下载模板填好）→ 选报告期 → 点「生成月报」
   → 30 秒后自动打开 PDF。

设计要点：
  · 数据源三种：内置示例 / 自己选的文件夹 / 单个 Excel 工作簿（五个 sheet）
  · 真正的计算、出稿都在后台线程跑，界面不卡；所有日志实时打到右边
  · 出错不崩，把堆栈写进日志，并在状态栏给出人话提示
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# 本文件位于 src/ 下。若以 `python src\gui.py` 启动，sys.path[0] 会等于 src/，
# 于是 src/copy.py 会遮蔽标准库 copy，pandas 一导入就崩（ImportError: deepcopy）。
# 这里先把 sys.path[0] 换成项目根目录，根治这个问题。
_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
if sys.path and Path(sys.path[0] or ".").resolve() == _SRC:
    sys.path[0] = str(_ROOT)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "tools") not in sys.path:
    sys.path.append(str(_ROOT / "tools"))

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

import pandas as pd  # noqa: E402

import build_report  # noqa: E402  (tools/build_report.py，已在上面的 sys.path 里)
import run_pipeline  # noqa: E402
from src import narrative as narr  # noqa: E402
from src import paths, template  # noqa: E402

ROOT = paths.app_root()

APP_NAME = "月报引擎"
APP_SUB = "经营月报自动生成系统"
VERSION = "1.0"
ASSETS = paths.res_root() / "assets"
OUT = ROOT / "outputs"
IMPORTS = ROOT / "data" / "imports"
REQUIRED = ["sales", "budget", "expenses", "dim_store", "dim_category"]
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _default_month(months: list[str]) -> str:
    """默认选上次生成过的月份，没有就选最新月份。"""
    if not months:
        return ""
    pdfs = sorted(OUT.glob("report_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in pdfs:
        m = p.stem.replace("report_", "")
        if m in months:
            return m
    return months[-1]


def run_generation(raw_dir: Path, month: str, use_llm: bool, log) -> Path | None:
    """出稿全过程：Stage A → 文案 → 版面 → PDF。GUI 与命令行共用这一条路径。"""
    run_pipeline.RAW = raw_dir
    run_pipeline.main(month)
    fp = json.loads((OUT / f"factpack_{month}.json").read_text(encoding="utf-8"))
    if use_llm:
        log("调用大模型生成结论与建议…")
        res = narr.generate("v3", fp, month)
        log(f"文案校验：{'通过' if res['passed'] else '未通过（使用兜底模板）'}；"
            f"尝试 {res['attempts']} 次")
    else:
        log("跳过模型调用，复用已校验文案或程序模板")
    info = build_report.main(month)
    pdf = Path(info["pdf"]) if isinstance(info, dict) and info.get("pdf") else None
    if pdf is None:
        cand = OUT / f"report_{month}.pdf"
        pdf = cand if cand.exists() else None
    if pdf is None:
        log("没有生成 PDF，详见上面的错误信息")
    return pdf

INK = "#1f2328"
SUB = "#6b7280"
NAVY = "#1f4e79"
NAVY_LIGHT = "#eaf1f8"
BG = "#f2f4f7"
CARD = "#ffffff"
BORDER = "#e3e8ee"
OK = "#2e7d5b"
WARN = "#c98a16"
ERR = "#c0392b"


class QueueWriter:
    """把 print() 的输出搬进日志框。"""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> None:
        for line in str(s).splitlines():
            if line.strip():
                self.q.put(("log", line.rstrip()))

    def flush(self) -> None:
        pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION} — {APP_SUB}")
        self.geometry("1040x820")
        self.minsize(980, 720)
        self.configure(bg=BG)
        self._center()
        self._set_icon()

        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.last_pdf: Path | None = None
        self.raw_dir: Path | None = None

        self.src_mode = tk.StringVar(value="demo")
        self.src_path = tk.StringVar(value="（内置示例：6 门店 × 8 品类 × 24 个月）")
        self.month = tk.StringVar()
        self.use_llm = tk.BooleanVar(value=True)
        self.auto_open = tk.BooleanVar(value=True)

        self._init_style()
        self._build()
        self.after(120, self._poll)
        self.log(f"{APP_NAME} v{VERSION} 已启动", "ok")
        self.log("选择数据源 → 选报告期 → 点「生成月报」。内置示例可直接生成。", "sub")
        self._log_hint()
        self._refresh_months()

    # ---------------------------------------------------------------- 外观
    def _center(self) -> None:
        self.update_idletasks()
        w, h = 1040, 820
        x = (self.winfo_screenwidth() - w) // 2
        y = max(0, (self.winfo_screenheight() - h) // 2 - 30)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _set_icon(self) -> None:
        ico = ASSETS / "app.ico"
        try:
            if ico.exists():
                self.iconbitmap(default=str(ico))
        except Exception:  # noqa: BLE001
            pass

    def _init_style(self) -> None:
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=INK, font=("Microsoft YaHei UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG, foreground=INK)
        st.configure("Card.TLabel", background=CARD, foreground=INK)
        st.configure("Sub.TLabel", background=CARD, foreground=SUB,
                     font=("Microsoft YaHei UI", 9))
        st.configure("Tip.TLabel", background=NAVY_LIGHT, foreground=SUB,
                     font=("Microsoft YaHei UI", 8))
        st.configure("H1.TLabel", background=NAVY, foreground="white",
                     font=("Microsoft YaHei UI", 18, "bold"))
        st.configure("H2.TLabel", background=NAVY, foreground="#a8c4dc",
                     font=("Microsoft YaHei UI", 9))
        st.configure("Card.TRadiobutton", background=CARD, foreground=INK,
                     font=("Microsoft YaHei UI", 10))
        st.configure("Card.TCheckbutton", background=CARD, foreground=INK,
                     font=("Microsoft YaHei UI", 10))
        st.map("Card.TRadiobutton", background=[("active", CARD)])
        st.map("Card.TCheckbutton", background=[("active", CARD)])
        st.configure("TButton", background=CARD, foreground=INK, padding=(14, 7),
                     borderwidth=1, font=("Microsoft YaHei UI", 10))
        st.map("TButton", background=[("active", "#eef2f7"), ("disabled", "#f4f6f8")],
               foreground=[("disabled", "#a9b2bd")])
        st.configure("Primary.TButton", background=NAVY, foreground="white",
                     font=("Microsoft YaHei UI", 10, "bold"), padding=(22, 10), borderwidth=0)
        st.map("Primary.TButton",
               background=[("active", "#2a6099"), ("disabled", "#c3cfdb")],
               foreground=[("disabled", "#f4f7fa")])
        st.configure("Ghost.TButton", background=CARD, foreground=NAVY, padding=(12, 6))
        st.configure("TProgressbar", background=NAVY, troughcolor="#e4e9f0",
                     borderwidth=0, thickness=9)
        st.configure("TCombobox", padding=4)
        st.configure("TEntry", padding=4)

    # ---------------------------------------------------------------- 布局
    def _card(self, parent: tk.Widget, no: str, title: str, pady=(0, 10)) -> tk.Frame:
        """统一卡片：白底 + 1px 描边 + 编号胶囊 + 标题。"""
        outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(fill="x", pady=pady)
        head = tk.Frame(outer, bg=CARD)
        head.pack(fill="x", padx=14, pady=(13, 0))
        tk.Label(head, text=no, bg=NAVY, fg="white",
                 font=("Microsoft YaHei UI", 8, "bold")).pack(side="left", ipadx=5, ipady=1)
        tk.Label(head, text=title, bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", padx=(8, 0))
        body = tk.Frame(outer, bg=CARD)
        body.pack(fill="x", padx=14, pady=(9, 13))
        return body

    def _build(self) -> None:
        self._build_header()
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(14, 6))
        body.columnconfigure(0, minsize=368, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_right(body)
        self._build_footer()

    def _build_header(self) -> None:
        h = tk.Frame(self, bg=NAVY, height=72)
        h.pack(fill="x")
        h.pack_propagate(False)
        left = tk.Frame(h, bg=NAVY)
        left.pack(side="left", padx=22)
        ttk.Label(left, text=APP_NAME, style="H1.TLabel").pack(anchor="w", pady=(13, 0))
        ttk.Label(left, text=f"{APP_SUB}   v{VERSION}", style="H2.TLabel").pack(anchor="w")
        right = tk.Frame(h, bg=NAVY)
        right.pack(side="right", padx=22)
        ttk.Label(right, text="数据 → 洞察 → 成稿", style="H2.TLabel").pack(anchor="e", pady=20)
        tk.Frame(self, bg="#c0392b", height=2).pack(fill="x")

    def _build_left(self, parent: tk.Widget) -> None:
        col = tk.Frame(parent, bg=BG)
        col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        # ① 数据源
        src = self._card(col, "1", "数据源")
        for text, val in (("使用内置示例数据", "demo"),
                          ("选择数据文件夹（含 5 张表）", "folder"),
                          ("选择 Excel 工作簿（5 个 sheet）", "xlsx")):
            ttk.Radiobutton(src, text=text, value=val, variable=self.src_mode,
                            command=self._on_mode, style="Card.TRadiobutton").pack(
                anchor="w", pady=1)
        row = tk.Frame(src, bg=CARD)
        row.pack(fill="x", pady=(9, 0))
        self.path_entry = ttk.Entry(row, textvariable=self.src_path, state="readonly")
        self.path_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self._browse, width=7).pack(side="left", padx=(6, 0))
        ttk.Button(src, text="下载数据模板（Excel）", command=self._save_template,
                   style="Ghost.TButton").pack(anchor="w", pady=(9, 0))

        # ② 报告期
        per = self._card(col, "2", "报告期")
        row2 = tk.Frame(per, bg=CARD)
        row2.pack(fill="x")
        self.month_box = ttk.Combobox(row2, textvariable=self.month, state="readonly", width=14)
        self.month_box.pack(side="left")
        ttk.Button(row2, text="刷新", command=self._refresh_months, width=6).pack(
            side="left", padx=(6, 0))
        ttk.Label(per, text="列表来自数据里实际存在的月份", style="Sub.TLabel").pack(
            anchor="w", pady=(7, 0))

        # ③ 选项
        opt = self._card(col, "3", "选项")
        ttk.Checkbutton(opt, text="用大模型生成结论与建议（约 0.02 元/次）",
                        variable=self.use_llm, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(opt, text="生成完成后自动打开 PDF",
                        variable=self.auto_open, style="Card.TCheckbutton").pack(
            anchor="w", pady=(5, 0))
        ttk.Label(opt, text="不勾选则复用上次已校验通过的文案，零成本、可复现",
                  style="Sub.TLabel", wraplength=306).pack(anchor="w", pady=(7, 0))

        # 接入提示（一行，避免第四张卡把版面撑出窗口）
        hint = tk.Frame(col, bg=NAVY_LIGHT)
        hint.pack(fill="x", pady=(0, 4))
        tk.Label(hint, text="企业接入：下载模板 → 按 sheet 填数 → 选文件夹 → 生成",
                 bg=NAVY_LIGHT, fg=NAVY, font=("Microsoft YaHei UI", 9),
                 anchor="w").pack(fill="x", padx=12, pady=8)

    def _build_right(self, parent: tk.Widget) -> None:
        col = tk.Frame(parent, bg=BG)
        col.grid(row=0, column=1, sticky="nsew")
        col.rowconfigure(2, weight=1)
        col.columnconfigure(0, weight=1)

        bar = tk.Frame(col, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        bar.grid(row=0, column=0, sticky="ew")
        inner = tk.Frame(bar, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)
        self.btn_check = ttk.Button(inner, text="检查数据", command=self.on_check)
        self.btn_check.pack(side="left")
        self.btn_run = ttk.Button(inner, text="生成月报", command=self.on_generate,
                                  style="Primary.TButton")
        self.btn_run.pack(side="left", padx=(10, 0))
        self.btn_pdf = ttk.Button(inner, text="打开 PDF", command=self.open_pdf, state="disabled")
        self.btn_pdf.pack(side="left", padx=(10, 0))
        self.btn_dir = ttk.Button(inner, text="输出文件夹", command=self.open_outdir)
        self.btn_dir.pack(side="left", padx=(6, 0))

        prow = tk.Frame(col, bg=BG)
        prow.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        self.pb = ttk.Progressbar(prow, mode="determinate", maximum=100)
        self.pb.pack(side="left", fill="x", expand=True)
        self.step_lbl = tk.Label(prow, text="", bg=BG, fg=SUB, width=6, anchor="e",
                                 font=("Microsoft YaHei UI", 8))
        self.step_lbl.pack(side="left", padx=(8, 0))

        wrap = tk.Frame(col, bg="#12161b", highlightthickness=1, highlightbackground="#12161b")
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.log_box = tk.Text(wrap, bg="#12161b", fg="#c9d1d9", insertbackground="#c9d1d9",
                               relief="flat", font=("Consolas", 9), wrap="word",
                               padx=16, pady=12, state="disabled", borderwidth=0,
                               highlightthickness=0)
        self.log_box.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(wrap, command=self.log_box.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_box.configure(yscrollcommand=sb.set)
        for tag, color in (("ok", "#6fcf97"), ("warn", "#f2c94c"), ("err", "#eb5757"),
                           ("sub", "#6b7684"), ("hi", "#7fb3e8"), ("step", "#ffffff")):
            self.log_box.tag_configure(tag, foreground=color)
        self.log_box.tag_configure("step", font=("Consolas", 9, "bold"))

    def _build_footer(self) -> None:
        f = tk.Frame(self, bg=CARD, height=32, highlightthickness=1,
                     highlightbackground=BORDER)
        f.pack(fill="x", side="bottom")
        f.pack_propagate(False)
        self.dot = tk.Canvas(f, width=8, height=8, bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", padx=(16, 6))
        self._dot_item = self.dot.create_oval(0, 0, 8, 8, fill=SUB, outline="")
        self.status = tk.Label(f, text="就绪", bg=CARD, fg=SUB,
                               font=("Microsoft YaHei UI", 9), anchor="w")
        self.status.pack(side="left")
        tk.Label(f, text=f"输出目录  {OUT}", bg=CARD, fg="#9aa4b0",
                 font=("Microsoft YaHei UI", 8)).pack(side="right", padx=16)

    # ---------------------------------------------------------------- 日志
    def log(self, msg: str, tag: str = "") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] ", "sub")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _log_hint(self) -> None:
        """日志区空着时给一句占位说明，避免一大块纯黑。"""
        self.log_box.tag_configure("hint", foreground="#4b5563", justify="center",
                                   spacing1=26)
        self.log_box.configure(state="normal")
        self.log_box.insert("end",
                            "\n\n运行日志将在此实时显示\n"
                            "校验结果 · 异常清单 · 版面求解 · PDF 质检\n", "hint")
        self.log_box.configure(state="disabled")

    def set_status(self, text: str, color: str = SUB) -> None:
        self.status.configure(text=text, fg=color)
        try:
            self.dot.itemconfigure(self._dot_item, fill=color)
        except Exception:  # noqa: BLE001
            pass

    STEP_RE = re.compile(r"\[(\d)/6\]")

    def _track_step(self, line: str) -> None:
        """从流水线的 [n/6] 标记推进进度条。"""
        m = self.STEP_RE.search(line)
        if m and self.busy:
            pct = int(m.group(1)) / 6 * 100
            self.pb.configure(value=pct)
            self.step_lbl.configure(text=f"{int(pct)}%")

    # ---------------------------------------------------------------- 事件
    def _on_mode(self) -> None:
        mode = self.src_mode.get()
        if mode == "demo":
            self.src_path.set("（内置示例：6 门店 × 8 品类 × 24 个月）")
        else:
            self.src_path.set("")
        self._refresh_months()

    def _browse(self) -> None:
        mode = self.src_mode.get()
        if mode == "folder":
            p = filedialog.askdirectory(title="选择包含 5 张表的数据文件夹")
        elif mode == "xlsx":
            p = filedialog.askopenfilename(title="选择 Excel 工作簿",
                                           filetypes=[("Excel 工作簿", "*.xlsx *.xlsm")])
        else:
            return
        if p:
            self.src_path.set(p)
            self._refresh_months()

    def _save_template(self) -> None:
        p = filedialog.asksaveasfilename(title="保存数据模板", defaultextension=".xlsx",
                                         initialfile="经营月报_数据模板.xlsx",
                                         filetypes=[("Excel 工作簿", "*.xlsx")])
        if not p:
            return
        try:
            template.write_template(p)
            self.log(f"模板已保存：{p}", "ok")
            self.set_status("模板已保存，按 sheet 填好后放到一个文件夹里", OK)
        except Exception as e:  # noqa: BLE001
            self.log(f"模板保存失败：{e}", "err")
            messagebox.showerror("保存失败", str(e))

    # ---------------------------------------------------------------- 数据
    def _resolve_raw(self) -> tuple[Path | None, str | None]:
        mode = self.src_mode.get()
        if mode == "demo":
            self.raw_dir = paths.res_root() / "data" / "raw"
            return self.raw_dir, None

        p = Path(self.src_path.get().strip())
        if not str(p) or not p.exists():
            return None, "请先选择数据来源"
        if mode == "xlsx":
            try:
                target = IMPORTS / datetime.now().strftime("%Y%m%d_%H%M%S") / "raw"
                self._xlsx_to_raw(p, target)
                self.raw_dir = target
                return target, None
            except Exception as e:  # noqa: BLE001
                return None, f"Excel 导入失败：{e}"

        # folder
        target = IMPORTS / datetime.now().strftime("%Y%m%d_%H%M%S") / "raw"
        target.mkdir(parents=True, exist_ok=True)
        missing = []
        for name in REQUIRED:
            csv, xlsx = p / f"{name}.csv", p / f"{name}.xlsx"
            if csv.exists():
                shutil.copy2(csv, target / f"{name}.csv")
            elif xlsx.exists():
                pd.read_excel(xlsx, dtype=str).to_csv(target / f"{name}.csv",
                                                      index=False, encoding="utf-8-sig")
            else:
                missing.append(f"{name}.csv")
        if missing:
            return None, "文件夹里缺少：" + "、".join(missing)
        self.raw_dir = target
        return target, None

    def _xlsx_to_raw(self, xlsx: Path, target: Path) -> None:
        book = pd.ExcelFile(xlsx)
        missing = [s for s in REQUIRED if s not in book.sheet_names]
        if missing:
            raise ValueError("缺少 sheet：" + "、".join(missing))
        target.mkdir(parents=True, exist_ok=True)
        for s in REQUIRED:
            pd.read_excel(book, sheet_name=s, dtype=str).to_csv(
                target / f"{s}.csv", index=False, encoding="utf-8-sig")

    def _refresh_months(self) -> None:
        try:
            raw, err = self._resolve_raw()
            if err:
                self.month_box["values"] = []
                self.month.set("")
                self.set_status(err, WARN)
                return
            sales = pd.read_csv(raw / "sales.csv", encoding="utf-8-sig", dtype=str)
            raw_months = {m for m in sales["month"].dropna().astype(str)}
            months = sorted({m for m in raw_months if MONTH_RE.match(m)})
            dropped = sorted(raw_months - set(months))
            self.month_box["values"] = months
            if months and self.month.get() not in months:
                self.month.set(_default_month(months))
            msg = f"数据源就绪：{len(sales)} 行，{len(months)} 个合法月份"
            if dropped:
                msg += f"（已忽略 {len(dropped)} 个非法期间，如 {dropped[0]}）"
            self.set_status(msg, SUB)
        except Exception as e:  # noqa: BLE001
            self.month_box["values"] = []
            self.set_status(f"读取月份失败：{e}", WARN)

    # ---------------------------------------------------------------- 任务
    def _busy(self, on: bool, status: str = "") -> None:
        self.busy = on
        for b in (self.btn_check, self.btn_run):
            b.configure(state="disabled" if on else "normal")
        if on:
            self.pb.stop()
            self.pb.configure(mode="determinate", value=0)
            self.step_lbl.configure(text="0%")
            if status:
                self.set_status(status, NAVY)
        else:
            self.pb.stop()
            self.pb.configure(value=0)
            self.step_lbl.configure(text="")

    def _worker(self, fn) -> None:
        def run():
            try:
                fn()
            except Exception:  # noqa: BLE001
                self.q.put(("log", "运行出错：\n" + traceback.format_exc()))
                self.q.put(("fail", "运行失败，详见日志"))

        threading.Thread(target=run, daemon=True).start()

    def on_check(self) -> None:
        if self.busy:
            return
        raw, err = self._resolve_raw()
        if err:
            messagebox.showwarning("数据源有问题", err)
            return
        month = self.month.get().strip()

        def job():
            self.q.put(("busy", "正在检查数据…"))
            with contextlib.redirect_stdout(QueueWriter(self.q)):
                from src import ingest as ing
                data = ing.load_raw(raw)
                self.q.put(("log", f"读取明细 {len(data['sales'])} 行、预算 {len(data['budget'])} 行"))
                clean, bad = ing.validate(data["sales"], data["dim_store"], data["dim_category"])
                self.q.put(("log", f"校验通过 {len(clean)} 行，拦截 {len(bad)} 行",
                            "ok" if len(bad) == 0 else "warn"))
                if len(bad):
                    for rid, cnt in bad["rule_id"].value_counts().items():
                        self.q.put(("log", f"  {rid} {ing.RULES[rid]}：{cnt} 行", "warn"))
                miss = ing.check_expense_coverage(clean, data["expenses"])
                if len(miss):
                    self.q.put(("log", f"缺费用记录的门店-月：{len(miss)} 个", "warn"))
                months = sorted({m for m in data["sales"]["month"].dropna().astype(str) if len(m) == 7})
                self.q.put(("log", f"可选报告期 {len(months)} 个，最新 {months[-1] if months else '—'}"))
                ok = "数据检查完成" if len(clean) else "数据全部被拦截，无法生成"
                self.q.put(("ok", ok))

        self._worker(job)

    def on_generate(self) -> None:
        if self.busy:
            return
        raw, err = self._resolve_raw()
        if err:
            messagebox.showwarning("数据源有问题", err)
            return
        month = self.month.get().strip()
        if not month:
            messagebox.showwarning("请选择报告期", "数据里没有可用的月份")
            return
        use_llm = self.use_llm.get()
        auto_open = self.auto_open.get()

        def job():
            self.q.put(("busy", "正在生成月报…"))
            with contextlib.redirect_stdout(QueueWriter(self.q)):
                run_generation(raw, month, use_llm, lambda m: self.q.put(("log", m)))
            pdf = OUT / f"report_{month}.pdf"
            self.q.put(("done", str(pdf) if pdf.exists() else ""))
            if auto_open and pdf.exists():
                self._open(str(pdf))

        self._worker(job)

    # ---------------------------------------------------------------- 收尾
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._track_step(payload)
                    self.log(payload)
                elif kind == "hi":
                    self.log(payload, "hi")
                elif kind == "ok":
                    self.log(payload, "ok")
                    self.set_status(payload, OK)
                elif kind == "warn":
                    self.log(payload, "warn")
                elif kind == "err":
                    self.log(payload, "err")
                elif kind == "busy":
                    self._busy(True, payload)
                elif kind == "done":
                    self._busy(False)
                    if payload:
                        self.last_pdf = Path(payload)
                        self.btn_pdf.configure(state="normal")
                        self.pb.configure(value=100)
                        self.step_lbl.configure(text="完成")
                        size = self.last_pdf.stat().st_size // 1024
                        self.log(f"月报已生成：{payload}（{size} KB）", "ok")
                        self.set_status("生成完成，可打开 PDF", OK)
                    else:
                        self.set_status("生成结束，但没有找到 PDF", WARN)
                elif kind == "fail":
                    self._busy(False)
                    self.set_status(payload, ERR)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _open(self, target: str) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(target)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:  # noqa: BLE001
            self.log(f"打开失败：{e}", "err")

    def open_pdf(self) -> None:
        if self.last_pdf and self.last_pdf.exists():
            self._open(str(self.last_pdf))

    def open_outdir(self) -> None:
        self._open(str(OUT))


def main() -> None:
    if "--run" in sys.argv:
        i = sys.argv.index("--run")
        month = sys.argv[i + 1] if len(sys.argv) > i + 1 else "2025-10"
        use_llm = "--no-llm" not in sys.argv
        pdf = run_generation(paths.res_root() / "data" / "raw", month, use_llm, print)
        print(f"\n[完成] {pdf}")
        return

    app = App()
    if "--selftest" in sys.argv:
        app.update()
        months = app.month_box["values"]
        print("SELFTEST OK")
        print(f"  可选月份 {len(months)} 个，最新 {months[-1] if months else '—'}")
        print(f"  当前选中 {app.month.get() or '—'}")
        print(f"  数据源   {app.raw_dir}")
        print(f"  输出目录 {OUT}")
        app.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
