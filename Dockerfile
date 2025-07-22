FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libpoppler-cpp-dev \
    pkg-config \
    python3-dev \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download nltk data
RUN python3 -m nltk.downloader stopwords

WORKDIR /app
COPY . .

CMD ["python", "pdf_extractor.py"]
