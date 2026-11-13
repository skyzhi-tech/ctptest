import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import os
from pathlib import Path
import tomllib
import uuid


SECRETS = ("token", "password", "auth_code")
TEST_FIELDS = ("symbol", "funds_symbol", "position_symbol", "market_symbol", "funds_volume",
               "price_offset", "quote_max_age", "timeout", "funds_error_codes",
               "position_error_codes", "market_error_codes")
FIELD_LABELS = {
    "environment": "测试环境", "front_url": "交易前置地址", "broker_id": "BrokerID",
    "user_id": "UserID", "app_id": "AppID", "symbol": "主测试合约", "log_dir": "日志目录",
    "password": "Password", "auth_code": "AuthCode", "token": "exsdk Token",
    "funds_volume": "资金不足委托手数", "price_offset": "价格偏移（价位数）",
    "quote_max_age": "报价有效期（秒）", "timeout": "回报等待期限（秒）",
}


class ConfigValidationError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(f"{FIELD_LABELS.get(field, field)} {message}")


class CredentialStore:
    """Windows Generic Credentials, no plaintext fallback."""

    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("凭据存储需要 Windows；不使用明文回退")
        class Credential(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]
        self.kind = Credential
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def write(self, target, value):
        blob = value.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        item = self.kind(Type=1, TargetName=target, CredentialBlobSize=len(blob),
                         CredentialBlob=buffer, Persist=2, UserName="ctptest")
        if not self.api.CredWriteW(ctypes.byref(item), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self, target):
        pointer = ctypes.POINTER(self.kind)()
        if not self.api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            item = pointer.contents
            return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode("utf-16-le")
        finally:
            self.api.CredFree(pointer)


@dataclass
class Config:
    environment: str = "仿真期货"
    broker_id: str = ""
    user_id: str = ""
    front_url: str = ""
    app_id: str = ""
    symbol: str = ""
    funds_symbol: str = ""
    position_symbol: str = ""
    market_symbol: str = ""
    funds_volume: int = 1
    price_offset: int = 5
    quote_max_age: float = 10
    timeout: float = 60
    log_dir: str = "data"
    funds_error_codes: str = ""
    position_error_codes: str = ""
    market_error_codes: str = ""
    credential_ref: str = ""

    @property
    def scope(self):
        # Renaming the default display label must not hide existing test records.
        environment = "模拟/仿真" if self.environment == "仿真期货" else self.environment
        raw = f"{environment}|{self.front_url}|{self.broker_id}|{self.user_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    @property
    def masked_user(self):
        return "***" + self.user_id[-3:]

    @property
    def connection_key(self):
        return tuple(getattr(self, item.name) for item in fields(self) if item.name not in TEST_FIELDS)

    def validate(self):
        for name in ("environment", "front_url", "broker_id", "user_id", "app_id", "symbol", "log_dir"):
            if not str(getattr(self, name)).strip():
                raise ConfigValidationError(name, "不能为空")
        if not self.front_url.startswith("tcp://"):
            raise ConfigValidationError("front_url", "必须以 tcp:// 开头")
        if "." not in self.symbol:
            raise ConfigValidationError("symbol", "必须使用 交易所.合约 格式")
        for name in ("funds_volume", "price_offset"):
            if getattr(self, name) < 1:
                raise ConfigValidationError(name, "必须为正整数")
        for name, maximum in (("quote_max_age", 300), ("timeout", 600)):
            if not 1 <= getattr(self, name) <= maximum:
                raise ConfigValidationError(name, f"须为 1～{maximum} 秒")


def load_config(path):
    path = Path(path)
    if not path.exists():
        return Config()
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if data.get("environment") == "模拟/仿真":
        data["environment"] = "仿真期货"
    allowed = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in allowed})


def save_config(path, config, secrets, vault=None):
    config.validate()
    for name in ("password", "auth_code", "token"):
        if not secrets.get(name, "").strip():
            raise ConfigValidationError(name, "不能为空")
    vault = vault or CredentialStore()
    existing = None
    if config.credential_ref:
        try:
            existing = {name: vault.read(f"{config.credential_ref}/{name}") for name in SECRETS}
        except OSError:
            pass
    if existing != secrets:
        # New credentials never overwrite the version used by an active connection.
        config.credential_ref = f"ctptest/{uuid.uuid4().hex}"
        for name in SECRETS:
            vault.write(f"{config.credential_ref}/{name}", secrets[name])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    lines = [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in asdict(config).items()]
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_secrets(config, vault=None):
    if not config.credential_ref:
        raise ValueError("尚未配置 Windows 凭据")
    vault = vault or CredentialStore()
    return {name: vault.read(f"{config.credential_ref}/{name}") for name in SECRETS}
