FROM node:22-alpine AS build

WORKDIR /app
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# Runs as uid 101 and listens on 8080, so it works under restricted Pod Security.
FROM nginxinc/nginx-unprivileged:1.27-alpine

ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

COPY --from=build /app/dist /usr/share/nginx/html
COPY ui/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 ui/nginx/25-apgar-ipv6.sh /docker-entrypoint.d/25-apgar-ipv6.sh
