import os
import platform
import subprocess


def open_file_in_editor(path):
    """
    Открывает файл в Windows/Linux, чтобы пользователь его отредактировал.
    Арументы функции:
    'path' - путь к файлу.
    """
    if platform.system() == "Windows":
        os.startfile(path)
    elif platform.system() == "Darwin":  # macOS
        subprocess.call(["open", path])
    else:  # Linux
        subprocess.call(["xdg-open", path])
