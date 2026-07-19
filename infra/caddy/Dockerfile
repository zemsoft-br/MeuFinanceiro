FROM caddy:2.11.3-alpine

# The official image grants cap_net_bind_service to /usr/bin/caddy so it can
# bind privileged ports. MeuFinanceiro listens on 8080 and intentionally runs
# with cap_drop=ALL and no-new-privileges, so retaining that file capability
# makes execve fail with EPERM on hardened Docker runtimes.
USER root
RUN setcap -r /usr/bin/caddy

USER 65534:65534
