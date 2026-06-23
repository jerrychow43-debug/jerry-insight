FROM ubuntu:24.04 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential make ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY Makefile ./
COPY src ./src
RUN make

FROM ubuntu:24.04

WORKDIR /app
COPY --from=build /app/rpc_server /app/rpc_server
RUN mkdir -p /app/data

EXPOSE 18888
CMD ["./rpc_server", "18888"]
