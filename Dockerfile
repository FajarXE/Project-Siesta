# [FILE: Dockerfile]

# 1. Base Image
FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jakarta

WORKDIR /usr/src/app

# --- PERBAIKAN DI SINI ---
# Saya menambahkan 'curl' di sini agar terbawa sampai final stage
RUN apt-get update -qq && \
    apt-get install -qq -y ffmpeg gcc libffi-dev curl && \
    rm -rf /var/lib/apt/lists/*

# 2. Builder Stage (Untuk download Rclone & Compile)
FROM base AS builder
RUN apt-get update -qq && \
    apt-get install -qq -y git wget unzip && \
    rm -rf /var/lib/apt/lists/*

# Download and install rclone
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; \
    elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; \
    fi && \
    curl -O https://downloads.rclone.org/v1.70.2/rclone-v1.70.2-linux-${ARCH}.zip && \
    unzip rclone-v1.70.2-linux-${ARCH}.zip && \
    install -m 755 rclone-v1.70.2-linux-${ARCH}/rclone /usr/bin/rclone && \
    rm -rf rclone-v1.70.2-linux-${ARCH}*

# 3. Final Stage
FROM base AS final

# Copy rclone dari builder
COPY --from=builder /usr/bin/rclone /usr/bin/rclone

# Copy requirements & Install
COPY requirements.txt .
# --no-cache-dir agar image lebih kecil
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

ENTRYPOINT ["python", "-m", "bot"]
