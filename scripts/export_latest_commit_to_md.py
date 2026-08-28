#!/usr/bin/env python3
"""Export every file changed by a Git commit into one Markdown document."""

from __future__ import annotations

import argparse
import base64
import html
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


LANGUAGES = {
    ".css": "css",
    ".go": "go",
    ".htm": "html",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "jsx",
    ".md": "markdown",
    ".php": "php",
    ".ps1": "powershell",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "bash",
    ".sql": "sql",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str
    old_path: str | None = None


def run_git(*args: str) -> bytes:
    """Run Git and return raw stdout, preserving unusual file names."""
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("找不到 git 命令，请先安装 Git 并加入 PATH。") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "Git 命令执行失败。") from exc
    return result.stdout


def resolve_commit(commit: str) -> str:
    return run_git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()


def first_parent(commit: str) -> str | None:
    fields = run_git("rev-list", "--parents", "-n", "1", commit).decode().split()
    return fields[1] if len(fields) > 1 else None


def changed_files(commit: str, parent: str | None) -> list[ChangedFile]:
    args = [
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "-z",
        "--find-renames",
    ]
    if parent is None:
        args.extend(["--root", commit])
    else:
        # For a merge commit, "latest commit changes" means changes from its
        # first parent, matching the usual Git/GitHub presentation.
        args.extend([parent, commit])
    raw = run_git(*args)
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()

    files: list[ChangedFile] = []
    index = 0
    while index < len(fields):
        status = fields[index].decode("ascii")
        index += 1
        if status.startswith(("R", "C")):
            old_path = fields[index].decode("utf-8", errors="surrogateescape")
            path = fields[index + 1].decode("utf-8", errors="surrogateescape")
            index += 2
            files.append(ChangedFile(status=status, path=path, old_path=old_path))
        else:
            path = fields[index].decode("utf-8", errors="surrogateescape")
            index += 1
            files.append(ChangedFile(status=status, path=path))
    return files


def blob_content(
    commit: str, parent: str | None, changed_file: ChangedFile
) -> bytes:
    if changed_file.status.startswith("D"):
        # A deleted file is absent from the commit, so export its last content.
        if parent is None:
            raise RuntimeError("根提交中出现了无法读取的删除文件。")
        return run_git("cat-file", "blob", f"{parent}:{changed_file.path}")
    return run_git("cat-file", "blob", f"{commit}:{changed_file.path}")


def markdown_fence(content: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def language_for(path: str) -> str:
    filename = Path(path).name.lower()
    if filename in {"dockerfile", "containerfile"}:
        return "dockerfile"
    return LANGUAGES.get(Path(path).suffix.lower(), "text")


def describe_change(changed_file: ChangedFile) -> str | None:
    kind = changed_file.status[:1]
    if kind == "D":
        return "已删除；下方为删除前的内容。"
    if kind == "R":
        return f"由 `{changed_file.old_path}` 重命名。"
    if kind == "C":
        return f"由 `{changed_file.old_path}` 复制。"
    return None


def render_markdown(
    commit: str, parent: str | None, files: list[ChangedFile]
) -> str:
    subject = run_git("log", "-1", "--format=%s", commit).decode("utf-8", errors="replace").strip()
    lines = [
        "# 最新 Git 提交的改动文件",
        "",
        f"- 提交：`{commit}`",
        f"- 说明：{subject}",
        f"- 文件数：{len(files)}",
        "",
    ]

    for changed_file in files:
        safe_path = html.escape(changed_file.path, quote=False)
        lines.extend([f"## <code>{safe_path}</code>", ""])
        description = describe_change(changed_file)
        if description:
            lines.extend([f"> {description}", ""])

        data = blob_content(commit, parent, changed_file)
        try:
            if b"\0" in data:
                raise ValueError("NUL byte indicates binary content")
            content = data.decode("utf-8-sig")
        except (UnicodeDecodeError, ValueError):
            content = base64.b64encode(data).decode("ascii")
            content = "\n".join(
                content[index : index + 76]
                for index in range(0, len(content), 76)
            )
            lines.extend(
                [
                    f"> 二进制或非 UTF-8 文件，大小为 {len(data)} 字节；下方为 Base64 编码。",
                    "",
                ]
            )
            language = "base64"
        else:
            language = language_for(changed_file.path)

        fence = markdown_fence(content)
        lines.append(f"{fence}{language}")
        lines.append(content.rstrip("\r\n"))
        lines.extend([fence, ""])

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将指定 Git 提交（默认 HEAD）涉及的全部文件内容汇总为 Markdown。"
    )
    parser.add_argument(
        "-c",
        "--commit",
        default="HEAD",
        help="要导出的提交（默认：HEAD）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("latest_commit_files.md"),
        help="输出文件（默认：latest_commit_files.md；使用 - 输出到终端）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        commit = resolve_commit(args.commit)
        parent = first_parent(commit)
        files = changed_files(commit, parent)
        markdown = render_markdown(commit, parent, files)
    except (RuntimeError, IndexError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if str(args.output) == "-":
        sys.stdout.write(markdown)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8", newline="\n")
        print(f"已导出 {len(files)} 个文件到 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
