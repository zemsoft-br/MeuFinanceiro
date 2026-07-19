FROM node:24.18.0-alpine AS build

ENV NPM_CONFIG_UPDATE_NOTIFIER=false

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund

COPY . .
RUN npm run build

FROM node:24.18.0-alpine AS runtime

ENV NODE_ENV=production \
    PORT=5173

RUN mkdir -p /app && chown node:node /app
WORKDIR /app
USER node

COPY --from=build --chown=node:node /app/dist ./dist
COPY --chown=node:node server.mjs ./

EXPOSE 5173

CMD ["node", "server.mjs"]
