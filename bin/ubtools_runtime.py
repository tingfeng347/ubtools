"""Shared bounded I/O and confirmation for the mirror and AI commands."""

import json
import os
import shlex
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


def text(zh, en):
    lang = (
        os.environ.get("UBTOOLS_LANG")
        or os.environ.get("LC_ALL")
        or os.environ.get("LANG", "")
    )
    return zh if "zh" in lang else en


def fetch(url, timeout=10, limit=4 * 1024 * 1024, headers=None, partial=False):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Expected an HTTP(S) URL without credentials")
    request = urllib.request.Request(
        url, headers={"User-Agent": "ubtools/1", **(headers or {})}
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if (
            parsed.scheme == "https"
            and urllib.parse.urlsplit(response.url).scheme != "https"
        ):
            raise ValueError("HTTPS download redirected to insecure transport")
        data = bytearray()
        while len(data) < limit:
            if time.monotonic() - started > timeout:
                raise TimeoutError("download timed out")
            chunk = response.read(min(65536, limit - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if not partial and len(data) == limit and response.read(1):
            raise ValueError("download exceeded size limit")
        return bytes(data)


def run(argv, timeout=10, **kwargs):
    return subprocess.run(
        [str(x) for x in argv],
        timeout=timeout,
        check=kwargs.pop("check", False),
        **kwargs,
    )


def command(argv):
    print("> " + shlex.join([str(x) for x in argv]), flush=True)


def confirm(message, yes=False):
    if yes:
        return True
    try:
        if os.isatty(0):
            answer = input(message + " [y/N] ")
        else:
            try:
                with open("/dev/tty", "r+") as tty:
                    tty.write(message + " [y/N] ")
                    tty.flush()
                    answer = tty.readline().strip()
            except OSError:
                answer = input(message + " [y/N] ")
        return answer.lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".ubtools-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
            os.fchmod(file.fileno(), mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2).encode())


def within(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False
