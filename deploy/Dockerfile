FROM python:3.13-slim
WORKDIR /opt/kaif-eval
COPY pyproject.toml requirements.txt README.md ./
COPY app ./app
COPY config ./config
COPY demo ./demo
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir .
ENV KAIF_EVAL_CONFIG=/opt/kaif-eval/demo/eval.yaml
ENTRYPOINT ["kaif-eval"]
