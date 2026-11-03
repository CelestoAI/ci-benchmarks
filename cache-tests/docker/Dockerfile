# A customer-like image: a slow step, a ~60 MB layer and app files.
# With the Docker layer cache, a second build marks every step CACHED.
FROM alpine:3.21
RUN echo "slow step" && sleep 30
RUN dd if=/dev/urandom of=/blob bs=1M count=60
COPY app.txt /app/app.txt
