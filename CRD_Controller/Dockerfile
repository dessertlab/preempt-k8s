FROM ubuntu:22.04
COPY ./target/release/CRD_Controller ./
RUN mkdir -p /eventqueue
USER root
CMD ["./CRD_Controller"]
