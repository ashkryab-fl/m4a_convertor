"""Build a standalone executable on the current OS (Python and FFmpeg included)."""
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent


def package_macos(executable):
    """Package the existing frozen binary with a signed native Finder launcher."""
    bundle = ROOT / "build" / "macos-package" / "M4A Converter.app"
    if bundle.exists():
        shutil.rmtree(bundle)
    executable_dir = bundle / "Contents" / "MacOS"
    executable_dir.mkdir(parents=True)
    shutil.copy2(executable, executable_dir / "M4AConverterServer")
    launcher = executable_dir / "M4AConverter"
    subprocess.run(["/usr/bin/xcrun", "clang", "-arch", platform.machine(),
                    "-mmacosx-version-min=11.0", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-framework", "CoreFoundation", str(ROOT / "macos_launcher.c"),
                    "-o", str(launcher)], check=True)
    launcher.chmod(0o755)
    with (bundle / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleName": "M4A Converter", "CFBundleDisplayName": "M4A Converter",
                      "CFBundleIdentifier": "local.m4a.converter", "CFBundleExecutable": "M4AConverter",
                      "CFBundlePackageType": "APPL", "CFBundleVersion": "1.0.1",
                      "CFBundleShortVersionString": "1.0.1", "LSMinimumSystemVersion": "11.0",
                      "LSUIElement": True, "NSHighResolutionCapable": True}, stream)
    subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    destination = ROOT / "dist" / bundle.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(bundle, destination)
    bundle = destination
    archive = ROOT / "dist" / f"M4A-Converter-macOS-{platform.machine()}.zip"
    subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                    str(bundle), str(archive)], check=True)
    # A disk image preserves the bundle layout and executable permissions even when
    # an external service treats uploaded .app bundles as ordinary directories.
    staging = ROOT / "build" / "dmg"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(bundle, staging / bundle.name, copy_function=shutil.copy2)
    (staging / "Applications").symlink_to("/Applications", target_is_directory=True)
    target_mac = "Apple Silicon (M1 и новее)" if platform.machine() == "arm64" else "Intel"
    (staging / "Прочитайте перед запуском.txt").write_text(
        f"M4A Converter — Mac с {target_mac}.\n\n"
        "1. Перетащите M4A Converter.app в Applications.\n"
        "2. Откройте приложение из Applications двойным щелчком.\n"
        "3. Если macOS блокирует неизвестного разработчика, после попытки запуска\n"
        "   откройте Системные настройки → Конфиденциальность и безопасность\n"
        "   и нажмите Всё равно открыть (Open Anyway) для M4A Converter.\n\n"
        "Python, FFmpeg и интерфейс уже внутри. Интернет не нужен.\n"
        "Для остановки используйте кнопку Закрыть конвертер в браузере.\n"
        "Приложение имеет локальную подпись; Developer ID и нотариализации Apple нет.\n",
        encoding="utf-8")
    disk_image = ROOT / "dist" / f"M4A-Converter-macOS-{platform.machine()}.dmg"
    subprocess.run(["/usr/bin/hdiutil", "create", "-ov", "-format", "UDZO", "-fs", "HFS+",
                    "-volname", "M4A Converter", "-srcfolder", str(staging), str(disk_image)], check=True)
    print(f"\nГотово: {bundle}\nФайл для передачи: {disk_image}\nАрхив: {archive}")


def main():
    if sys.platform not in ("darwin", "win32"):
        raise SystemExit("Сборка приложения поддерживается на macOS и Windows.")
    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
               "--noupx", "--name", "M4AConverter", "--distpath", str(ROOT / "dist"),
               "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
               "--add-data", f"{ROOT / 'templates'}:templates",
               "--add-data", f"{ROOT / 'static'}:static",
               "--add-binary", f"{ffmpeg}:ffmpeg",
               "--windowed" if sys.platform == "win32" else "--console", str(ROOT / "app.py")]
    subprocess.run(command, cwd=ROOT, check=True)
    if sys.platform == "darwin":
        package_macos(ROOT / "dist" / "M4AConverter")
    else:
        print(f"\nГотово: {ROOT / 'dist' / 'M4AConverter.exe'}")


if __name__ == "__main__":
    main()
