# Frontend — Vite build → nginx 靜態服務
FROM node:20-alpine AS build
WORKDIR /app
# 先複製 lockfile 再 npm ci：可重現的依賴 + 有效利用 layer cache
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
# 用 127.0.0.1 而非 localhost：掛了自訂 nginx.conf 後，官方 entrypoint 的
# 10-listen-on-ipv6-by-default.sh 會跳過，nginx 只聽 IPv4；
# 而 Alpine 的 localhost 會先解析成 ::1，healthcheck 會拿到 Connection refused。
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
CMD ["nginx", "-g", "daemon off;"]
