import socket
import datetime


def google_ping() -> str:
    host = "google.com"
    port = 80
    timeout = 5
    print(f"[{datetime.datetime.now()}] Checking connection to {host}...")

    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        result = f"Success! {host} is reachable via port {port}."
        print(result)

        return result
    except socket.error as e:
        print(f"Failed. {host} is unreachable. Error: {e}")
        raise e
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise e


if __name__ == '__main__':
    google_ping()