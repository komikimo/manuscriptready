FROM python:3.12-slim

WORKDIR /app

# copy requirements from backend folder
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# copy backend source code
COPY backend/ .

CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]