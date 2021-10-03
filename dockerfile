# syntax=docker/dockerfile:1

FROM python:3.9-slim-buster
WORKDIR /app
RUN pip3 install nodewire==2.0.0 amqtt motor pyjwt
COPY . .
CMD [ "python3", "./cp/cp.py"]