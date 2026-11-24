# Cloud Run edge: serves auth-web (/login) and workbench-web (/) and proxies /api and /auth to the
# core-api and auth-service Cloud Run services, so the browser sees one origin (SameSite=Strict cookies).
# Build context: repository root.
FROM node:20.18-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
COPY apps/auth-web/package.json apps/auth-web/
COPY apps/workbench-web/package.json apps/workbench-web/
RUN npm ci --no-audit --no-fund
COPY apps apps
RUN npm run build --workspace @nsip/auth-web && npm run build --workspace @nsip/workbench-web

FROM nginx:1.27-alpine
COPY --from=build /src/apps/workbench-web/dist /usr/share/nginx/html
COPY --from=build /src/apps/auth-web/dist /usr/share/nginx/html/login
COPY infra/gcp/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER="^(CORE_HOST|AUTH_HOST|PORT)$" PORT=8080
EXPOSE 8080
