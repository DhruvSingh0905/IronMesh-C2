#!/bin/bash
set -e

echo "🔍 Detecting Python Configuration..."

# 1. Get Include Paths (Headers)
PY_INC=$(python3 -m pybind11 --includes)

# 2. Get Extension Suffix (File type)
EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.so')")

# 3. Get Linker Flags (The Missing Piece!)
# This explicitly asks Python: "Where is your .dylib library?"
PY_LDFLAGS=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LDFLAGS') or '')")
PY_LIB=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))")
PY_LDLIBRARY=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LDLIBRARY'))")

# Combine them for the linker
LINK_ARGS="-L$PY_LIB -lpython3.11" 
# NOTE: If your python version is different, this might need adjustment. 
# Let's make it dynamic:
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
LINK_ARGS="-L$PY_LIB -lpython$PY_VER"


# 4. FlatBuffers Paths
INCLUDES="-I/opt/homebrew/include -I/usr/local/include"

echo "   Python Version: $PY_VER"
echo "   Library Path:   $PY_LIB"
echo "   Linker Flags:   $LINK_ARGS"

echo "🛠️  Generating C++ Headers..."
flatc --cpp -o src/ schema/tactical.fbs

echo "🚀 Compiling Python Extension..."

# MacOS Linker needs '-undefined dynamic_lookup' for Python modules
# This tells the linker: "Don't worry about missing Python symbols, 
# the Python interpreter will provide them at runtime."
c++ -O3 -Wall -shared -std=c++17 -fPIC \
    $PY_INC \
    $INCLUDES \
    -undefined dynamic_lookup \
    -I src/ \
    src/tactical_bind.cpp \
    -o src/tactical_core$EXT_SUFFIX

echo "✅ Build Complete: src/tactical_core$EXT_SUFFIX"