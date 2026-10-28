"""Local AAC/M4A conversion. No cloud services or shell commands."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
import argparse
import errno
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from urllib.request import urlopen

from flask import Flask, abort, jsonify, render_template, request, send_file
import imageio_ffmpeg
from werkzeug.exceptions import HTTPException

BITRATES = (64, 96, 128, 160, 192, 256, 320)
MAX_FILE_BYTES = 2 * 1024**3
RETENTION_SECONDS = 60 * 60
TERMINAL = {"done", "error", "cancelled"}
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
BUNDLE_ROOT = Path(__file__).resolve().parent


def display_name(filename):
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip(" .")
    return name[:180] or "audio"


@dataclass
class Job:
    id: str
    name: str
    bitrate: int
    source_size: int
    folder: Path
    status: str = "queued"
    progress: int = 0
    error: str = ""
    output_size: int = 0
    finished_at: float = 0
    hidden: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen | None = None

    @property
    def output_name(self):
        return f"{Path(self.name).stem or 'audio'}.m4a"

    @property
    def output(self):
        return self.folder / "output.m4a"

    def public(self):
        return {key: getattr(self, key) for key in
                ("id", "name", "bitrate", "source_size", "status", "progress", "error", "output_size")} | {
                    "output_name": self.output_name}


class ConversionStore:
    def __init__(self, ffmpeg=None):
        if ffmpeg:
            self.ffmpeg = ffmpeg
        elif getattr(sys, "frozen", False):
            # Always use the embedded encoder, even on a computer with no FFmpeg installation.
            self.ffmpeg = str(next((BUNDLE_ROOT / "ffmpeg").glob("ffmpeg*")))
        else:
            self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.temporary = tempfile.TemporaryDirectory(prefix="m4a-converter-")
        self.root = Path(self.temporary.name)
        self.jobs = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio")

    def cleanup(self):
        with self.lock:
            expired = [key for key, job in self.jobs.items()
                       if job.finished_at and time.time() - job.finished_at > RETENTION_SECONDS]
            for key in expired:
                shutil.rmtree(self.jobs.pop(key).folder, ignore_errors=True)

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job.cancelled.set()
                if job.process and job.process.poll() is None:
                    job.process.terminate()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.temporary.cleanup()

    def convert(self, job):
        source = job.folder / "source"
        try:
            with self.lock:
                if job.cancelled.is_set():
                    return
                job.status = "converting"
            # Probe with the bundled executable; a separate ffprobe install is unnecessary.
            probe = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-protocol_whitelist", "file,pipe", "-i", str(source)],
                capture_output=True, timeout=30, creationflags=CREATE_FLAGS,
            )
            details = probe.stderr.decode("utf-8", errors="replace")
            match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", details)
            duration = (int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])) if match else 0
            command = [self.ffmpeg, "-nostdin", "-hide_banner", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source),
                       "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", f"{job.bitrate}k",
                       "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(job.output)]
            with (job.folder / "ffmpeg.log").open("wb") as log:
                with self.lock:
                    if job.cancelled.is_set():
                        return
                    job.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log,
                                                   text=True, encoding="utf-8", errors="replace",
                                                   creationflags=CREATE_FLAGS)
                for line in job.process.stdout:
                    if line.startswith("out_time_us=") and duration:
                        value = line.partition("=")[2].strip()
                        if value.isdigit():
                            with self.lock:
                                job.progress = min(99, int(int(value) / 1_000_000 / duration * 100))
                job.process.stdout.close()
                code = job.process.wait()
            with self.lock:
                if job.cancelled.is_set():
                    return
                if code != 0 or not job.output.exists() or job.output.stat().st_size == 0:
                    job.status = "error"
                    job.error = "Не удалось прочитать аудио. Файл повреждён, не содержит аудиодорожки или формат не поддерживается."
                else:
                    job.output_size = job.output.stat().st_size
                    job.progress = 100
                    job.status = "done"
        except (OSError, subprocess.SubprocessError):
            with self.lock:
                if not job.cancelled.is_set():
                    job.status = "error"
                    job.error = "Ошибка запуска FFmpeg или записи файла. Проверьте свободное место и перезапустите конвертер."
        finally:
            with self.lock:
                job.process = None
                job.finished_at = time.time()
                if job.cancelled.is_set():
                    job.status = "cancelled"
                if job.status != "done":
                    job.output.unlink(missing_ok=True)
            source.unlink(missing_ok=True)
            (job.folder / "ffmpeg.log").unlink(missing_ok=True)
            with self.lock:
                if job.hidden:
                    self.jobs.pop(job.id, None)
                    shutil.rmtree(job.folder, ignore_errors=True)


def create_app(ffmpeg=None, shutdown=None):
    app = Flask(__name__, template_folder=str(BUNDLE_ROOT / "templates"),
                static_folder=str(BUNDLE_ROOT / "static"))
    app.config.update(MAX_CONTENT_LENGTH=MAX_FILE_BYTES + 1024 * 1024,
                      TRUSTED_HOSTS=["localhost", "127.0.0.1"])
    store = ConversionStore(ffmpeg)
    token = secrets.token_urlsafe(32)
    app.extensions["conversions"] = store

    @app.before_request
    def protect_local_api():
        if request.path.startswith("/api/"):
            supplied = request.headers.get("X-Local-Token") or request.args.get("token", "")
            if not secrets.compare_digest(supplied, token):
                abort(403, description="Обновите страницу конвертера и попробуйте снова.")
            store.cleanup()

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    @app.errorhandler(HTTPException)
    def api_error(error):
        message = error.description
        if error.code == 413:
            message = "Файл слишком большой. Максимальный размер — 2 ГБ."
        elif not re.search(r"[А-Яа-яЁё]", message):
            message = {
                400: "Некорректный запрос.",
                403: "Доступ запрещён. Обновите страницу конвертера.",
                404: "Страница или файл не найдены.",
                405: "Это действие не поддерживается.",
                429: "Слишком много запросов. Попробуйте немного позже.",
                500: "Ошибка сервера. Перезапустите конвертер.",
                503: "Сервер временно недоступен. Попробуйте снова.",
            }.get(error.code, "Не удалось выполнить запрос.")
        return jsonify(error=message), error.code

    @app.get("/")
    def index():
        return render_template("index.html", token=token, desktop=shutdown is not None)

    @app.get("/health")
    def health():
        return jsonify(application="m4a-converter", desktop=shutdown is not None)

    @app.post("/api/shutdown")
    def stop_converter():
        if shutdown is None:
            abort(404, description="Закройте окно запуска, чтобы остановить конвертер.")
        threading.Timer(0.5, shutdown).start()
        return jsonify(stopped=True)

    @app.get("/api/jobs")
    def list_jobs():
        with store.lock:
            return jsonify(jobs=[job.public() for job in store.jobs.values() if not job.hidden])

    @app.post("/api/jobs")
    def upload():
        try:
            bitrate = int(request.form.get("bitrate", "192"))
        except ValueError:
            abort(400, description="Некорректное качество аудио.")
        if bitrate not in BITRATES:
            abort(400, description="Некорректное качество аудио.")
        file = request.files.get("file")
        if file is None or not file.filename:
            abort(400, description="Выберите аудиофайл.")
        with store.lock:
            if len(store.jobs) >= 100:
                abort(429, description="Очередь заполнена. Перезапустите конвертер или подождите, пока старые результаты будут удалены.")
            identifier = secrets.token_hex(16)
            folder = store.root / identifier
            folder.mkdir()
            try:
                file.save(folder / "source")
                size = (folder / "source").stat().st_size
                if not size:
                    abort(400, description="Файл пустой.")
                if size > MAX_FILE_BYTES:
                    abort(413)
                job = Job(identifier, display_name(file.filename), bitrate, size, folder)
                store.jobs[identifier] = job
                store.executor.submit(store.convert, job)
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            return jsonify(job.public()), 202

    def find_job(identifier):
        job = store.jobs.get(identifier)
        if not job:
            abort(404, description="Файл больше недоступен. Результаты хранятся один час; добавьте оригинал повторно.")
        return job

    @app.delete("/api/jobs/<identifier>")
    def cancel(identifier):
        with store.lock:
            job = find_job(identifier)
            job.hidden = True
            if job.status not in TERMINAL:
                job.cancelled.set()
                job.status = "cancelled"
                if job.process and job.process.poll() is None:
                    job.process.terminate()
            elif job.finished_at:
                store.jobs.pop(identifier, None)
                shutil.rmtree(job.folder, ignore_errors=True)
            return jsonify(job.public())

    @app.get("/api/jobs/<identifier>/download")
    def download(identifier):
        with store.lock:
            job = find_job(identifier)
            if job.status != "done":
                abort(409, description="Конвертация ещё не завершена.")
            return send_file(job.output, mimetype="audio/mp4", as_attachment=True,
                             download_name=job.output_name, conditional=False)

    @app.get("/api/archive")
    def archive():
        identifiers = list(dict.fromkeys(request.args.get("ids", "").split(",")))
        if not identifiers or not identifiers[0] or len(identifiers) > 100:
            abort(400, description="Выберите готовые файлы.")
        # Spool to disk for large batches, keeping memory use bounded.
        bundle = tempfile.SpooledTemporaryFile(max_size=8 * 1024**2, mode="w+b")
        try:
            with store.lock, zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zip_file:
                used = set()
                for identifier in identifiers:
                    job = find_job(identifier)
                    if job.status != "done":
                        abort(409, description="Не все файлы готовы.")
                    name = job.output_name
                    suffix = 2
                    while name.casefold() in used:
                        name = f"{Path(job.output_name).stem} ({suffix}).m4a"
                        suffix += 1
                    used.add(name.casefold())
                    zip_file.write(job.output, name)
            bundle.seek(0)
            response = send_file(bundle, mimetype="application/zip", as_attachment=True,
                                 download_name="m4a-audio.zip", conditional=False)
            response.call_on_close(bundle.close)
            return response
        except Exception:
            bundle.close()
            raise

    return app


def main():
    from waitress import create_server
    parser = argparse.ArgumentParser(description="Локальный M4A-конвертер")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--desktop", action="store_true", help="Запуск отдельного приложения")
    args = parser.parse_args()
    desktop = args.desktop or getattr(sys, "frozen", False)
    stopped = threading.Event()
    url = f"http://127.0.0.1:{args.port}"
    if desktop:
        # A second launch opens the running converter instead of starting another queue.
        try:
            with urlopen(f"{url}/health", timeout=1) as response:
                existing = json.load(response)
            if existing.get("application") == "m4a-converter" and existing.get("desktop"):
                if not args.no_browser:
                    webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
    app = create_app(shutdown=stopped.set if desktop else None)
    server = None
    try:
        try:
            server = create_server(app, host="127.0.0.1", port=args.port, threads=4,
                                   max_request_body_size=MAX_FILE_BYTES + 1024 * 1024)
        except OSError as error:
            if not desktop or error.errno not in (errno.EADDRINUSE, 10048):
                raise
            server = create_server(app, host="127.0.0.1", port=0, threads=4,
                                   max_request_body_size=MAX_FILE_BYTES + 1024 * 1024)
        url = f"http://127.0.0.1:{server.effective_port}"
        print(f"\nM4A-конвертер: {url}\nОстановить: Ctrl+C. Файлы обрабатываются только на этом компьютере.\n", flush=True)
        if not args.no_browser:
            threading.Timer(0.5, webbrowser.open, args=(url,)).start()
        if desktop:
            def serve():
                try:
                    server.run()
                except Exception:
                    if not stopped.is_set():
                        raise
                finally:
                    stopped.set()
            threading.Thread(target=serve, name="local-server", daemon=True).start()
            stopped.wait()
        else:
            server.run()
    except OSError as error:
        parser.exit(1, f"Не удалось запустить сервер: {error}\nПопробуйте другой порт: python launch.py --port 8766\n")
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        if server:
            server.close()
        app.extensions["conversions"].close()


if __name__ == "__main__":
    main()
