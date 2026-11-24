# Build context: repository root.
FROM node:20.18-alpine AS build
WORKDIR /src
COPY apps/workbench-web/package.json apps/workbench-web/
RUN cd apps/workbench-web && npm install --no-audit --no-fund
COPY apps/workbench-web apps/workbench-web
RUN cd apps/workbench-web && npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /src/apps/workbench-web/dist /usr/share/nginx/html
COPY infra/nginx/spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
