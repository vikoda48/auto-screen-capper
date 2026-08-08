"""
字幕自动截屏工具 —— 快捷启动脚本

运行方法：
    python run_subtitle_capper.py
"""

import sys
from subtitle_capper.app import main

if __name__ == "__main__":
    sys.exit(main() or 0)
