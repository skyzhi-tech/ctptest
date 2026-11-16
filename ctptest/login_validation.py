"""Shared UserID gate used before constructing a live CTP account.

CTP TThostFtdcUserIDType is char[16]; reserve one byte for the NUL terminator.
The alphanumeric-only character policy belongs to this client, not to passwords.
"""
import string


USER_ID_MAX_BYTES = 15


class UserIDError(ValueError):
    def __init__(self, reason, message):
        self.reason = reason
        super().__init__("UserID " + message)


def validate_user_id(value):
    if not isinstance(value, str) or not value or not value.strip():
        raise UserIDError("blank", "不能为空或纯空白")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise UserIDError("control", "不能包含 ASCII 控制字符")
    if not value.isascii() or not value.isalnum():
        raise UserIDError("special", "仅允许 ASCII 字母和数字")
    if len(value.encode("ascii")) > USER_ID_MAX_BYTES:
        raise UserIDError("length", f"不能超过 {USER_ID_MAX_BYTES} 字节（CTP char[16]，保留终止符）")


def build_ctp_account(config, secrets, account_factory):
    validate_user_id(config.user_id)
    return account_factory(broker_id=config.broker_id, user_id=config.user_id,
                           password=secrets["password"], front_url=config.front_url,
                           app_id=config.app_id, auth_code=secrets["auth_code"])


def invalid_user_ids(case_id):
    if case_id == 34:
        return "blank", ("", " ", "   ", "\t ")
    if case_id == 35:
        return "control", tuple("AB" + chr(code) + "12" for code in (*range(32), 127))
    if case_id == 36:
        return "special", tuple("AB" + char + "12" for char in string.punctuation)
    if case_id == 37:
        return "length", tuple("A" * size for size in (16, 17, 64))
    raise ValueError("未知 UserID 测试")
