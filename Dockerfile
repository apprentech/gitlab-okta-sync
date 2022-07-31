FROM python:3.9-buster

COPY __main__.py requirements.txt /root

RUN pip3 install -r /root/requirements.txt
