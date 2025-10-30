FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jakarta

WORKDIR /usr/src/app

# Install all dependencies in one layer to reduce image size
RUN apt-get update -qq && \
    apt-get install -qq -y \
    ffmpeg \
    gcc \
    libffi-dev \
    git \
    wget \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Download and install rclone
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; \
    elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; \
    elif [ "$ARCH" = "armv7l" ]; then ARCH="arm-v7"; fi && \
    curl -s -O https://downloads.rclone.org/rclone-current-linux-${ARCH}.zip && \
    unzip -q rclone-current-linux-${ARCH}.zip && \
    cd rclone-*-linux-${ARCH} && \
    install -m 755 rclone /usr/bin/rclone && \
    cd .. && \
    rm -rf rclone-*-linux-${ARCH}*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Initialize and update git submodules
RUN git submodule update --init --recursive

ENTRYPOINT ["python", "-m", "bot"]