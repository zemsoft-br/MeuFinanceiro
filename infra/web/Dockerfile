FROM debian:bookworm-slim AS flutter-build

ENV DEBIAN_FRONTEND=noninteractive \
    FLUTTER_ROOT=/opt/flutter \
    PATH=/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:$PATH

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libglu1-mesa \
        python3-minimal \
        unzip \
        xz-utils \
        zip \
    && rm -rf /var/lib/apt/lists/*

COPY .flutter-version .flutter-revision /tmp/flutter-pin/
COPY infra/scripts/finalize-flutter-web-build.py /tmp/finalize-flutter-web-build.py

RUN set -eux; \
    expected_version="$(tr -d '[:space:]' < /tmp/flutter-pin/.flutter-version)"; \
    expected_revision="$(tr -d '[:space:]' < /tmp/flutter-pin/.flutter-revision)"; \
    git clone --depth 1 --branch "$expected_version" https://github.com/flutter/flutter.git "$FLUTTER_ROOT"; \
    actual_revision="$(git -C "$FLUTTER_ROOT" rev-parse HEAD)"; \
    test "$actual_revision" = "$expected_revision"; \
    flutter config --no-analytics; \
    flutter precache --web

WORKDIR /src/apps/app
COPY apps/app/pubspec.yaml apps/app/pubspec.lock ./
RUN flutter pub get --enforce-lockfile

COPY apps/app/ ./
RUN flutter build web --release --no-web-resources-cdn --pwa-strategy=none \
    && python3 /tmp/finalize-flutter-web-build.py --build-dir build/web

FROM caddy:2.11.3-alpine

ENV XDG_CONFIG_HOME=/tmp/caddy-config \
    XDG_DATA_HOME=/tmp/caddy-data

USER root
RUN setcap -r /usr/bin/caddy \
    && mkdir -p /srv \
    && chown 65534:65534 /srv

COPY infra/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=flutter-build --chown=65534:65534 /src/apps/app/build/web/ /srv/

USER 65534:65534

EXPOSE 5173
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
