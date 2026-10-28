"""Create single-file launchers; each includes the complete application source."""
import base64
import hashlib
import io
from pathlib import Path
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = ("app.py", "launch.py", "requirements.txt", "start.command", "start.ps1",
         "templates/index.html", "static/app.js", "static/style.css")

MAC = r'''#!/bin/zsh
# Complete M4A Converter. No neighbouring files are required.
converter_self="${0:A}"
converter_parent="${M4A_INSTALL_DIR:-$HOME/Library/Application Support/M4A Converter}"
converter_dir="$converter_parent/@VERSION@"

install_converter() {
  if [[ -f "$converter_dir/.complete" ]]; then return 0; fi
  mkdir -p "$converter_parent" || return 1
  local staging=$(/usr/bin/mktemp -d "$converter_parent/.install.XXXXXX") || return 1
  /usr/bin/awk '/^__M4A_PAYLOAD__$/{payload=1;next}payload{print}' "$converter_self" | \
    /usr/bin/base64 -D > "$staging/app.zip"
  if [[ $? -ne 0 ]] || ! /usr/bin/unzip -q "$staging/app.zip" -d "$staging/app"; then
    /bin/rm -rf -- "$staging"
    return 1
  fi
  touch "$staging/app/.complete"
  if [[ ! -d "$converter_dir" ]]; then
    /bin/mv -- "$staging/app" "$converter_dir" || return 1
  fi
  /bin/rm -rf -- "$staging"
}

if ! install_converter; then
  echo "Не удалось подготовить конвертер. Переместите файл в доступную для записи папку и попробуйте снова."
  read -r "?Нажмите Enter, чтобы закрыть…"
  exit 1
fi
/bin/zsh "$converter_dir/start.command" --desktop "$@"
exit $?
__M4A_PAYLOAD__
@PAYLOAD@
'''

WINDOWS = r'''@echo off
chcp 65001 >nul
set "M4A_PACKAGE_SELF=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& { $ErrorActionPreference='Stop'; try { $parent=if($env:M4A_INSTALL_DIR){$env:M4A_INSTALL_DIR}else{Join-Path $env:LOCALAPPDATA 'M4AConverter'}; $target=Join-Path $parent '@VERSION@'; if(-not (Test-Path -LiteralPath (Join-Path $target '.complete'))){ $stage=Join-Path $parent ([Guid]::NewGuid().ToString()); New-Item -ItemType Directory -Path $stage -Force | Out-Null; try { $content=[IO.File]::ReadAllText($env:M4A_PACKAGE_SELF); $payload=($content -split '(?m)^::M4A_PAYLOAD_BEGIN\r?$',2)[1]; $zip=Join-Path $stage 'app.zip'; [IO.File]::WriteAllBytes($zip,[Convert]::FromBase64String($payload)); Add-Type -AssemblyName System.IO.Compression.FileSystem; $app=Join-Path $stage 'app'; [IO.Compression.ZipFile]::ExtractToDirectory($zip,$app); New-Item -ItemType File -Path (Join-Path $app '.complete') | Out-Null; if(-not (Test-Path -LiteralPath $target)){ Move-Item -LiteralPath $app -Destination $target }; } finally { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }; }; & (Join-Path $target 'start.ps1') --desktop; exit $LASTEXITCODE; } catch { Write-Host ('Не удалось запустить конвертер: '+$_.Exception.Message); exit 1; } }"
set "converter_exit=%errorlevel%"
if not "%converter_exit%"=="0" pause
exit /b %converter_exit%
::M4A_PAYLOAD_BEGIN
@PAYLOAD@
'''


def main():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, (ROOT / name).read_bytes())
    data = archive.getvalue()
    version = hashlib.sha256(data).hexdigest()[:16]
    payload = "\n".join(textwrap.wrap(base64.b64encode(data).decode("ascii"), 76))
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    for name, template in (("M4A-Converter-macOS.command", MAC), ("M4A-Converter-Windows.bat", WINDOWS)):
        contents = template.replace("@VERSION@", version).replace("@PAYLOAD@", payload)
        path = output / name
        path.write_text(contents, encoding="utf-8", newline="\r\n" if name.endswith(".bat") else "\n")
        if name.endswith(".command"):
            path.chmod(0o755)
        print(f"Готово: {path}")


if __name__ == "__main__":
    main()
