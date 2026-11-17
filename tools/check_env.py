"""
环境自检：确认 .env 是否配好、DeepSeek 是否连得通、依赖是否齐全。

运行：python tools/check_env.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import llm  # noqa: E402


def main() -> int:
    print("=" * 60)
    print("环境自检")
    print("=" * 60)
    print(f"解释器    : {sys.executable}")
    print(f"版本      : {sys.version.split()[0]}")
    print(f"项目根目录: {ROOT}")
    print(f".env 路径 : {llm.ENV_FILE}")
    print(f".env 存在 : {llm.ENV_FILE.exists()}")

    env = llm.load_env()
    key = env["DEEPSEEK_API_KEY"].strip()
    shown = f"{key[:6]}…{key[-4:]}" if len(key) > 12 else ("（未填写）" if not key else "（长度异常）")
    print(f"API Key   : {shown}   模型: {env['DEEPSEEK_MODEL']}")

    try:
        import pandas  # noqa: F401
        print("pandas    : OK")
    except Exception as e:  # noqa: BLE001
        print(f"pandas    : 不可用 → {e}")
        print("            请改用 run.bat，它会自动挑选可用的解释器")
        return 1

    if not key:
        print("\n[未配置] 请用记事本打开上面的 .env 文件，在 DEEPSEEK_API_KEY= 后面填入你的 key 再保存。")
        print("         注意：等号后面不要留空格，不要加引号。")
        return 2

    print("\n正在测试一次最小调用 …")
    try:
        r = llm.chat([{"role": "user", "content": "只回复两个字：连通"}], max_tokens=16)
        print(f"  返回      : {r['content'].strip()[:40]!r}")
        print(f"  模型      : {r['model']}")
        print(f"  耗时      : {r['latency_ms']} ms")
        print(f"  token 用量: {r['usage']}")
        print("\n[OK] 配置可用。")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"\n[失败] {e}")
        print("检查：key 是否正确、账户是否有余额、网络是否可访问 api.deepseek.com")
        return 3


if __name__ == "__main__":
    sys.exit(main())
