FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    NAVER_TUNNEL_NATIVE_CI=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 openssh-client openssh-server nginx systemd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd
WORKDIR /opt/naver-tunnel
COPY naver_engine/ ./naver_engine/
COPY naver_runtime/ ./naver_runtime/
COPY deploy/naver-erp-tunnel/ ./deploy/naver-erp-tunnel/
COPY tools/naver-tunnel-native-ci.py ./tools/naver-tunnel-native-ci.py
ENTRYPOINT ["python3", "tools/naver-tunnel-native-ci.py"]
