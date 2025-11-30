##### PREEMPT-K8S DOCKERFILE #####

### Build Stage ###
FROM rust:1.91.1 AS builder
WORKDIR /usr/src/Preempt-K8s
COPY Cargo.toml Cargo.lock ./
RUN cargo fetch
COPY src ./src
RUN cargo build --release

### Container Creation Stage ###
FROM debian:bullseye-slim
COPY --from=builder /usr/src/Preempt-K8s/target/release/Preempt-K8s /usr/local/bin/Preempt-K8s
RUN mkdir -p /eventqueue
USER root
CMD ["Preempt-K8s"]
