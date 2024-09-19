FROM ubuntu:latest

WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Los_Angeles

RUN apt-get -qq update --fix-missing 
RUN apt-get -qq install -y git wget curl busybox python3 python3-pip locales

RUN curl -sL https://rclone.org/install.sh | bash
RUN rclone version

COPY requirements.txt .

COPY . .

CMD ["bash","start.sh"]
