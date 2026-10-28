"""Check the actual ZIP/DMG bundles through macOS Launch Services."""
import json
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def check_bundle(bundle):
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    launcher = bundle / "Contents" / "MacOS" / "M4AConverter"
    assert launcher.stat().st_mode & 0o111
    assert subprocess.check_output(["/usr/bin/file", str(launcher)]).find(b"Mach-O") >= 0
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    def read(path):
        with urlopen(base + path, timeout=1) as response:
            return response.read()

    def launch():
        subprocess.run(["/usr/bin/open", "-n", str(bundle), "--args", "--no-browser",
                        "--port", str(port)], check=True, timeout=20)

    token = None
    try:
        launch()
        deadline = time.monotonic() + 30
        while True:
            try:
                html = read("/").decode()
                break
            except URLError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Finder launch failed: {bundle}")
                time.sleep(0.1)
        token = re.search(r'name="local-token" content="([^"]+)"', html)[1]
        assert json.loads(read("/health")) == {"application": "m4a-converter", "desktop": True}
        launch()
        time.sleep(2)
        assert re.search(r'name="local-token" content="([^"]+)"', read("/").decode())[1] == token
        assert "Конвертировать" in html
        assert read("/static/app.js")
        print(f"Finder startup, native executable, signature, assets and repeat launch OK: {bundle}")
    finally:
        if token:
            with urlopen(Request(base + "/api/shutdown", data=b"", method="POST",
                                 headers={"X-Local-Token": token}), timeout=5):
                pass
            deadline = time.monotonic() + 10
            while True:
                try:
                    read("/health")
                except URLError:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Packaged server did not stop")
                time.sleep(0.1)


def main():
    with tempfile.TemporaryDirectory(prefix="package-smoke-", dir=ROOT / "build") as temporary:
        root = Path(temporary)
        archive_root = root / "zip"
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(ROOT / "dist" / f"M4A-Converter-macOS-{platform.machine()}.zip"),
                        str(archive_root)], check=True)
        check_bundle(archive_root / "M4A Converter.app")
        mount = root / "mounted"
        mount.mkdir()
        subprocess.run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount),
                        str(ROOT / "dist" / f"M4A-Converter-macOS-{platform.machine()}.dmg")], check=True)
        try:
            copied = root / "installed" / "M4A Converter.app"
            shutil.copytree(mount / copied.name, copied)
            check_bundle(copied)
        finally:
            subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], check=True)
    print("Both distribution formats passed. Downloaded-app Gatekeeper approval is still required.")


if __name__ == "__main__":
    main()
