FROM python:3.11-slim

# 1. INSTALL COMPILERS & HEADERS
RUN apt-get update && apt-get install -y \
    build-essential \
    flatbuffers-compiler \
    libflatbuffers-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. INSTALL PYTHON BUILD DEPS
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install pybind11

# 3. COPY SOURCE CODE
# We copy specific folders to keep the layer clean
COPY schema/ ./schema/
COPY src/ ./src/
# Copy the updated main.py from root
COPY main.py .
COPY build_linux.sh .

# 4. COMPILE C++ EXTENSIONS
RUN chmod +x build_linux.sh && ./build_linux.sh

# 5. RUNTIME CONFIGURATION
ENV PYTHONUNBUFFERED=1

# Create directories for persistence and keys
RUN mkdir -p /keys /data

# Expose Gossip Port
EXPOSE 9000

# Healthcheck using the file written by main.py
HEALTHCHECK --interval=5s --timeout=3s \
  CMD test $(find /tmp/healthy -mmin -0.1) || exit 1

# Launch the unified entry point
CMD ["python", "main.py"]