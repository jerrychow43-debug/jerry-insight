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
COPY --from=build /app/minichat /app/minichat
RUN mkdir -p /app/data

EXPOSE 19191
CMD ["./minichat", "19191", "rpc", "18888"]
