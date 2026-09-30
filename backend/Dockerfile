# Every dependency in requirements.txt ships a prebuilt manylinux wheel, so this
# image needs no compiler and no apt packages at all. That is worth stating
# because it is what makes a single stage correct here: there is nothing to
# build in a builder stage and cache into a slimmer runtime one.
#
# The result is a smaller image with a smaller CVE surface, a faster build, and
# no build-time dependency on a Debian mirror.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# From the base image's own passwd package - no apt install needed.
RUN useradd --create-home --uid 10001 analyst

WORKDIR /app

COPY requirements.txt .
# No --only-binary guard here on purpose. It looks like a safety net for "this
# image needs no compiler", but the absence of a compiler already enforces that:
# anything needing one fails loudly by itself. What the flag *also* rejects is a
# pure-Python dependency that happens to ship only an sdist - which installs
# perfectly well here - so it turns working builds into hard failures on any
# platform or Python version whose wheel coverage differs.
RUN pip install -r requirements.txt

COPY --chown=analyst:analyst . .

# Uploaded workbooks live here; mount a volume so they survive a restart and can
# be backed up (and wiped) independently of the image.
RUN mkdir -p /app/data/uploads && chown -R analyst:analyst /app/data
VOLUME ["/app/data"]

USER analyst
EXPOSE 8000

# Python is already in this image, so the health check needs no curl - which was
# the last reason this image installed anything from apt.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/system/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
