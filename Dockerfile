FROM python:3.12-slim-bookworm

WORKDIR /app
COPY pyproject.toml README.md ./
COPY pdfexel_api ./pdfexel_api
RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["uvicorn", "pdfexel_api.api:app", "--host", "0.0.0.0", "--port", "8080"]
