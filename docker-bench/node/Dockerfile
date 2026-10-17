ARG BASE
FROM ${BASE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json ./
COPY src ./src
RUN npm run build
FROM ${BASE}
WORKDIR /app
COPY --from=build /app/bundle.js ./bundle.js
CMD ["node", "bundle.js"]
