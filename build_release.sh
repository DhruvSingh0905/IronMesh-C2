#!/bin/bash
set -e

# ANSI Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}[BUILD] 初始化 IronMesh Release Builder...${NC}"

# 1. Spin up a build container using your existing image
# We mount the current directory so we can extract the binary later
docker run --rm -v "$(pwd):/app" -w /app tactical-mesh:latest /bin/bash -c "
    echo -e '${GREEN}   --> Installing PyInstaller inside container...${NC}'
    pip install pyinstaller > /dev/null

    echo -e '${GREEN}   --> Locating C++ Core...${NC}'
    # Find the exact name of the compiled .so file
    CORE_LIB=\$(find src -name 'tactical_core*.so' | head -n 1)
    echo \"       Found: \$CORE_LIB\"

    echo -e '${GREEN}   --> Packaging Single-File Binary...${NC}'
    # --onefile: Create a single executable
    # --hidden-import: Explicitly include the C++ extension
    # --add-data: Bundle the .so file so Python can find it at runtime
    pyinstaller --clean --onefile \\
        --name ironmesh \\
        --add-data \"\$CORE_LIB:src\" \\
        --hidden-import src.tactical_core \\
        main.py

    echo -e '${GREEN}   --> Cleaning up build artifacts...${NC}'
    rm -rf build ironmesh.spec
    
    # Set permissions so the host user can run it
    chmod +x dist/ironmesh
"

echo -e "${BLUE}[SUCCESS] Binary created at: dist/ironmesh${NC}"
echo -e "          File size: $(du -h dist/ironmesh | cut -f1)"