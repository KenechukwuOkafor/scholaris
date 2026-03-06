from rest_framework.views import exception_handler


def scholaris_exception_handler(exc, context):
    """
    Wraps DRF's default exception handler to return a consistent envelope:

        {"error": "<message>", "detail": <original detail>}

    Falls back to None (which lets Django handle non-DRF exceptions) when
    the exception is not recognised by DRF.
    """
    response = exception_handler(exc, context)

    if response is not None:
        original_detail = response.data
        message = (
            original_detail
            if isinstance(original_detail, str)
            else original_detail.get("detail", str(exc))
            if isinstance(original_detail, dict)
            else str(exc)
        )
        response.data = {
            "error": message,
            "detail": original_detail,
        }

    return response
