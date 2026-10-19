# syntax=docker/dockerfile:1
FROM python:3.13-alpine

ARG TARGETARCH
ARG VERSION=1.1.0
LABEL org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.source="https://github.com/neilforest7/cloudflare-hosts-updater" \
      org.opencontainers.image.description="Cloudflare IP 优选与 Docker 容器 hosts 管理"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Shanghai DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./

# Optional build CA supports managed environments without changing TLS validation.
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca PIP_CERT=/run/secrets/build_ca; fi; \
    apk add --no-cache ca-certificates curl docker-cli tzdata \
    && pip install --no-cache-dir -r requirements.txt

# Pin both the upstream release and each architecture's published SHA-256 digest.
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export CURL_CA_BUNDLE=/run/secrets/build_ca; fi; \
    case "$TARGETARCH" in \
      amd64) digest=c4c8fc76b4e1bf2bdb5ced8b765956d82dda7bc4eb59df5c04053f0f7db98d90 ;; \
      arm64) digest=0ac992fcf24d4684caed33620deb9b83ce82f32d2418dc1f90be490ce5900300 ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl -fsSL --retry 3 "https://github.com/XIU2/CloudflareSpeedTest/releases/download/v2.3.5/cfst_linux_${TARGETARCH}.tar.gz" -o /tmp/cfst.tar.gz \
    && echo "$digest  /tmp/cfst.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/cfst.tar.gz -C /app --strip-components=1 \
    && mv /app/cfst /app/CloudflareST \
    && chmod +x /app/CloudflareST \
    && rm /tmp/cfst.tar.gz

COPY app ./app
RUN mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('WEB_PORT','8080')+'/healthz', timeout=3)" || exit 1
CMD ["python", "-m", "app.main"]
