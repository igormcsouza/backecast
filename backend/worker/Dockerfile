# Worker Lambda: shipped as a container image, NOT a zip (unlike ApiFunction
# in infra/stacks/api_stack.py, still a PythonFunction/zip). Why: this
# Lambda needs the `ffmpeg`/`ffprobe` *binaries* on its PATH (see
# worker/audio.py's docstring for what they're for). Those are native
# binaries with their own shared-library dependencies, not something `uv
# add` can install as a Python package. A Lambda Layer *can* technically
# hold binaries, but layers have their own size ceiling and are an awkward,
# separately-versioned artifact for a binary this size — a container image
# (up to 10GB) just installs ffmpeg like any Linux box would, in the same
# Dockerfile that builds the rest of the function.
#
# Build context is `backend/` (see infra/stacks/pipeline_stack.py's
# DockerImageCode.from_image_asset(..., file="worker/Dockerfile")) so this
# file can COPY pyproject.toml/uv.lock/app/worker from there.

FROM ghcr.io/astral-sh/uv:latest AS uv-bin

# --- base: AWS's own Lambda Python runtime image + ffmpeg ------------------
FROM public.ecr.aws/lambda/python:3.12 AS base

# Amazon Linux 2023's default package repos (this base image's OS) don't
# ship ffmpeg — it's excluded for licensing reasons, same as on most
# distros' default repos. The common workaround, used here, is a prebuilt
# static binary rather than compiling ffmpeg from source inside the image.
RUN dnf install -y tar xz && \
    curl -sSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
      -o /tmp/ffmpeg.tar.xz && \
    mkdir -p /tmp/ffmpeg-extract && \
    tar -xf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg-extract --strip-components=1 && \
    cp /tmp/ffmpeg-extract/ffmpeg /tmp/ffmpeg-extract/ffprobe /usr/local/bin/ && \
    rm -rf /tmp/ffmpeg.tar.xz /tmp/ffmpeg-extract && \
    dnf clean all

# uv itself: copied as a static binary from its official image rather than
# `pip install uv` — keeps "uv for everything Python" true even for the one
# tool that bootstraps the rest, and avoids needing pip in this image at all.
COPY --from=uv-bin /uv /usr/local/bin/uv

# --- deps: resolve + install project dependencies (cached until pyproject/uv.lock change)
FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# --- runtime: Lambda's entrypoint is worker.handler.handler
FROM base AS runtime
COPY --from=deps ${LAMBDA_TASK_ROOT}/.venv ${LAMBDA_TASK_ROOT}/.venv
ENV PYTHONPATH="${LAMBDA_TASK_ROOT}/.venv/lib/python3.12/site-packages"
COPY app ${LAMBDA_TASK_ROOT}/app
COPY worker ${LAMBDA_TASK_ROOT}/worker
CMD ["worker.handler.handler"]
