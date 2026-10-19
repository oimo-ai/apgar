FROM node:22-alpine AS build

WORKDIR /app
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM nginx:1.27-alpine

ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

COPY --from=build /app/dist /usr/share/nginx/html
COPY ui/nginx/default.conf.template /etc/nginx/templates/default.conf.template
