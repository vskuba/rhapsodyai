import os
import platform
import subprocess


async def open_file_in_editor(path):
    """
    Opens a file on Windows/Linux for the user to edit.
    The 'path' argument is the path to the file.
    """
    if platform.system() == "Windows":
        os.startfile(path)
    elif platform.system() == "Darwin":  # macOS
        subprocess.call(["open", path])
    else:  # Linux
        subprocess.call(["xdg-open", path])
