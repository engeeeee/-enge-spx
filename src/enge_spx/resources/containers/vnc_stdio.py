"""Transport a local VNC connection over docker exec stdio; publish no ports."""
import os
import socket
import threading


def main():
    with socket.create_connection(("127.0.0.1", 5900), timeout=10) as connection:
        connection.settimeout(None)
        def upload():
            try:
                while data := os.read(0, 65536):
                    connection.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    connection.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
        threading.Thread(target=upload, daemon=True).start()
        try:
            while data := connection.recv(65536):
                offset = 0
                while offset < len(data):
                    offset += os.write(1, data[offset:])
        except (OSError, BrokenPipeError):
            pass


if __name__ == "__main__":
    main()
