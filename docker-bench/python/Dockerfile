ARG BASE
FROM ${BASE} AS build
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt
FROM ${BASE}
COPY --from=build /install /usr/local
WORKDIR /app
COPY app.py ./
CMD ["python", "app.py"]
