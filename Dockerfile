FROM python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jakarta

WORKDIR /usr/src/app

RUN apt-get update -qq && \
    apt-get install -qq -y ffmpeg gcc libffi-dev git wget curl unzip && \
    rm -rf /var/lib/apt/lists/*

# Download and install rclone
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; \
    elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi && \
    curl -O https://downloads.rclone.org/v1.70.2/rclone-v1.70.2-linux-${ARCH}.zip && \
    unzip rclone-v1.70.2-linux-${ARCH}.zip && \
    install -m 755 rclone-v1.70.2-linux-${ARCH}/rclone /usr/bin/rclone && \
    rm -rf rclone-v1.70.2-linux-${ARCH}*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Clone OrpheusDL to the correct location
RUN git clone https://github.com/OrfiTeam/OrpheusDL.git bot/helpers/OrpheusDL

WORKDIR /usr/src/app/bot/helpers/OrpheusDL

# Clone the beatport module
RUN git clone https://github.com/Dniel97/orpheusdl-beatport.git modules/beatport

# Install OrpheusDL requirements and initialize
RUN pip install -r requirements.txt && \
    python orpheus.py settings refresh

WORKDIR /usr/src/app

# Clean up session files and temporary files
RUN find . -name "*.session" -delete && \
    find /tmp -name "*.session" -delete 2>/dev/null || true && \
    rm -rf /var/lib/apt/lists/*

# Create necessary directories
RUN mkdir -p downloads tmp

ENTRYPOINT ["python", "-m", "bot"]
