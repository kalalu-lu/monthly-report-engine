"""
HTML → PDF（Stage B 第四步之二）

为什么不引第三方库：
  - WeasyPrint 在 Windows 上要 GTK 运行库，装不动；
  - wkhtmltopdf 早就停止维护，中文断行与字体嵌入都不可靠；
  - 本机 Edge 是 Chromium 内核，自带 --print-to-pdf，字体、颜色、@page 全都支持，
    而且它就在系统里，零安装。

代价是它是命令行黑盒，所以这里做两件事把它"框住"：
  1. 固定参数：无页眉页脚、A4、0 边距（边距由版面求解器给，不由浏览器给）
  2. 出完立刻回读 PDF 二进制，核对页数、纸张尺寸、字体嵌入——
     不合格就抛异常，绝不"生成成功但其实是空白页"还往下走。

接口：
  find_browser()                 -> 可用的 Chromium 内核浏览器路径
  to_pdf(html, pdf)              -> 转档，返回耗时/大小
  pdf_info(path)                 -> {"pages","size_bytes","page_mm","fonts","linearized"}
  screenshot(html, png, page_no) -> 单页截图（评测用来做视觉核查）
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

MM_PER_PX = 25.4 / 96.0


class RenderError(RuntimeError):
    pass


def find_browser() -> Path:
    for c in CANDIDATES:
        p = Path(c)
        if p.exists():
            return p
    found = shutil.which("msedge") or shutil.which("chrome")
    if found:
        return Path(found)
    raise RenderError("找不到 Edge/Chrome，无法把 HTML 转成 PDF")


def _base_args(browser: Path, profile: Path) -> list[str]:
    return [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        f"--user-data-dir={profile}",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=4000",
    ]


def _run(args: list[str], timeout: int) -> str:
    """运行浏览器。输出重定向到临时文件而不是管道——
    管道有 64KB 上限，Chromium 在打印时可能写满缓冲导致死锁（表现为"执行超时"且无输出）。"""
    import tempfile as _tf

    with _tf.NamedTemporaryFile(delete=False, suffix=".log") as f:
        log_path = Path(f.name)
    try:
        with open(log_path, "wb") as fh:
            try:
                r = subprocess.run(args, stdout=fh, stderr=fh, timeout=timeout,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired as e:
                raise RenderError(f"浏览器执行超时（{timeout}s）") from e
        err = log_path.read_text("utf-8", "ignore")
        if r.returncode != 0:
            raise RenderError(f"浏览器返回 {r.returncode}：{err[-600:]}")
        return err
    finally:
        try:
            log_path.unlink()
        except OSError:
            pass


def _ascii_temp_base() -> Path:
    """给 Chromium 用的临时基目录必须是纯 ASCII 路径。

    踩过的坑：如果临时目录里带中文（例如程序装在 E:\\AI实践报告作业\\… 下），
    Chromium 创建 user-data-dir 会失败并**一直挂住**，表现为"浏览器执行超时"，
    而且没有任何错误信息。
    """
    import os

    cands = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Temp",
        Path("C:/Windows/Temp"),
        Path("C:/Temp"),
        Path(os.environ.get("SystemDrive", "C:") + "/Temp"),
    ]
    for c in cands:
        try:
            if not c.is_dir():
                c.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if all(ord(ch) < 128 for ch in str(c)):
            return c
    return Path(tempfile.gettempdir())


def to_pdf(html_path: str | Path, pdf_path: str | Path, timeout: int = 180) -> dict:
    browser = find_browser()
    html_p = Path(html_path).resolve()
    pdf_p = Path(pdf_path).resolve()
    pdf_p.parent.mkdir(parents=True, exist_ok=True)
    if pdf_p.exists():
        try:
            pdf_p.unlink()
        except PermissionError:
            # 用户正打开着这份 PDF（阅读器占用文件句柄）。
            # 不打断他，改写成带时间戳的副本，并在返回值里告诉他实际路径。
            from datetime import datetime
            stamp = datetime.now().strftime("%H%M%S")
            alt = pdf_p.with_name(f"{pdf_p.stem}_{stamp}{pdf_p.suffix}")
            print(f"[提示] {pdf_p.name} 正在被其它程序占用，本次改存为 {alt.name}")
            pdf_p = alt

    with tempfile.TemporaryDirectory(prefix="dsh-pdf-", dir=str(_ascii_temp_base())) as tmp:
        args = _base_args(browser, Path(tmp)) + [
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_p}",
            html_p.as_uri(),
        ]
        t0 = time.time()
        _run(args, timeout)
        cost = int((time.time() - t0) * 1000)

    if not pdf_p.exists() or pdf_p.stat().st_size == 0:
        raise RenderError("浏览器没有产出 PDF（页面可能渲染失败）")
    return {"path": pdf_p, "ms": cost, "size": pdf_p.stat().st_size, "browser": browser.name}


def screenshot(html_path: str | Path, png_path: str | Path, page: int = 1,
               total_pages: int = 1, scale: int = 2, timeout: int = 120) -> Path:
    """截第 page 页：临时把 HTML 里其它页隐藏（只在截图副本里改，不动正式文件）。"""
    html_p = Path(html_path).resolve()
    png_p = Path(png_path).resolve()
    png_p.parent.mkdir(parents=True, exist_ok=True)
    text = html_p.read_text(encoding="utf-8")
    hide = "".join(
        f'.page[data-page="{k}"]{{display:none!important}}'
        for k in range(1, total_pages + 1) if k != page)
    probe = html_p.with_name(f"_shot_{html_p.stem}_{page}.html")
    probe.write_text(text.replace("</style>", hide + "</style>"), encoding="utf-8")
    w_px = round(210 / MM_PER_PX)
    h_px = round(297 / MM_PER_PX)
    try:
        with tempfile.TemporaryDirectory(prefix="dsh-shot-", dir=str(_ascii_temp_base())) as tmp:
            args = _base_args(find_browser(), Path(tmp)) + [
                f"--window-size={w_px},{h_px}",
                f"--force-device-scale-factor={scale}",
                f"--screenshot={png_p}",
                probe.as_uri(),
            ]
            _run(args, timeout)
    finally:
        probe.unlink(missing_ok=True)
    if not png_p.exists():
        raise RenderError("截图失败")
    return png_p


# --------------------------------------------------------------------- PDF 校验
def pdf_info(path: str | Path) -> dict:
    """从 PDF 二进制里读出页数、纸张尺寸、字体嵌入情况（不依赖任何 PDF 库）。"""
    p = Path(path)
    data = p.read_bytes()
    if not data.startswith(b"%PDF"):
        raise RenderError("不是合法 PDF（缺少 %PDF 头）")
    if b"%%EOF" not in data[-2048:]:
        raise RenderError("PDF 尾部缺少 %%EOF，文件可能被截断")

    counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", data)]
    pages = max(counts) if counts else len(re.findall(rb"/Type\s*/Page[^s]", data))

    mb = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    page_mm = None
    if mb:
        w = float(mb.group(3)) - float(mb.group(1))
        h = float(mb.group(4)) - float(mb.group(2))
        page_mm = (round(w * 25.4 / 72, 1), round(h * 25.4 / 72, 1))

    fonts = sorted({m.group(1).decode("latin-1") for m in
                    re.finditer(rb"/BaseFont\s*/([A-Za-z0-9+\-_,.]+)", data)})
    embedded = len(re.findall(rb"/FontFile[23]?\b", data))
    return {
        "path": p, "pages": pages, "page_mm": page_mm,
        "size_bytes": p.stat().st_size,
        "fonts": fonts, "embedded_font_files": embedded,
        "linearized": b"/Linearized" in data,
    }


def check_pdf(path: str | Path, expect_pages: int | None = None,
              expect_mm: tuple[float, float] = (210.0, 297.0), tol: float = 1.5) -> list[str]:
    """核对 PDF 是否真的符合版面计划。返回问题列表（空 = 合格）。"""
    try:
        info = pdf_info(path)
    except RenderError as e:
        return [str(e)]
    errs = []
    if info["size_bytes"] < 8000:
        errs.append(f"PDF 只有 {info['size_bytes']} 字节，可能是空白页")
    if expect_pages is not None and info["pages"] != expect_pages:
        errs.append(f"页数 {info['pages']} ≠ 版面计划 {expect_pages}")
    if info["page_mm"]:
        w, h = info["page_mm"]
        if abs(w - expect_mm[0]) > tol or abs(h - expect_mm[1]) > tol:
            errs.append(f"纸张 {w}×{h}mm 不是 A4")
    else:
        errs.append("读不到 MediaBox，无法确认纸张尺寸")
    if info["embedded_font_files"] == 0:
        errs.append("没有内嵌字体（换机器打开会变字）")
    return errs
