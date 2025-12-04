##### PREEMPT-K8S DOCKERFILE #####

### Build Stage ###
FROM rust:1.91.1 AS builder
WORKDIR /Preempt-K8s
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo fetch
RUN cargo build --release

### Container Creation Stage ###
FROM debian:bullseye-slim
COPY --from=builder /Preempt-K8s/target/release/Preempt-K8s /usr/local/bin/Preempt-K8s
RUN mkdir -p /eventqueue
USER root
CMD ["Preempt-K8s"]
