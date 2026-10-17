"""`python -m agent_conflict_radar` 通路。

⚠️ 入口必须是**绝对导入的薄模块**：相对导入会让冻结产物一启动就
`ImportError: attempted relative import with no known parent package`，
而构建过程仍 exit 0（SKILL「冻结构建首次实构建」条）。这里刻意用绝对导入。
"""

import sys

from agent_conflict_radar.cli import main

if __name__ == "__main__":
    sys.exit(main())
