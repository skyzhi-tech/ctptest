"""Read explicitly labelled codes from SDK error text; never infer from reasons."""
import re


_CODE = re.compile(
    r"(?<![A-Za-z0-9_])(?:ErrorID|error_code|错误码|返回码)"
    r"\s*(?:[:：=]|为|是)?\s*([+-]?[0-9]+)(?![0-9A-Za-z_.])",
    re.IGNORECASE,
)


def error_code(message):
    codes = {int(match.group(1)) for match in _CODE.finditer(str(message or ""))}
    # Conflicting codes are not safe to use as a single test result.
    return codes.pop() if len(codes) == 1 else None
