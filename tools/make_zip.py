"""
把目录打成**规范 ZIP**（路径分隔符用 `/`）。

为什么需要这个脚本：PowerShell 的 [System.IO.Compression.ZipFile]::CreateFromDirectory
在 .NET Framework 下会把 Windows 的 `\\` 直接写进条目名，而 ZIP 规范要求 `/`。
用资源管理器解压这类包时，含反斜杠的条目会被判为非法文件名而跳过，
表现为"解压后少了文件"。Python 的 zipfile 会正确使用 `/`。

用法：
    python tools/make_zip.py <源目录> <输出.zip>
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def build_zip(src: Path, out: Path, compress_level: int = 6) -> tuple[int, int]:
    src = src.resolve()
    out = out.resolve()
    if not src.is_dir():
        raise SystemExit(f"源目录不存在：{src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    n = 0
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=compress_level) as z:
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            arc = p.relative_to(src.parent).as_posix()   # 关键：正斜杠
            z.write(p, arc)
            n += 1
            total += p.stat().st_size
    return n, total


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    n, total = build_zip(src, out)
    size = out.stat().st_size
    print(f"条目 {n} 个，原始 {total / 1e6:.0f} MB → {out.name} {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
