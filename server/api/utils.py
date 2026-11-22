"""Shared application utilities."""

from api.models import Error


def error_record(exception: Exception) -> Error:
    """Capture the innermost traceback location, where the exception was raised."""
    traceback = exception.__traceback__
    while traceback is not None and traceback.tb_next is not None:
        traceback = traceback.tb_next
    if traceback is None:
        location = "api.worker.main.handle_message"
    else:
        frame = traceback.tb_frame
        module = frame.f_globals.get("__name__", "<unknown>")
        location = f"{module}.{frame.f_code.co_qualname}"
    return Error(location=location, error_message=repr(exception))
