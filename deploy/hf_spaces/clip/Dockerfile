FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir \
    "open-clip-torch" \
    "fastapi==0.115.0" \
    "uvicorn[standard]==0.30.6" \
    "pillow==10.4.0"
COPY app.py .
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
