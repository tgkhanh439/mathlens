FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Hugging Face Spaces dung cong 7860, Render va Railway truyen bien PORT.
ENV PORT=7860
ENV MATHLENS_DB=/tmp/mathlens.db

EXPOSE 7860
CMD ["sh", "-c", "uvicorn web.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
