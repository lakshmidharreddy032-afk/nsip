FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.32.1"
COPY mock_gateway ./mock_gateway
RUN useradd -r -u 10001 app
USER 10001
EXPOSE 8090
CMD ["uvicorn", "mock_gateway.app:app", "--host", "0.0.0.0", "--port", "8090"]
