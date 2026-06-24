FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir -e .
COPY config.v0.2.example.yaml ./config.v0.2.example.yaml
ENTRYPOINT ["radar"]
CMD ["doctor"]
