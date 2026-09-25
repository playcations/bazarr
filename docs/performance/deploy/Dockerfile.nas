# The home-operations Bazarr image (same one the NAS runs: Python, unrar, entrypoint) with the Bazarr code replaced
# by the integration/performance branch. Build context: a checkout of that branch with frontend/build built.
FROM ghcr.io/home-operations/bazarr:1.6.1

USER root
RUN rm -rf /app/bin/bazarr /app/bin/bazarr.py /app/bin/custom_libs /app/bin/libs /app/bin/migrations \
           /app/bin/frontend/build /app/bin/requirements.txt /app/bin/postgres-requirements.txt
COPY bazarr.py requirements.txt postgres-requirements.txt /app/bin/
COPY bazarr /app/bin/bazarr
COPY custom_libs /app/bin/custom_libs
COPY libs /app/bin/libs
COPY migrations /app/bin/migrations
COPY frontend/build /app/bin/frontend/build
RUN echo "v1.6.1-perf" > /app/bin/VERSION
USER nobody:nogroup
