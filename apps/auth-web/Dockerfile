# Build context: repository root. Separate login application served under /login.
FROM node:20.18-alpine AS build
WORKDIR /src
COPY apps/auth-web/package.json apps/auth-web/
RUN cd apps/auth-web && npm install --no-audit --no-fund
COPY apps/auth-web apps/auth-web
RUN cd apps/auth-web && npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /src/apps/auth-web/dist /usr/share/nginx/html/login
COPY infra/nginx/spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
