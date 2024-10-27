FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=America/Los_Angeles

WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

RUN apt-get update -qq --fix-missing && \
    apt-get install -qq -y \
        git wget curl busybox python3.10 python3-pip locales ffmpeg rclone && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt --break-system-packages

COPY . .

CMD ["bash", "start.sh"]
