import socket
import datetime
import sys


def google_ping():
    host = "google.com"
    port = 80
    timeout = 5
    print(f"[{datetime.datetime.now()}] Checking connection to {host}...")

    try:
        # Пытаемся создать TCP-соединение с 80 портом Google
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        print(f"Success! {host} is reachable via port {port}.")
    except socket.error as e:
        print(f"Failed. {host} is unreachable. Error: {e}")
        # Выходим с ненулевым кодом, чтобы ваш Cronjob класс поймал это как статус "error"
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == '__main__':
    google_ping()