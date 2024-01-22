import threading
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib

SCP_MAIN_THREAD_NAME = "SCP_MAIN_THREAD"

def thread_safe_blocking_call(function):
    """ Make function/method thread safe and block until its call is finished
    """

    blocker = threading.Event()

    def inner_wrapper(*args, **kwargs):
        function(*args, **kwargs)
        blocker.set()
        return False

    def wrapper(*args, **kwargs):
        # if this is the main thread then simply return function
        if threading.current_thread().name == SCP_MAIN_THREAD_NAME:
            return function(*args, **kwargs)
        Gdk.threads_add_idle(
        GLib.PRIORITY_DEFAULT_IDLE,
        inner_wrapper,
        *args,
        **kwargs
        )
        blocker.wait()

    return wrapper
