# Python ka official lightweight image
FROM python:3.11-slim

# Container ke andar kaam karne ka folder
WORKDIR /app

# Requirements copy karke libraries install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki saara project code copy karo
COPY . .

# FastAPI server ko port 8000 par expose aur run karo
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]