FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Hong_Kong

WORKDIR /usr/src/app

# Install all dependencies
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

# Install rclone
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

# Clone the repository with submodules
ARG GIT_REPO
ARG GIT_BRANCH=main

RUN if [ -n "$GIT_REPO" ]; then \
        git clone --branch $GIT_BRANCH --recursive $GIT_REPO . ; \
    else \
        echo "Warning: GIT_REPO not provided, you need to copy code manually" ; \
    fi

# Install Python dependencies
RUN if [ -f "requirements.txt" ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    fi

ENTRYPOINT ["python", "-m", "bot"]