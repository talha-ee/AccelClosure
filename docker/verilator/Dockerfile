FROM ghcr.io/ucb-bar/chia:latest

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       verilator \
       build-essential \
       openssh-client \
       rsync \
    && rm -rf /var/lib/apt/lists/*

USER ray
