"""Create the local environment once, then start the converter."""
import hashlib
from pathlib import Path
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Нужен Python 3.10 или новее: https://www.python.org/downloads/")
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    try:
        usable = python.exists() and subprocess.run(
            [str(python), "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        usable = False
    if not usable:
        print("Создание среды…", flush=True)
        venv.create(environment, with_pip=True, clear=True)
    requirements = root / "requirements.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = environment / ".requirements-hash"
    if not stamp.exists() or stamp.read_text() != digest:
        print("Установка зависимостей и FFmpeg (нужен интернет)…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        stamp.write_text(digest)
    with subprocess.Popen([str(python), str(root / "app.py"), *sys.argv[1:]], cwd=root) as server:
        try:
            return server.wait()
        except KeyboardInterrupt:
            # The terminal sends Ctrl+C to both processes. Let the server clean up its files.
            try:
                return server.wait(timeout=35)
            except subprocess.TimeoutExpired:
                server.terminate()
                try:
                    return server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
                    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Не удалось запустить конвертер: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)
