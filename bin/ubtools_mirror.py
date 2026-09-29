"""Measure Ubuntu mirrors and transactionally change Ubuntu source URIs."""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from ubtools_runtime import (
    atomic_write,
    command,
    confirm,
    fetch,
    run,
    save_json,
    text,
    within,
)

ARCHIVE = "https://archive.ubuntu.com/ubuntu"
PORTS = "https://ports.ubuntu.com/ubuntu-ports"
KEYRING = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
INDEX = "http://mirrors.ubuntu.com/mirrors.txt"


def normalize(url):
    value = urllib.parse.urlsplit(url)
    if (
        value.scheme not in {"http", "https"}
        or not value.hostname
        or value.username
        or value.password
        or value.query
        or value.fragment
    ):
        raise ValueError(
            "Mirror must be an HTTP(S) URL without credentials, query or fragment"
        )
    return url.rstrip("/")


def ubuntu_url(url, known):
    value = urllib.parse.urlsplit(url)
    if value.hostname == "security.ubuntu.com":
        return False  # Keep the separate official security source as configured.
    normalized = normalize(url)
    alternate = (
        "https:" if normalized.startswith("http:") else "http:"
    ) + normalized.split(":", 1)[1]
    return (
        normalized in known
        or alternate in known
        or (value.hostname or "").endswith(".archive.ubuntu.com")
        or value.hostname in {"archive.ubuntu.com", "ports.ubuntu.com"}
    )


@dataclass
class Source:
    path: Path
    original: bytes
    replacements: list
    suites: list

    def render(self, url):
        value = self.original.decode("utf-8")
        for start, end in sorted(self.replacements, reverse=True):
            value = value[:start] + url + value[end:]
        return value.encode()


def sources(apt_dir, known):
    """Track URI token spans so comments/options/keys/third-party stanzas survive."""
    paths = (
        [apt_dir / "sources.list"]
        + sorted((apt_dir / "sources.list.d").glob("*.list"))
        + sorted((apt_dir / "sources.list.d").glob("*.sources"))
    )
    result = []
    for path in paths:
        if not path.is_file():
            continue
        if not within(path.resolve(), apt_dir):
            raise ValueError(f"Source resolves outside APT directory: {path}")
        raw = path.read_bytes()
        value = raw.decode("utf-8")
        changes, suites = [], []
        if path.suffix == ".sources":
            for paragraph in re.finditer(r"(?:[^\r\n]+(?:\r?\n|$))+", value):
                fields, spans, field = {}, {}, ""
                offset = paragraph.start()
                for line in paragraph.group().splitlines(keepends=True):
                    match = re.match(
                        r"^([A-Za-z][A-Za-z-]*):[ \t]*(.*?)(?:\r?\n)?$", line
                    )
                    if match:
                        field = match[1].lower()
                        fields[field] = match[2]
                        token_offset = offset + match.start(2)
                        spans[field] = [
                            (token_offset + m.start(), token_offset + m.end(), m[0])
                            for m in re.finditer(r"\S+", match[2])
                        ]
                    elif line.startswith((" ", "\t")) and field:
                        fields[field] += " " + line.strip()
                        spans[field] += [
                            (offset + m.start(), offset + m.end(), m[0])
                            for m in re.finditer(r"\S+", line)
                        ]
                    elif not line.lstrip().startswith("#"):
                        field = ""
                    offset += len(line)
                if fields.get("enabled", "").lower() == "no":
                    continue
                if not set(fields.get("types", "").split()) & {"deb", "deb-src"}:
                    continue
                for start, end, url in spans.get("uris", []):
                    try:
                        eligible = ubuntu_url(url, known)
                    except ValueError:
                        continue
                    if eligible:
                        changes.append((start, end))
                        suites.extend(fields.get("suites", "").split())
        else:
            offset = 0
            for line in value.splitlines(keepends=True):
                match = re.match(
                    r"^\s*deb(?:-src)?\s+(?:\[[^\]]*\]\s+)?(\S+)\s+(\S+)", line
                )
                if match:
                    try:
                        eligible = ubuntu_url(match[1], known)
                    except ValueError:
                        eligible = False
                    if eligible:
                        changes.append((offset + match.start(1), offset + match.end(1)))
                        suites.append(match[2])
                offset += len(line)
        if changes:
            if path.is_symlink():
                raise ValueError(f"Source file is a symlink; edit it manually: {path}")
            if not suites or any(
                not re.fullmatch(r"[a-z][a-z0-9-]*", suite) for suite in suites
            ):
                raise ValueError(f"Unsupported suite in {path}; refusing to guess")
            result.append(Source(path, raw, changes, list(dict.fromkeys(suites))))
    if not result:
        raise ValueError("No recognized Ubuntu source entries found")
    return result


def architecture():
    if shutil.which("dpkg"):
        found = run(
            ["dpkg", "--print-architecture"], capture_output=True, text=True, timeout=3
        )
        if found.returncode == 0 and re.fullmatch(r"[a-z0-9]+", found.stdout.strip()):
            return found.stdout.strip()
    return {"x86_64": "amd64", "aarch64": "arm64", "i686": "i386"}.get(
        platform.machine(), platform.machine()
    )


def release(url, suite, args, directory):
    data = fetch(
        f"{url}/dists/{suite}/InRelease", timeout=args.timeout, limit=4 * 1024 * 1024
    )
    file = Path(directory) / (uuid.uuid4().hex + ".InRelease")
    file.write_bytes(data)
    checked = run(
        ["gpgv", "--keyring", str(args.keyring), str(file)],
        timeout=args.timeout,
        capture_output=True,
    )
    if checked.returncode:
        raise ValueError(f"{suite}: invalid Ubuntu archive signature")
    value = data.decode("utf-8")
    fields = dict(re.findall(r"^([A-Za-z-]+):[ \t]*(.*)$", value, re.MULTILINE))
    if fields.get("Suite") != suite:
        raise ValueError(f"{suite}: unexpected signed suite")
    if args.arch not in fields.get("Architectures", "").split():
        raise ValueError(f"{suite}: architecture {args.arch} unavailable")
    if (
        fields.get("Valid-Until")
        and parsedate_to_datetime(fields["Valid-Until"]).timestamp() <= time.time()
    ):
        raise ValueError(f"{suite}: signed release expired")
    checksums = {}
    section = re.search(r"^SHA256:\s*\n((?:[ \t]+[^\n]+\n)+)", value, re.MULTILINE)
    if section:
        for digest, size, path in re.findall(
            r"^\s+([a-f0-9]{64})\s+(\d+)\s+(\S+)\s*$", section[1], re.MULTILINE
        ):
            checksums[path] = (digest, int(size))
    for extension in ["xz", "gz", ""]:
        path = f"main/binary-{args.arch}/Packages" + (
            "." + extension if extension else ""
        )
        if path in checksums and checksums[path][1] > 0:
            return {
                "path": path,
                "checksum": checksums[path],
                "date": fields.get("Date", ""),
            }
    raise ValueError(f"{suite}: signed package index unavailable")


def measure(url, suites, reference, args, directory):
    result = {"url": url, "ok": False, "speed": 0, "error": ""}
    try:
        for suite in suites:
            info = release(url, suite, args, directory)
            expected = reference[suite]
            if (
                info["path"] != expected["path"]
                or info["checksum"] != expected["checksum"]
            ):
                raise ValueError(f"{suite}: not synchronized with official index")
        suite = next((s for s in suites if s.endswith("-updates")), suites[0])
        path = reference[suite]["path"]
        started = time.monotonic()
        data = fetch(
            f"{url}/dists/{suite}/{path}",
            timeout=args.timeout,
            limit=256 * 1024,
            headers={"Range": "bytes=0-262143"},
            partial=True,
        )
        elapsed = time.monotonic() - started
        expected_size = min(reference[suite]["checksum"][1], 256 * 1024)
        if len(data) != expected_size:
            raise ValueError("incomplete package-index sample")
        if (
            reference[suite]["checksum"][1] <= 256 * 1024
            and hashlib.sha256(data).hexdigest() != reference[suite]["checksum"][0]
        ):
            raise ValueError("package-index checksum mismatch")
        result.update(
            ok=True,
            speed=len(data) / max(elapsed, 0.001),
            seconds=elapsed,
            bytes=len(data),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        # Errors identify a phase, not full HTTP responses or credentials.
        result["error"] = (
            str(error) if isinstance(error, ValueError) else type(error).__name__
        )
    return result


def candidate_urls(args):
    args.catalog = set()
    default = PORTS if args.arch not in {"amd64", "i386"} else ARCHIVE
    if args.mirror:
        return list(dict.fromkeys(normalize(url) for url in args.mirror))
    result = [default]
    # The official geographic list can legitimately contain only the main
    # archive. Known university mirrors provide additional measurable choices.
    suffix = "ubuntu-ports" if default == PORTS else "ubuntu"
    fallback = [
        f"https://mirrors.tuna.tsinghua.edu.cn/{suffix}",
        f"https://mirrors.ustc.edu.cn/{suffix}",
    ]
    args.catalog.update(fallback)
    if default == ARCHIVE:
        try:
            data = fetch(INDEX, timeout=args.timeout, limit=1024 * 1024).decode()
            for line in data.splitlines():
                try:
                    url = normalize(line.strip())
                except ValueError:
                    continue
                args.catalog.add(url)
                if (
                    not any(
                        url.split("://", 1)[1] == old.split("://", 1)[1]
                        for old in result
                    )
                    and len(result) < args.limit
                ):
                    result.append(url)
        except (OSError, ValueError):
            print(
                text(
                    "镜像列表获取失败，使用内置候选。",
                    "Mirror-list fetch failed; using built-in candidates.",
                ),
                file=sys.stderr,
            )
    for url in fallback:
        if url not in result and len(result) < args.limit:
            result.append(url)
    return result


def test_mirrors(args):
    if not shutil.which("gpgv") or not args.keyring.is_file():
        raise ValueError(
            "gpgv and the Ubuntu archive keyring are required for mirror verification"
        )
    candidates = candidate_urls(args)
    known = (
        set(candidates)
        | args.catalog
        | {
            ARCHIVE,
            PORTS,
            ARCHIVE.replace("https:", "http:"),
            PORTS.replace("https:", "http:"),
        }
    )
    public_known = args.state_dir.parent / "mirror-known.json"
    if public_known.is_file():
        known.update(json.loads(public_known.read_text()))
    # Previously selected mirror URLs remain recognizable for legacy .list files.
    for manifest in args.state_dir.glob("*/manifest.json"):
        try:
            known.add(json.loads(manifest.read_text())["mirror"])
        except (OSError, ValueError, KeyError):
            continue
    entries = sources(args.apt_dir, known)
    suites = list(dict.fromkeys(s for entry in entries for s in entry.suites))
    base = args.reference or (PORTS if args.arch not in {"amd64", "i386"} else ARCHIVE)
    if not args.json:
        print(
            text(
                "先验证官方索引，然后测速候选镜像…",
                "Verifying official indexes, then measuring candidate mirrors…",
            ),
            flush=True,
        )
    with tempfile.TemporaryDirectory(prefix="ub-mirror-") as directory:
        reference = {
            suite: release(normalize(base), suite, args, directory) for suite in suites
        }
        with ThreadPoolExecutor(max_workers=4) as executor:
            tasks = [
                executor.submit(measure, url, suites, reference, args, directory)
                for url in candidates
            ]
            results = []
            for task in as_completed(tasks):
                item = task.result()
                results.append(item)
                if not args.json:
                    print(
                        f"{text('正常' if item['ok'] else '失败', 'OK' if item['ok'] else 'FAIL'):4} {item['speed'] / 1024:10.1f} KiB/s  {item['url']}  {item['error']}",
                        flush=True,
                    )
    results.sort(key=lambda item: (not item["ok"], -item["speed"]))
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
    return entries, results


def validation_command(args):
    argv = [
        "apt-get",
        "-o",
        "APT::Update::Error-Mode=any",
        "-o",
        f"Acquire::http::Timeout={args.timeout}",
        "-o",
        f"Acquire::https::Timeout={args.timeout}",
        "-o",
        "Acquire::Retries=0",
    ]
    if args.apt_dir != Path("/etc/apt"):
        # Custom source directories use private indexes, never the host's APT state.
        for name in ["lists/partial", "cache/archives/partial"]:
            (args.state_dir / name).mkdir(parents=True, exist_ok=True)
        argv += [
            "-o",
            f"Dir::Etc::sourcelist={args.apt_dir / 'sources.list'}",
            "-o",
            f"Dir::Etc::sourceparts={args.apt_dir / 'sources.list.d'}",
            "-o",
            f"Dir::State::lists={args.state_dir / 'lists'}",
            "-o",
            f"Dir::Cache={args.state_dir / 'cache'}",
        ]
    return argv + ["update"]


def apply(entries, url, args):
    changed = [entry for entry in entries if entry.render(url) != entry.original]
    if not changed:
        print(
            text(
                "已经使用该镜像，无需修改。",
                "Already using this mirror; no changes needed.",
            )
        )
        return
    for entry in changed:
        print(f"{entry.path}: → {url}")
    if args.dry_run or not confirm(
        text("备份并切换以上 Ubuntu 源？", "Back up and switch these Ubuntu sources?"),
        args.yes,
    ):
        return
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.state_dir / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        backup = args.state_dir / (
            time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        )
        backup.mkdir(mode=0o700)
        records = []
        for i, entry in enumerate(changed):
            if entry.path.is_symlink() or entry.path.read_bytes() != entry.original:
                raise ValueError(f"Source changed during measurement: {entry.path}")
            mode = stat.S_IMODE(entry.path.stat().st_mode)
            atomic_write(backup / f"{i}.source", entry.original)
            records.append(
                {
                    "path": str(entry.path.relative_to(args.apt_dir)),
                    "backup": f"{i}.source",
                    "mode": mode,
                    "before": hashlib.sha256(entry.original).hexdigest(),
                    "after": hashlib.sha256(entry.render(url)).hexdigest(),
                }
            )
        manifest = {
            "apt_dir": str(args.apt_dir),
            "mirror": url,
            "files": records,
            "restored": False,
        }
        save_json(backup / "manifest.json", manifest)
        written = []
        try:
            for entry, record in zip(changed, records):
                atomic_write(entry.path, entry.render(url), record["mode"])
                written.append((entry, record))
            argv = validation_command(args)
            command(argv)
            result = run(argv, timeout=args.timeout * 8 + 30)
            if result.returncode:
                raise RuntimeError(
                    f"APT index validation failed (exit {result.returncode})"
                )
            public_known = args.state_dir.parent / "mirror-known.json"
            history = (
                json.loads(public_known.read_text()) if public_known.exists() else []
            )
            atomic_write(
                public_known,
                json.dumps(list(dict.fromkeys(history + [url]))).encode(),
                0o644,
            )
        except BaseException:
            for entry, record in written:
                atomic_write(entry.path, entry.original, record["mode"])
            manifest["restored"] = True
            save_json(backup / "manifest.json", manifest)
            print(
                text(
                    "换源失败，原源配置已恢复。",
                    "Switch failed; original source configuration restored.",
                ),
                file=sys.stderr,
            )
            raise
        print(text("切换完成，备份：", "Switched; backup: ") + str(backup))


def restore(args):
    manifests = sorted(args.state_dir.glob("*/manifest.json"), reverse=True)
    for path in manifests:
        data = json.loads(path.read_text())
        if not data.get("restored") and data.get("apt_dir") == str(args.apt_dir):
            break
    else:
        raise ValueError("No active mirror backup found for this APT directory")
    files = []
    for record in data["files"]:
        target = args.apt_dir / record["path"]
        saved = path.parent / record["backup"]
        if (
            target.is_symlink()
            or not within(target.resolve(), args.apt_dir)
            or not within(saved.resolve(), path.parent)
        ):
            raise ValueError("Invalid backup path")
        original = saved.read_bytes()
        if hashlib.sha256(original).hexdigest() != record["before"]:
            raise ValueError("Backup integrity check failed")
        current = target.read_bytes()
        if hashlib.sha256(current).hexdigest() != record["after"] and not args.force:
            raise ValueError(
                f"Source edited after switching: {target}; inspect or use --force"
            )
        files.append((target, original, current, record["mode"]))
        print(f"{target}: ← {saved}")
    if args.dry_run or not confirm(
        text("恢复以上镜像源备份？", "Restore this mirror backup?"), args.yes
    ):
        return
    with (args.state_dir / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        written = []
        try:
            for target, original, current, mode in files:
                if target.is_symlink() or target.read_bytes() != current:
                    raise ValueError(f"Source changed during restore: {target}")
                atomic_write(target, original, mode)
                written.append((target, original, current, mode))
        except BaseException:
            for target, original, current, mode in written:
                atomic_write(target, current, mode)
            raise
        data["restored"] = True
        save_json(path, data)
    print(
        text(
            "源配置已恢复；运行 ub update --refresh-index 更新索引。",
            "Source configuration restored; run ub update --refresh-index to refresh indexes.",
        )
    )


def main(argv=None):
    supplied_args = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="ub mirror",
        description=text(
            "测速、切换并恢复 Ubuntu 镜像源。",
            "Measure, switch and restore Ubuntu mirrors.",
        ),
    )
    parser.add_argument(
        "action", nargs="?", choices=["test", "auto", "restore"], default="test"
    )
    parser.add_argument(
        "--mirror", action="append", help="candidate URL; repeat to compare mirrors"
    )
    parser.add_argument("--timeout", type=int, default=10, help="timeout per request")
    parser.add_argument(
        "--limit", type=int, default=8, help="maximum candidates from the official list"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument(
        "--json", action="store_true", help="JSON measurement results (test only)"
    )
    parser.add_argument(
        "--force", action="store_true", help="restore despite subsequent source edits"
    )
    parser.add_argument("--apt-dir", type=Path, default=Path("/etc/apt"))
    parser.add_argument(
        "--state-dir", type=Path, default=Path("/var/lib/ubtools/mirror")
    )
    parser.add_argument("--keyring", type=Path, default=Path(KEYRING))
    parser.add_argument(
        "--reference", help="reference archive URL; default official Ubuntu archive"
    )
    parser.add_argument("--arch", default=architecture())
    args = parser.parse_args(supplied_args)
    # Bare `ub mirror` is the interactive flow: benchmark, then offer to switch.
    # Explicit `test` stays read-only for scripts and diagnostics.
    args.offer_switch = not supplied_args and not args.json
    args.keyring = args.keyring.resolve()
    args.apt_dir = args.apt_dir.resolve()
    args.state_dir = args.state_dir.resolve()
    if args.timeout < 1 or args.limit < 1:
        parser.error("--timeout and --limit must be positive")
    if not re.fullmatch(r"[a-z0-9]+", args.arch):
        parser.error("unsupported architecture")
    if args.json and args.action != "test":
        parser.error("--json is supported by test only")
    if (
        (args.action != "test" or args.offer_switch)
        and not args.dry_run
        and args.apt_dir == Path("/etc/apt")
        and os.geteuid() != 0
    ):
        # Elevate the concrete CLI operation; test and dry-run never request sudo.
        return run(
            [
                "sudo",
                sys.executable,
                str(Path(__file__).resolve()),
                *supplied_args,
            ],
            timeout=None,
        ).returncode
    if args.action == "restore":
        restore(args)
        return 0
    entries, results = test_mirrors(args)
    good = [item for item in results if item["ok"]]
    if not good:
        raise ValueError("No synchronized, signed and reachable mirror found")
    print(
        (text("最快可用镜像：", "Fastest usable mirror: ") + good[0]["url"])
        if not args.json
        else "",
        file=sys.stderr if args.json else sys.stdout,
    )
    if args.action == "auto" or args.offer_switch:
        if not shutil.which("apt-get"):
            raise ValueError("apt-get is required to validate a switch")
        apply(entries, good[0]["url"], args)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(text(f"错误：{error}", f"Error: {error}"), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
