
# Use a lightweight Python base image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the necessary Python libraries
RUN pip install -r requirements.txt

# Copy the Python script into the container
COPY listener.py .

# Set the entrypoint for the container
CMD ["python", "-u", "listener.py"]
