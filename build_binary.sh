#!/usr/bin/env bash
set -euo pipefail

# Determine script root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="ProxyServerUi"
VENV_DIR="$SCRIPT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
VENV_PYINSTALLER="$VENV_DIR/bin/pyinstaller"

# Parse CLI arguments (default is --onefile)
BUILD_MODE="--onefile"
for arg in "$@"; do
    case "$arg" in
        --onedir|-d)
            BUILD_MODE="--onedir"
            ;;
        --onefile|-f)
            BUILD_MODE="--onefile"
            ;;
        --help|-h)
            echo "Использование: $0 [ОПЦИИ]"
            echo ""
            echo "Опции:"
            echo "  --onefile, -f   Собрать один исполняемый файл (по умолчанию)"
            echo "  --onedir,  -d   Собрать директорию со всеми зависимостями (быстрее старт)"
            echo "  --help,    -h   Показать эту справку"
            exit 0
            ;;
        *)
            echo "Неизвестный параметр: $arg" >&2
            echo "Используйте $0 --help" >&2
            exit 1
            ;;
    esac
done

echo "=== Сборка бинарника $APP_NAME (PyInstaller) ==="
echo "Режим сборки: $BUILD_MODE"

# 1. Check virtual environment
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Виртуальное окружение не найдено в $VENV_DIR. Создаем..."
    python3 -m venv "$VENV_DIR"
    "$VENV_PIP" install --upgrade pip
    "$VENV_PIP" install -r "$SCRIPT_DIR/requirements.txt"
fi

# 2. Check PyInstaller installation
if [ ! -f "$VENV_PYINSTALLER" ]; then
    echo "PyInstaller не найден в venv. Устанавливаем..."
    "$VENV_PIP" install pyinstaller
fi

# 3. Clean up previous build artifacts
echo "Очистка предыдущих сборок (build/, dist/, *.spec)..."
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist" "$SCRIPT_DIR/$APP_NAME.spec"

# 4. Run PyInstaller
echo "Запуск PyInstaller..."
"$VENV_PYINSTALLER" \
    --name "$APP_NAME" \
    $BUILD_MODE \
    --windowed \
    --clean \
    --noconfirm \
    --collect-all qasync \
    --collect-all python_socks \
    --collect-all httpx \
    --hidden-import PyQt6 \
    --hidden-import qasync \
    --hidden-import python_socks.async_.asyncio \
    main.py

echo ""
echo "=== Сборка завершена успешно! ==="
if [ "$BUILD_MODE" = "--onefile" ]; then
    BIN_PATH="$SCRIPT_DIR/dist/$APP_NAME"
    if [ -f "$BIN_PATH" ]; then
        BIN_SIZE=$(du -h "$BIN_PATH" | cut -f1)
        echo "Исполняемый файл: $BIN_PATH (размер: $BIN_SIZE)"
        echo "Запуск: ./dist/$APP_NAME"
    fi
else
    DIR_PATH="$SCRIPT_DIR/dist/$APP_NAME"
    echo "Директория с приложением: $DIR_PATH"
    echo "Запуск: ./dist/$APP_NAME/$APP_NAME"
fi
