python_dockerfile = """FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use environment variables
COPY .env .env
ENV $(cat .env)

EXPOSE 5000

CMD ["python", "app.py"]
"""