#!/bin/bash
set -e

echo "🔍 Detecting Python Configuration..."

PY_INC=$(python3 -m pybind11 --includes)

EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.so')")

PY_LDFLAGS=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LDFLAGS') or '')")
PY_LIB=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))")
PY_LDLIBRARY=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LDLIBRARY'))")

LINK_ARGS="-L$PY_LIB -lpython3.11" 
# NOTE: If your python version is different, this might need adjustment. 
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
LINK_ARGS="-L$PY_LIB -lpython$PY_VER"


INCLUDES="-I/opt/homebrew/include -I/usr/local/include"

echo "   Python Version: $PY_VER"
echo "   Library Path:   $PY_LIB"
echo "   Linker Flags:   $LINK_ARGS"

echo "🛠️  Generating C++ Headers..."
flatc --cpp -o src/ schema/tactical.fbs

echo "🚀 Compiling Python Extension..."

c++ -O3 -Wall -shared -std=c++17 -fPIC \
    $PY_INC \
    $INCLUDES \
    -undefined dynamic_lookup \
    -I src/ \
    src/tactical_bind.cpp \
    -o src/tactical_core$EXT_SUFFIX

echo "✅ Build Complete: src/tactical_core$EXT_SUFFIX"