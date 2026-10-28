#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1

start_converter() {
  local converter_python=""
  local candidate
  if [[ "${M4A_FORCE_BUNDLED_PYTHON:-0}" != "1" ]]; then
    for candidate in "$PWD/.venv/bin/python" "$(command -v python3)"; do
      # Apple's /usr/bin/python3 may be a stub that opens the developer tools installer.
      if [[ -n "$candidate" && "$candidate" != "/usr/bin/python3" && -x "$candidate" ]] &&
        "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        converter_python="$candidate"
        break
      fi
    done
  fi

  if [[ -z "$converter_python" ]]; then
    local runtime_dir="$PWD/.runtime"
    local uv_exe="$runtime_dir/bin/uv"
    export UV_PYTHON_INSTALL_DIR="$runtime_dir/python"
    export UV_CACHE_DIR="$runtime_dir/cache"
    if [[ ! -x "$uv_exe" ]]; then
      echo "Python не найден. Загрузка локального установщика (нужен интернет)…"
      mkdir -p "$runtime_dir" || return 1
      # Download before executing, so a failed download cannot run a partial installer.
      /usr/bin/curl --fail --location --silent --show-error --retry 2 \
        https://astral.sh/uv/install.sh -o "$runtime_dir/uv-install.sh" || return 1
      UV_UNMANAGED_INSTALL="$runtime_dir/bin" /bin/sh "$runtime_dir/uv-install.sh" || return 1
    fi
    echo "Подготовка локального Python…"
    "$uv_exe" python install --no-bin --no-registry --no-config 3.12 || return 1
    converter_python=$("$uv_exe" python find --system --managed-python --no-config 3.12) || return 1
  fi
  "$converter_python" launch.py "$@"
}

start_converter "$@"
result=$?
if [ "$result" -ne 0 ]; then
  echo "Не удалось запустить конвертер. Проверьте интернет и сообщения выше."
  read -r "?Нажмите Enter, чтобы закрыть…"
fi
exit "$result"
