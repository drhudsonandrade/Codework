FROM mambaorg/micromamba:2.3.2

ARG MAMBA_DOCKERFILE_ACTIVATE=1
WORKDIR /opt/codework

COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install --yes --name base --file /tmp/environment.yml \
    && micromamba clean --all --yes

COPY --chown=$MAMBA_USER:$MAMBA_USER mcp/package.json mcp/package-lock.json /opt/codework/mcp/
RUN cd /opt/codework/mcp \
    && npm ci --ignore-scripts

COPY --chown=$MAMBA_USER:$MAMBA_USER . /opt/codework/
USER root
RUN chmod 0755 /opt/codework/scripts/*.sh /opt/codework/scripts/*.py \
    && mkdir -p /refs /data /work /results /audit \
    && chown -R $MAMBA_USER:$MAMBA_USER /refs /data /work /results /audit
USER $MAMBA_USER

RUN cd /opt/codework/mcp \
    && npm run build

ENV PORT=3000 \
    REF_ROOT=/refs \
    DATA_ROOT=/data \
    WORK_ROOT=/work \
    RESULTS_ROOT=/results \
    AUDIT_ROOT=/audit

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:3000/healthz >/dev/null || exit 1
CMD ["node", "/opt/codework/mcp/dist/src/server.js"]
