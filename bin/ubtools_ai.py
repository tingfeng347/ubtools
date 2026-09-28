"""Install/update AI clients through their official distribution channels."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ubtools_runtime import command, confirm, fetch, run, text, within

TOOLS = {
    "codex": {
        "package": "@openai/codex",
        "url": "https://chatgpt.com/codex/install.sh",
        "shell": "sh",
    },
    "claude": {
        "package": "@anthropic-ai/claude-code",
        "url": "https://claude.ai/install.sh",
        "shell": "bash",
    },
    "opencode": {
        "package": "opencode-ai",
        "url": "https://opencode.ai/install",
        "shell": "bash",
    },
}


@dataclass
class Installation:
    path: str = ""
    method: str = "missing"
    package: str = ""


def detect(name):
    home = Path.home()
    native = home / (".opencode/bin" if name == "opencode" else ".local/bin") / name
    found = shutil.which(name)
    # Installers cannot change this process's PATH; check their user locations too.
    if not found and native.is_file() and os.access(native, os.X_OK):
        found = str(native)
    if not found:
        return Installation()
    path = Path(found).resolve()
    value = str(path)
    if shutil.which("dpkg-query"):
        result = run(
            ["dpkg-query", "-S", value], timeout=3, capture_output=True, text=True
        )
        if result.returncode == 0 and ": " in result.stdout:
            package = result.stdout.split(": ", 1)[0].splitlines()[0]
            # Multiple owners or diversions need manual inspection, not a guessed update.
            if re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?", package):
                return Installation(found, "apt", package)
    if shutil.which("pacman"):
        result = run(
            ["pacman", "-Qoq", value], timeout=3, capture_output=True, text=True
        )
        if result.returncode == 0 and re.fullmatch(
            r"[a-z0-9][a-z0-9+_.-]*", result.stdout.strip()
        ):
            return Installation(found, "pacman", result.stdout.strip())
    if "/node_modules/" in value:
        method = "pnpm" if "/.pnpm/" in value else "bun" if "/.bun/" in value else "npm"
        return Installation(found, method, TOOLS[name]["package"])
    if "/Cellar/" in value or "/Caskroom/" in value:
        return Installation(found, "brew", "claude-code" if name == "claude" else name)
    native_roots = [
        home / ".local/share/codex",
        home / ".local/share/claude",
        home / ".opencode/bin",
    ]
    if path == native.resolve() or any(within(path, root) for root in native_roots):
        return Installation(found, "native")
    return Installation(found, "unmanaged")


def version(installation):
    if not installation.path:
        return "-", False
    try:
        result = run(
            [installation.path, "--version"], timeout=5, capture_output=True, text=True
        )
    except (OSError, subprocess.TimeoutExpired):
        return "version check failed/timed out", True
    output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.stdout).strip().splitlines()
    value = "".join(c for c in (output[0] if output else "-") if c.isprintable())[:100]
    return value, result.returncode != 0 or not output


def latest(name, timeout):
    package = urllib.parse.quote(TOOLS[name]["package"], safe="@")
    data = json.loads(
        fetch(f"https://registry.npmjs.org/{package}/latest", timeout=timeout)
    )
    value = data.get("version", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", value):
        raise ValueError("invalid published version metadata")
    return value


def plan(name, existing, action):
    method = existing.method
    package = existing.package
    if method in {"npm", "pnpm", "bun"}:
        verbs = {
            "npm": ["install", "--global"],
            "pnpm": ["add", "--global"],
            "bun": ["install", "--global"],
        }
        return [[method, *verbs[method], package + "@latest"]]
    if method == "apt":
        return [
            ["sudo", "apt-get", "update"],
            ["sudo", "apt-get", "install", "--only-upgrade", package],
        ]
    if method == "brew":
        return [["brew", "upgrade", *(["--cask"] if name == "claude" else []), package]]
    if method in {"unmanaged", "pacman"}:
        raise ValueError(
            f"{name}: {text('无法确定安装来源，请使用原安装工具更新', 'unrecognized installation; update with its original manager')}: {existing.path}"
        )
    if method == "native" and action == "update" and name != "codex":
        return (
            [[existing.path, "update"]]
            if name == "claude"
            else [[existing.path, "upgrade", "--method", "curl"]]
        )
    # The @installer marker is rendered as a download + a separate execution,
    # with no shell interpolation of remote contents or user-supplied arguments.
    return [
        [
            "@installer",
            TOOLS[name]["url"],
            TOOLS[name]["shell"],
            *(["latest"] if name == "claude" else []),
        ]
    ]


def display_plan(steps):
    for step in steps:
        if step[0] == "@installer":
            command(["curl", "-fL", step[1], "-o", "<installer-file>"])
            command([step[2], "<installer-file>", *step[3:]])
        else:
            command(step)


def execute(steps, timeout):
    for step in steps:
        if step[0] == "@installer":
            data = fetch(step[1], timeout=timeout, limit=2 * 1024 * 1024)
            if not data.startswith(b"#!") or b"\x00" in data:
                raise ValueError("official installer returned unexpected content")
            with tempfile.TemporaryDirectory(prefix="ub-ai-") as directory:
                script = Path(directory) / "install.sh"
                script.write_bytes(data)
                env = dict(os.environ)
                if "chatgpt.com/codex/" in step[1]:
                    # Ignore an inherited prerelease selector for a latest install.
                    env["CODEX_RELEASE"] = "latest"
                result = run([step[2], str(script), *step[3:]], timeout=600, env=env)
        else:
            result = run(step, timeout=600)
        if result.returncode:
            raise RuntimeError(f"installer/update failed (exit {result.returncode})")


def choose(action):
    fzf = shutil.which("fzf")
    if not fzf:
        raise ValueError("fzf unavailable; specify codex/claude/opencode or --all")
    candidates = [name for name in TOOLS if action == "install" or detect(name).path]
    if not candidates:
        print(
            text(
                "尚未安装 AI 工具；请运行 ub ai install。",
                "No clients installed; run ub ai install.",
            )
        )
        return []
    selected = run(
        [
            fzf,
            "--multi",
            "--layout=reverse",
            "--border",
            "--height=60%",
            "--header",
            "Tab: multi-select | Enter: select | Esc: exit",
        ],
        input="\n".join(candidates) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        timeout=None,
    )
    if selected.returncode in {1, 130}:
        return []
    if selected.returncode:
        raise RuntimeError(f"fzf failed (exit {selected.returncode})")
    return list(
        dict.fromkeys(
            name for name in selected.stdout.splitlines() if name in candidates
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ub ai",
        description=text(
            "管理 Codex、Claude Code 和 OpenCode。",
            "Manage Codex, Claude Code and OpenCode.",
        ),
    )
    sub = parser.add_subparsers(dest="action")
    for action in ["install", "update", "status", "doctor"]:
        item = sub.add_parser(action)
        item.add_argument("tools", nargs="*", choices=list(TOOLS))
        item.add_argument("--all", action="store_true")
        item.add_argument("--timeout", type=int, default=15)
        if action in {"install", "update"}:
            item.add_argument("--dry-run", action="store_true")
            item.add_argument("--yes", "-y", action="store_true")
        if action == "status":
            item.add_argument(
                "--latest",
                action="store_true",
                help="query latest npm publication versions",
            )
        if action == "doctor":
            item.add_argument("--offline", action="store_true")
    args = parser.parse_args(
        argv if argv is not None else (sys.argv[1:] or ["install"])
    )
    if not args.action:
        parser.print_help()
        return 0
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if args.all and args.tools:
        parser.error("use tool names or --all, not both")
    names = args.tools or list(TOOLS)
    if args.action in {"install", "update"} and not args.tools and not args.all:
        names = choose(args.action)
    failed = False
    if args.action in {"status", "doctor"}:
        for name in names:
            found = detect(name)
            current, bad_version = version(found)
            failed |= bad_version
            published = ""
            if args.action == "status" and args.latest:
                try:
                    published = f" npm-latest={latest(name, args.timeout)}"
                except (OSError, ValueError) as error:
                    published = f" latest-query-failed={type(error).__name__}"
                    failed = True
            print(
                f"{name:10} {current:28} {found.method:12} {found.path}{published}",
                flush=True,
            )
        if args.action == "doctor":
            for dependency in ["curl", "bash", "tar", "unzip"]:
                ok = bool(shutil.which(dependency))
                print(f"{'OK' if ok else 'FAIL'} dependency: {dependency}", flush=True)
                failed |= not ok
            if not args.offline:
                for name in names:
                    try:
                        fetch(
                            TOOLS[name]["url"],
                            timeout=args.timeout,
                            limit=2 * 1024 * 1024,
                        )
                        print(f"OK {name} official download endpoint", flush=True)
                    except (OSError, ValueError) as error:
                        print(
                            f"FAIL {name} download endpoint: {type(error).__name__}",
                            flush=True,
                        )
                        failed = True
        return int(failed)
    operations = []
    for name in names:
        found = detect(name)
        if args.action == "update" and not found.path:
            print(f"SKIP {name}: not installed")
            continue
        steps = plan(name, found, args.action)
        print(f"{name}: {found.method} → {args.action}", flush=True)
        display_plan(steps)
        operations.append((name, steps))
    if not operations or args.dry_run:
        return 0
    if not confirm(
        text("执行以上安装/更新操作？", "Apply these installations/updates?"), args.yes
    ):
        return 0
    for name, steps in operations:
        execute(steps, args.timeout)
        found = detect(name)
        current, bad = version(found)
        if not found.path or bad:
            raise RuntimeError(
                f"{name}: installation finished but version verification failed"
            )
        print(f"OK {name}: {current} ({found.path})", flush=True)
        print(text("登录/配置入口：", "Sign-in/configuration: ") + name)
        if shutil.which(name) != found.path:
            print(f"PATH: add {Path(found.path).parent} to your shell PATH")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
