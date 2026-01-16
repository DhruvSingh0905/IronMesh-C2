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

# 3. COPY BUILD ASSETS
COPY schema/ ./schema/
COPY src/ ./src/
COPY main.py .
COPY build_linux.sh .

# 4. RUN THE BUILD
RUN chmod +x build_linux.sh && ./build_linux.sh

# 5. SETUP RUNTIME ENV
# [CRITICAL FIX] Force Python to flush logs immediately
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /keys /data
EXPOSE 9000
HEALTHCHECK --interval=5s --timeout=3s \
  CMD test $(find /tmp/healthy -mmin -0.1) || exit 1

CMD ["python", "main.py"]