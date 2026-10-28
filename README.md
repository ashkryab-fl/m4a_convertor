# Local M4A Converter

A small browser-based GUI for macOS and Windows. Add one or more files, choose a quality setting, and get separate `.m4a` files with AAC audio encoding.

## Launch

Ready-to-use files are in **`dist`**:

- **Mac with Apple Silicon (M1/M2/M3/M4, etc.):** To share via Google Drive, use the single file **`M4A-Converter-macOS-arm64.dmg`**. Open it, drag **`M4A Converter.app`** to **Applications**, then open the app from Applications with a double-click. Python, FFmpeg, and the interface are already included. No internet connection or manual dependency installation is required. Alternatively, use the ready-to-use **`M4A-Converter-macOS-arm64.zip`**: extract it with the Mac's built-in archive utility. Do not upload the `.app` itself to Drive as a folder: the service may not preserve executable permissions.
- **Mac, including Intel:** You can share only **`M4A-Converter-macOS.command`** and open it with a double-click. The file contains all the code and extracts it to `~/Library/Application Support/M4A Converter`; dependencies are installed automatically. An internet connection is required for the first setup.
- **Windows:** You can share only **`M4A-Converter-Windows.bat`** and open it with a double-click. The file contains all the code; the original project folder is not needed. It extracts the app to `%LOCALAPPDATA%\M4AConverter` and sets up Python and FFmpeg automatically. An internet connection is required for the first setup; subsequent launches work offline.

The browser opens automatically. Launching the app again opens the converter that is already running. To stop it, click **“Close converter”** in the top corner of the interface. Download any results you need first: stopping the app deletes temporary files. Closing the browser tab alone does not stop the converter.

The ready-to-use Mac build has been tested on this Apple Silicon Mac. On Intel, use the universal `.command` file or create a native build on an Intel Mac. The Windows launcher should be tested on Windows. The app is signed with a local ad hoc signature; distribution as a trusted macOS app requires an Apple Developer ID and notarization.

### If the downloaded Mac version won't open

Launching locally differs from launching after a download: macOS performs additional checks on apps from the internet. A `.dmg` preserves the app structure and executable permissions, but does not replace Developer ID signing and notarization.

After the first launch attempt, if macOS blocks an unidentified developer, open **System Settings → Privacy & Security → Open Anyway**, then confirm **Open** specifically for **M4A Converter**. This is a one-time permission for this app; subsequent launches can be done with a double-click. [Apple's instructions](https://support.apple.com/en-us/102445).

If the only message is **“The application … can’t be opened”** and there is no **Open Anyway** button, the cause cannot be determined from the message alone: check that you have the complete ready-to-use ZIP/DMG, extracted using the Mac's built-in tools, and that you chose the correct architecture. Version 1.0.1 uses a native Mach-O launcher instead of a shell script.

### Launching from the source folder

You don't need to install Python manually. The source folder also includes launchers:

- **macOS:** Double-click `start.command`.
- **Windows:** Double-click `start.bat`.

The script first checks the local environment and for an installed Python 3.10+. If a suitable Python version is not available, it automatically downloads **Python 3.12** via [uv](https://docs.astral.sh/uv/guides/install-python/) to the `.runtime` folder next to the converter. On Mac, the system `/usr/bin/python3` is skipped to avoid opening Apple's developer tools installer.

The first launch creates a `.venv` and downloads dependencies, including FFmpeg; this requires an internet connection and access to Astral, GitHub, and PyPI. Subsequent launches work offline. Administrator privileges, PATH changes, and manual FFmpeg installation are not required. If a download is interrupted, run the script again.

On Windows, `start.bat` uses the built-in Windows PowerShell; the script execution setting applies only to that process and does not change the system policy. Policies on managed corporate computers may restrict launching or downloading.

The browser automatically opens **http://127.0.0.1:8765**. Keep the launcher window open while using the app. To stop it, press **Ctrl+C** in that window. If the browser does not open, navigate to the address manually.

Alternatively, launch from the macOS terminal:

```sh
cd /Users/artemshkryab/dev/proj/m4a_convertor
./start.command
```

On Windows (from the project folder):

```bat
start.bat
```

If the port is occupied: use `./start.command --port 8766` on Mac or `start.bat --port 8766` on Windows. To launch without automatically opening the browser, add `--no-browser`. If Python is available, you can also run `python3 launch.py` or `py -3 launch.py` directly.

## Usage

1. Drag files into the window or click **Add**. You can select multiple files at once.
2. Choose a quality setting with the slider: **64, 96, 128, 160, 192, 256, or 320 kbps**. The default is **192 kbps**.
3. Click **Convert**. Files are processed one at a time, with progress shown for each.
4. Save a result with the **↓** button next to the file, or download all completed files in a single **ZIP**.

The **×** button cancels processing and removes the file from the list. After an error, you can prepare a file for conversion again with the **→** button, as long as the original is still on the current page. After a page refresh, the server restores the queue and completed results; files that had not been sent must be added again.

## Formats, quality, and storage

- Common input formats: MP3, WAV, FLAC, OGG, Opus, AIFF, AAC, M4A, WMA. Actual support depends on FFmpeg decoders. You can also add video files; the first audio track will be used.
- Output: **M4A** container, **AAC** codec, at the selected bitrate. Even an M4A input is re-encoded at the selected quality.
- A higher bitrate increases file size; it does not restore detail lost in the original. The estimated size per minute is approximate; the container and metadata also take up space.
- Up to **2 GiB per file** and **100 files** in the server queue. Make sure there is enough free space for the originals, results, and ZIP.
- Files are processed locally; the server listens only on `127.0.0.1`. The interface does not use external fonts, analytics, or cloud conversion.
- Completed results are stored in a temporary folder for **1 hour after completion**. Expired results are cleaned up on the next API request. The original is deleted after processing; the temporary folder is cleared when the server shuts down normally. After a crash, the system temporary folder may remain.
- Download results before closing the server. Downloaded copies remain in the browser's default downloads folder.
- When copying the project folder to another computer, **exclude `.venv` and `.runtime`**: the environment and, if needed, Python will be created for the new system on first launch. Keep the converter in a folder where you have write permission.

## Verification

### Building a standalone app

Building requires Python and development dependencies. The macOS app must be built on macOS, and the Windows `.exe` on Windows; [PyInstaller does not cross-compile between operating systems](https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems).

On Mac, Xcode/Command Line Tools are required to build the native launcher. These are needed only by the developer during the build, not by users of the finished app. The build creates an `.app`, ZIP, and DMG.

macOS:

```sh
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python build_app.py
```

Windows, after preparing `.venv`:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe build_app.py
```

The Windows build produces a single **`dist\M4AConverter.exe`** that already includes Python and FFmpeg and works offline. A `.exe` has not been built on this Mac; the current ready-to-use Windows file is a `.bat` that automatically sets up dependencies.

Update both self-contained launcher files after changing the code:

```sh
.venv/bin/python build_portable.py
```

Test the native executable separately from the source files and system FFmpeg:

```sh
.venv/bin/python tests/smoke_packaged.py dist/M4AConverter
```

Test the extracted ZIP and the app copied from the DMG via Launch Services (as in Finder):

```sh
.venv/bin/python tests/smoke_macos_package.py
```

This local check does not confirm whether Gatekeeper will prompt after downloading from the internet.

### Converter tests

After installing dependencies:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

On Windows:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests run real FFmpeg and check conversion of various formats, AAC in M4A, different bitrates, ZIP files with duplicate names, errors, cancellation, cleanup, and access to the local API.
