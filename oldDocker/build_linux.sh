#!/bin/bash
set -e

# 1. Get Python Config
PY_INC=$(python3 -m pybind11 --includes)
EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.so')")

# 2. Generate Headers
echo "🛠️  [Container] Generating C++ Headers..."
flatc --cpp -o src/ schema/tactical.fbs

# 3. Compile
echo "🚀 [Container] Compiling Extension for Linux..."
c++ -O3 -Wall -shared -std=c++17 -fPIC \
    $PY_INC \
    -I src/ \
    src/tactical_bind.cpp \
    -o src/tactical_core$EXT_SUFFIX

echo "✅ [Container] Build Complete."