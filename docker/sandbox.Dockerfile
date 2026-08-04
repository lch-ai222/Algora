# Per-trial sandbox image (design artifact for the "Docker upgrade" of the MVP sandbox).
#
# The MVP isolates each trial with a temp git worktree + subprocess + command allow-list (see
# src/codeagent_eval/sandbox/). This Dockerfile is the documented upgrade: run each trial inside
# a throwaway container for kernel-level isolation, reproducible environments (the reason the
# official SWE-bench harness requires Docker), and real network isolation via `--network none`.
#
# Build:  docker build -f docker/sandbox.Dockerfile -t codeagent-eval-sandbox .
# Run one trial (network cut, resource-capped, nothing mounted from host):
#   docker run --rm --network none --cpus 1 --memory 1g \
#     codeagent-eval-sandbox \
#     python -m codeagent_eval.runner --agent v2 --suite datasets/mini_store_suite --cases <id>
#
# Built and exercised by `.github/workflows/ci.yml` (the `sandbox-image` job): CI builds the
# image, then runs the per-case selfcheck and the deterministic bounds inside it with
# `--network none`. An image that builds but cannot run a trial is not an isolation layer, and
# offline execution is the claim the MVP worktree sandbox cannot make on its own.

FROM python:3.11-slim

# git is required for the worktree sandbox; build tools kept minimal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

COPY datasets ./datasets
COPY scripts ./scripts

# Non-root user; the trial runs as an unprivileged user with no host access.
RUN useradd -m runner && chown -R runner:runner /app
USER runner

# Default: show the CLI help. Real invocations pass a runner command (see header).
ENV PYTHONPATH=/app/src
CMD ["python", "-m", "codeagent_eval.runner", "--help"]
