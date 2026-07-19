FROM node:24.18.0-alpine

ENV NODE_ENV=development \
    NPM_CONFIG_UPDATE_NOTIFIER=false

RUN mkdir -p /app && chown node:node /app
WORKDIR /app
USER node

COPY --chown=node:node package.json ./
RUN npm install --include=dev --no-audit --no-fund

COPY --chown=node:node . .
EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
