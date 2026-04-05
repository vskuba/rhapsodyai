import webbrowser


async def webbrowser_tab_open(url: str) -> None:
    """
    The function opens a window in the browser and passes a link.
    'url' arguments - the link to open.
    """
    webbrowser.open(url)
