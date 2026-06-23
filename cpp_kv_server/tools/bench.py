#!/usr/bin/env python3
import argparse
import socket
import time


def recv_line(sock: socket.socket) -> str:
    chunks = []
    while True:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("server closed connection")
        chunks.append(ch)
        if ch == b"\n":
            return b"".join(chunks).decode("utf-8", errors="replace").rstrip("\r\n")


def send_command(sock: socket.socket, command: str) -> str:
    sock.sendall((command + "\n").encode("utf-8"))
    return recv_line(sock)


def run_benchmark(host: str, port: int, count: int) -> None:
    with socket.create_connection((host, port), timeout=5) as sock:
        welcome = recv_line(sock)
        print(welcome)

        start = time.perf_counter()
        for i in range(count):
            resp = send_command(sock, f"set bench:{i} value-{i}")
            if resp != "OK":
                raise RuntimeError(f"unexpected set response at {i}: {resp}")
        set_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        for i in range(count):
            resp = send_command(sock, f"get bench:{i}")
            expected = f"value-{i}"
            if resp != expected:
                raise RuntimeError(f"unexpected get response at {i}: {resp}, expected {expected}")
        get_elapsed = time.perf_counter() - start

        send_command(sock, "exit")

    print(f"set: {count} requests in {set_elapsed:.4f}s, qps={count / set_elapsed:.2f}")
    print(f"get: {count} requests in {get_elapsed:.4f}s, qps={count / get_elapsed:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark MiniKV with set/get commands.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("-n", "--count", type=int, default=10000)
    args = parser.parse_args()

    run_benchmark(args.host, args.port, args.count)


if __name__ == "__main__":
    main()
