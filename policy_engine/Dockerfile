FROM python:3.12-slim

ARG UID=10001
ARG GID=10001
WORKDIR /opt/genoma
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/genoma/policy_engine \
    GENOMA_RULESET_PATH=/run/genoma/REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt \
    GENOMA_RULESET_SHA_MANIFEST=/run/genoma/manifests/RULESET_V3.3.sha256
RUN groupadd --gid ${GID} genoma && useradd --uid ${UID} --gid ${GID} --create-home genoma
COPY policy_engine /opt/genoma/policy_engine
RUN chmod +x /opt/genoma/policy_engine/scripts/genoma-policy
USER genoma
EXPOSE 8787
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=2).read()" || exit 1
ENTRYPOINT ["python", "-m", "genoma_policy"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8787"]
