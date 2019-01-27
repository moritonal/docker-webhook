FROM python:3-alpine3.8

# Install docker
RUN apk update
RUN apk add docker

# Install docker-compose
RUN apk add py-pip
RUN pip install --upgrade pip
RUN pip install docker-compose

# Create /app/ and /app/hooks/
RUN mkdir -p /app/hooks/

WORKDIR /app

# Install requirements
COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
RUN rm -f requirements.txt

# Copy in webhook listener script
COPY webhook_listener.py ./webhook_listener.py

CMD ["python", "webhook_listener.py"]
EXPOSE 80
