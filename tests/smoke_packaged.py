"""Exercise the standalone binary without Python/FFmpeg on the child process PATH."""
import argparse
import io
import json
import os
from pathlib import Path
import random
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import wave
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="m4a-standalone-") as temporary:
        root = Path(temporary)
        executable = root / args.executable.name
        shutil.copy2(args.executable, executable)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PATH"] = "/usr/bin:/bin" if os.name != "nt" else os.environ["SystemRoot"] + "\\System32"
        environment["IMAGEIO_FFMPEG_EXE"] = str(root / "ffmpeg-that-does-not-exist")
        process = subprocess.Popen([str(executable), "--no-browser", "--port", str(port)],
                                   cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"

        def request(path, method="GET", data=None, content_type=None, token=None):
            headers = {"X-Local-Token": token} if token else {}
            if content_type:
                headers["Content-Type"] = content_type
            with urlopen(Request(base + path, data=data, headers=headers, method=method), timeout=15) as response:
                return response.read()

        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    html = request("/").decode()
                    break
                except URLError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Standalone startup failed: " + process.communicate(timeout=5)[0].decode(errors="replace"))
                    time.sleep(0.1)
            assert 'lang="ru"' in html
            assert 'id="stop-converter"' in html
            assert request("/static/app.js")
            assert request("/static/style.css")
            token = re.search(r'name="local-token" content="([^"]+)"', html)[1]
            assert json.loads(request("/health"))["desktop"] is True
            duplicate = subprocess.run([str(executable), "--no-browser", "--port", str(port)],
                                       cwd=root, env=environment, capture_output=True, timeout=30)
            assert duplicate.returncode == 0, duplicate.stdout + duplicate.stderr
            assert process.poll() is None
            audio = io.BytesIO()
            rng = random.Random(2026)
            with wave.open(audio, "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(44100)
                output.writeframes(b"".join(struct.pack("<hh", rng.randint(-10000, 10000), rng.randint(-10000, 10000))
                                            for _ in range(44100 * 2)))
            identifiers = []
            for bitrate in (64, 320):
                boundary = "m4a-smoke-test-boundary"
                body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"bitrate\"\r\n\r\n{bitrate}\r\n"
                        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"track.wav\"\r\n"
                        "Content-Type: audio/wav\r\n\r\n").encode() + audio.getvalue() + f"\r\n--{boundary}--\r\n".encode()
                job = json.loads(request("/api/jobs", "POST", body, f"multipart/form-data; boundary={boundary}", token))
                identifiers.append(job["id"])
            deadline = time.monotonic() + 20
            while True:
                jobs = json.loads(request("/api/jobs", token=token))["jobs"]
                assert not any(job["status"] == "error" for job in jobs), jobs
                if len(jobs) == 2 and all(job["status"] == "done" for job in jobs):
                    break
                assert time.monotonic() < deadline, jobs
                time.sleep(0.1)
            outputs = [request(f"/api/jobs/{identifier}/download", token=token) for identifier in identifiers]
            for output in outputs:
                assert output[4:8] == b"ftyp" and b"mp4a" in output
            assert len(outputs[1]) > len(outputs[0]) * 2
            archive = request("/api/archive?ids=" + ",".join(identifiers), token=token)
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                assert bundle.namelist() == ["track.m4a", "track (2).m4a"]
                assert [bundle.read(name) for name in bundle.namelist()] == outputs
            request("/api/shutdown", "POST", b"", token=token)
            assert process.wait(timeout=15) == 0
            logs = process.communicate(timeout=5)[0].decode(errors="replace")
            assert "Exception in thread" not in logs and "Traceback" not in logs, logs
            print("Standalone binary: startup, bundled assets/FFmpeg, repeat launch, two bitrates, downloads, ZIP and shutdown OK.")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()


if __name__ == "__main__":
    main()
