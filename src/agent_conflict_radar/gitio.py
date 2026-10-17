"""git 只读封装（K4 / K8）。

三层保护，缺一层都不算"只读"：

1. **子命令白名单**：只允许枚举出的只读形态（`worktree list` / `status` / `diff` / `log` /
   `rev-parse` / `merge-tree` / `cat-file` / `ls-tree` / `rev-list` / `show` / `symbolic-ref` /
   `ls-files` / `for-each-ref` / `hash-object`）。任何 merge / rebase / reset / checkout /
   commit / apply / stash / worktree add|remove … 一律抛 `ReadOnlyViolation`。
2. **禁写标志**：`-w` / `--write` / `--hard` / `--force` / `--prune` / `--amend` 一律拒绝
   （**例外**：`merge-tree --write-tree` 是题面指定的无副作用试合并形态，显式放行并记录其边界）。
3. **可选锁关闭**：子进程环境置 `GIT_OPTIONAL_LOCKS=0`，防止 `status` 之类刷新索引而**写 .git**。

`--write-tree` 的如实边界（不得声称"零任何写入"）：它会在对象库写入临时 tree/blob 对象，
但**不改索引、不改工作区、不建分支**。这条边界写进 README 与报告。

编码（K8）：子进程显式 `encoding="utf-8"`。`py -X utf8` 只改我们自己进程的 stdio，
**改不了子进程的解码通路**——子进程解码走 locale，不显式指定就会在 CI（cp1252）上炸。
"""

import os
import shutil
import subprocess
from typing import List, NamedTuple, Optional, Sequence

from .errors import EnvironmentError_, ReadOnlyViolation

#: 允许的首个参数（子命令）。
READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "worktree",
        "status",
        "diff",
        "log",
        "rev-parse",
        "merge-tree",
        "cat-file",
        "ls-tree",
        "rev-list",
        "show",
        "symbolic-ref",
        "ls-files",
        "for-each-ref",
        "hash-object",
        "version",
        "--version",
        "--no-pager",
    }
)

#: 会被误用成写操作的标志：一律拒绝（例外见 `_ALLOWED_WRITE_FLAGS`）。
MUTATING_FLAGS = frozenset({"-w", "--write", "--hard", "--force", "--prune", "--amend"})

#: 显式放行的"名字里有 write 但语义只读"的形态。
_ALLOWED_WRITE_FLAGS = frozenset({"--write-tree"})

#: `worktree` 只允许 `list` 子形态（`add` / `remove` / `prune` / `lock` 都会改磁盘）。
_WORKTREE_ALLOWED = frozenset({"list"})


class GitResult(NamedTuple):
    args: List[str]
    returncode: int
    stdout: str
    stderr: str


def git_available() -> bool:
    """git 是否可用（只做存在性探测，不执行任何 git 命令）。"""
    return shutil.which("git") is not None


def ensure_git_available() -> str:
    """返回 git 可执行文件路径；不可用则抛 `EnvironmentError_`（exit 3）。"""
    path = shutil.which("git")
    if path is None:
        raise EnvironmentError_(
            "找不到 git 可执行文件：本工具的多项能力（worktree 枚举、无副作用试合并、未提交 diff）"
            "依赖 git。请安装 git 并确保它在 PATH 上。"
        )
    return path


def _assert_read_only(args: Sequence[str]) -> None:
    if not args:
        raise ReadOnlyViolation("空的 git 参数：拒绝执行（只读纪律要求显式声明子命令）")
    head = args[0]
    if head not in READ_ONLY_SUBCOMMANDS:
        raise ReadOnlyViolation(
            "拒绝执行非只读 git 子命令 %r（K4）：本工具绝不写 git 索引、不执行 merge/rebase、"
            "不修改工作区。" % head
        )
    if head == "worktree":
        if len(args) < 2 or args[1] not in _WORKTREE_ALLOWED:
            raise ReadOnlyViolation(
                "`git worktree` 只允许 `list`（add/remove/prune/lock 都会改磁盘）：收到 %r" % list(args)
            )
    for token in args:
        if token in _ALLOWED_WRITE_FLAGS:
            continue
        if token in MUTATING_FLAGS:
            raise ReadOnlyViolation("拒绝执行含写操作标志 %r 的 git 命令：%r" % (token, list(args)))


def _git_env() -> dict:
    env = dict(os.environ)
    # 关掉可选锁：`git status` 一类命令默认可能刷新并写索引，这就破坏了"不改工作区/索引"。
    env["GIT_OPTIONAL_LOCKS"] = "0"
    # 永不提示凭据、永不分页（分页器会把输出挂住）。
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    return env


def run_readonly(
    args: Sequence[str],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> GitResult:
    """以只读方式执行一条 git 命令。

    * 白名单不通过 → `ReadOnlyViolation`（在**起进程之前**拒绝，零副作用）；
    * git 不可用 → `EnvironmentError_`（exit 3）；
    * 超时 → `EnvironmentError_`（exit 3）——超时绝不降级成"无冲突"。
    """
    ordered = list(args)
    _assert_read_only(ordered)
    binary = ensure_git_available()
    command = [binary, "--no-pager"] + ordered
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=_git_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise EnvironmentError_(
            "git 命令超时（%s 秒）：%r。超时不代表没有冲突，请调大 config 的 git.timeout_seconds "
            "或检查仓库是否被锁。" % (timeout, ordered)
        )
    except OSError as exc:
        raise EnvironmentError_("git 命令无法执行：%r（%s）" % (ordered, exc))
    return GitResult(
        args=ordered,
        returncode=completed.returncode,
        # 显式 utf-8：子进程解码不继承 `py -X utf8`（K8）。
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )
