FROM --platform=linux/amd64 python:3.10.12-slim-bookworm

WORKDIR /load

RUN pip install rdf2gremlin

RUN pip install requests

COPY load_data.py .

CMD python load_data.py