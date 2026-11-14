FROM python:3.10

WORKDIR /app

ARG HUBBLE_CLI_VERSION=v1.20.4
ADD --checksum=sha256:78ed68bd56d244bf2691ae4ba186d78e87e6814df58573d6de6089d0e5d7ddd8 \
    https://github.com/cilium/hubble/releases/download/${HUBBLE_CLI_VERSION}/hubble-linux-amd64.tar.gz \
    /tmp/hubble.tar.gz
RUN tar -xzf /tmp/hubble.tar.gz -C /usr/local/bin hubble \
    && rm /tmp/hubble.tar.gz

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
