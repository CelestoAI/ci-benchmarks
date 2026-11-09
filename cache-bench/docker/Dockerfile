# Docker layer cache fixture: a dependency layer (npm ci of the web-app tree)
# and a compile layer (tsc over the Turborepo fixture). Build context: cache-bench/
FROM node:22.16.0-bookworm-slim
WORKDIR /app
COPY deps/package.json deps/package-lock.json ./
RUN npm ci --no-audit --no-fund --ignore-scripts
COPY turbo/package.json turbo/package-lock.json turbo/turbo.json turbo/gen.mjs ./mono/
RUN cd mono && node gen.mjs && npm ci --no-audit --no-fund && npx turbo run build
CMD ["node", "-e", "console.log('ok')"]
