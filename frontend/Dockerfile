# E2E-only image: builds the static export and serves it over HTTP inside
# the docker-compose network so Playwright (also containerized, see
# ../e2e/Dockerfile and ../docker-compose.e2e.yml) can drive it.
#
# NOT used for the real deploy — Phase 8's CD workflow pushes the static
# export straight to GitHub Pages (manual.md §4/§7), which needs no
# container at all. This Dockerfile exists purely so Phase 7's E2E suite has
# something to point a browser at that resolves the same internal hostnames
# (`api`, `localstack`) a real page load would need — see
# docker-compose.e2e.yml's comments for the full reasoning.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, not
# read at runtime — this build arg has to be set *before* `npm run build`,
# not just at container `docker run` time (see lib/api.ts's docstring).
ARG NEXT_PUBLIC_API_URL=http://api:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# Root-relative, unlike the real GitHub Pages deploy (NEXT_BASE_PATH=/backecast)
# — this container serves the app at the domain root.
ENV NEXT_BASE_PATH=

RUN npm run build

# `output: 'export'` produces static files in `out/`, not a Node server —
# `next start` doesn't apply to an export build, so a plain static file
# server is what actually serves it. `serve` resolves directory `index.html`
# files for clean URLs (/admin -> /admin/index.html) out of the box, which
# is exactly what this multi-page app (not a single-page app) needs — no
# `-s`/SPA-fallback flag, that would incorrectly rewrite every route to the
# root page.
RUN npm install -g serve@14

EXPOSE 3000
CMD ["serve", "out", "-l", "3000"]
