# Use the official Python image.
FROM python:3.13-slim

# Set the working directory.
WORKDIR /app

# Copy the requirements file.
COPY requirements.txt .

# Install the dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY . .

# Set the command to run the application.
CMD ["python", "analyzer.py"]
