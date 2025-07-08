FROM ubuntu:latest
RUN useradd -r -u 65532 nonroot
USER 65532
COPY activator /
ENTRYPOINT ["/activator"]
