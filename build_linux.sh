#!/bin/bash
set -e

PY_INC=$(python3 -m pybind11 --includes)
EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.so')")

echo "🛠️  Generating FlatBuffers Headers..."
flatc --cpp -o src/ schema/tactical.fbs

echo "🚀 Compiling C++ Core..."
c++ -O3 -Wall -shared -std=c++17 -fPIC \
    $PY_INC \
    -I src/ \
    src/tactical_bind.cpp \
    -o src/tactical_core$EXT_SUFFIX

echo "✅ Linux Build Complete"