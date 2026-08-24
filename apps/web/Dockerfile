FROM node:26-alpine AS dependencies
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile

FROM node:26-alpine AS builder
RUN corepack enable
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=dependencies /app/apps/web/node_modules ./apps/web/node_modules
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web ./apps/web
RUN pnpm --filter @chakravyuh/web build

FROM node:26-alpine AS runtime
ENV NODE_ENV=production
RUN addgroup --system --gid 10001 chakravyuh \
    && adduser --system --uid 10001 --ingroup chakravyuh chakravyuh
WORKDIR /app
COPY --from=builder --chown=chakravyuh:chakravyuh /app/apps/web/.next/standalone ./
COPY --from=builder --chown=chakravyuh:chakravyuh /app/apps/web/.next/static ./apps/web/.next/static
USER chakravyuh
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
