import io
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile

import imageio_ffmpeg
from app import create_app, RETENTION_SECONDS


class ConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = tempfile.TemporaryDirectory(prefix="m4a-test-")
        cls.sample_root = Path(cls.samples.name)
        cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for extension in ("wav", "mp3", "flac", "ogg", "m4a"):
            subprocess.run([cls.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "anoisesrc=d=3:c=white:r=44100:a=0.15:s=11",
                            "-f", "lavfi", "-i", "anoisesrc=d=3:c=white:r=44100:a=0.15:s=22",
                            "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]", "-map", "[a]",
                            str(cls.sample_root / f"sample.{extension}")], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.samples.cleanup()

    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self.store = self.app.extensions["conversions"]
        html = self.client.get("/").get_data(as_text=True)
        self.token = re.search(r'name="local-token" content="([^"]+)"', html)[1]
        self.headers = {"X-Local-Token": self.token}

    def tearDown(self):
        self.store.close()

    def upload(self, extension="wav", bitrate=192, name=None, content=None):
        source = content if content is not None else (self.sample_root / f"sample.{extension}").read_bytes()
        response = self.client.post("/api/jobs", headers=self.headers,
                                    data={"file": (io.BytesIO(source), name or f"sample.{extension}"),
                                          "bitrate": str(bitrate)})
        self.assertEqual(response.status_code, 202, response.get_json())
        identifier = response.get_json()["id"]
        response.close()
        # The real WSGI server owns this stream; the Flask test client leaves it to its caller.
        response.request.environ["wsgi.input"].close()
        return identifier

    def wait(self, identifier):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with self.store.lock:
                job = self.store.jobs[identifier]
                if job.finished_at:
                    return job
            time.sleep(0.03)
        self.fail("Conversion timed out")

    def inspect(self, file):
        result = subprocess.run([self.ffmpeg, "-hide_banner", "-i", str(file)], capture_output=True)
        return result.stderr.decode(errors="replace")

    def test_real_formats_produce_decodable_aac_m4a(self):
        identifiers = [self.upload(extension) for extension in ("wav", "mp3", "flac", "ogg", "m4a")]
        for identifier in identifiers:
            with self.subTest(identifier=identifier):
                job = self.wait(identifier)
                self.assertEqual(job.status, "done", job.error)
                self.assertEqual(job.progress, 100)
                self.assertFalse((job.folder / "source").exists())
                inspection = self.inspect(job.output)
                self.assertIn("Audio: aac", inspection)
                self.assertIn("44100 Hz, stereo", inspection)
                self.assertIn("Duration: 00:00:03", inspection)
                subprocess.run([self.ffmpeg, "-v", "error", "-i", str(job.output),
                                "-f", "null", "-"], check=True, capture_output=True)
                response = self.client.get(f"/api/jobs/{identifier}/download", headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "audio/mp4")
                self.assertEqual(response.data, job.output.read_bytes())
                response.close()

    def test_quality_changes_bitrate_and_size(self):
        low = self.wait(self.upload(bitrate=64))
        high = self.wait(self.upload(bitrate=320))
        self.assertEqual(low.status, "done")
        self.assertEqual(high.status, "done")
        self.assertGreater(high.output_size, low.output_size * 2)
        for job in (low, high):
            details = self.inspect(job.output)
            actual = int(re.search(r"Audio: aac[^\n]*, (\d+) kb/s", details)[1])
            self.assertLess(abs(actual - job.bitrate), job.bitrate * 0.2)

    def test_zip_preserves_duplicate_and_unicode_names(self):
        ids = [self.upload(name="пісня.wav"), self.upload(name="пісня.flac")]
        for identifier in ids:
            self.assertEqual(self.wait(identifier).status, "done")
        response = self.client.get(f"/api/archive?ids={','.join(ids)}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["пісня.m4a", "пісня (2).m4a"])
            for identifier, name in zip(ids, archive.namelist()):
                self.assertEqual(archive.read(name), self.store.jobs[identifier].output.read_bytes())
        response.close()

    def test_invalid_audio_and_request_validation(self):
        job = self.wait(self.upload(content=b"not an audio file"))
        self.assertEqual(job.status, "error")
        self.assertFalse(job.output.exists())
        response = self.client.get(f"/api/jobs/{job.id}/download", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        for data in ({"bitrate": "invalid"}, {"bitrate": "999"}, {}):
            self.assertEqual(self.client.post("/api/jobs", data=data, headers=self.headers).status_code, 400)
        response = self.client.post("/api/jobs", headers=self.headers,
                                    data={"file": (io.BytesIO(b""), "empty.wav")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/archive", headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get("/api/jobs/unknown/download", headers=self.headers).status_code, 404)

    def test_local_api_requires_token_and_rejects_foreign_host(self):
        self.assertEqual(self.client.get("/api/jobs").status_code, 403)
        self.assertEqual(self.client.post("/api/jobs").status_code, 403)
        self.assertEqual(self.client.get("/", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(self.client.get("/api/jobs", headers=self.headers).status_code, 200)

    def test_queued_cancellation_and_clear(self):
        gate = threading.Event()
        blocker = self.store.executor.submit(gate.wait, 5)
        try:
            identifier = self.upload()
            response = self.client.delete(f"/api/jobs/{identifier}", headers=self.headers)
            self.assertEqual(response.get_json()["status"], "cancelled")
            self.assertEqual(self.client.get("/api/jobs", headers=self.headers).get_json()["jobs"], [])
        finally:
            gate.set()
            blocker.result()
        self.store.executor.submit(lambda: None).result(timeout=5)
        self.assertNotIn(identifier, self.store.jobs)
        self.assertFalse((self.store.root / identifier).exists())

    def test_running_progress_and_cancellation(self):
        long_sample = self.sample_root / "long.mp3"
        subprocess.run([self.ffmpeg, "-v", "error", "-y", "-stream_loop", "199", "-i",
                        str(self.sample_root / "sample.mp3"), "-c", "copy", str(long_sample)], check=True)
        identifier = self.upload(name="long.mp3", content=long_sample.read_bytes())
        job = self.store.jobs[identifier]
        deadline = time.monotonic() + 15
        while job.progress == 0 and not job.finished_at and time.monotonic() < deadline:
            time.sleep(0.03)
        self.assertEqual(job.status, "converting")
        self.assertGreater(job.progress, 0)
        self.assertLess(job.progress, 100)
        response = self.client.delete(f"/api/jobs/{identifier}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.store.executor.submit(lambda: None).result(timeout=10)
        self.assertEqual(job.status, "cancelled")
        self.assertFalse(job.folder.exists())
        self.assertNotIn(identifier, self.store.jobs)

    def test_oversized_request_is_rejected(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 128
        response = self.client.post("/api/jobs", headers=self.headers,
                                    data={"file": (io.BytesIO(b"x" * 256), "large.wav")})
        self.assertEqual(response.status_code, 413)
        self.assertIn("2 ГБ", response.get_json()["error"])

    def test_completed_removal_and_expiration(self):
        job = self.wait(self.upload(name="../../пісня.wav"))
        self.assertEqual(job.output_name, "пісня.m4a")
        self.client.delete(f"/api/jobs/{job.id}", headers=self.headers)
        self.assertNotIn(job.id, self.store.jobs)
        job = self.wait(self.upload())
        job.finished_at = time.time() - RETENTION_SECONDS - 1
        self.client.get("/api/jobs", headers=self.headers)
        self.assertNotIn(job.id, self.store.jobs)
        self.assertFalse(job.folder.exists())

    def test_shutdown_requires_token_and_desktop_mode(self):
        self.assertEqual(self.client.post("/api/shutdown").status_code, 403)
        self.assertEqual(self.client.post("/api/shutdown", headers=self.headers).status_code, 404)
        stopped = threading.Event()
        desktop = create_app(shutdown=stopped.set)
        try:
            client = desktop.test_client()
            html = client.get("/").get_data(as_text=True)
            self.assertIn('id="stop-converter"', html)
            token = re.search(r'name="local-token" content="([^"]+)"', html)[1]
            self.assertEqual(client.post("/api/shutdown").status_code, 403)
            self.assertFalse(stopped.is_set())
            response = client.post("/api/shutdown", headers={"X-Local-Token": token})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(stopped.wait(timeout=2))
        finally:
            desktop.extensions["conversions"].close()


if __name__ == "__main__":
    unittest.main()
