FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jakarta

WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

RUN apt-get update -qq --fix-missing && \
    apt-get install -qq -y \
        git wget curl busybox python3.12 python3-pip locales ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install rclone using curl
RUN curl -O https://downloads.rclone.org/rclone-current-linux-amd64.deb && \
    dpkg -i rclone-current-linux-amd64.deb && \
    rm rclone-current-linux-amd64.deb

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt --break-system-packages

COPY . .

CMD ["bash", "start.sh"]
