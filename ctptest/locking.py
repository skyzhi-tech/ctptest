from pathlib import Path


class InstanceLock:
    """OS-released exclusive byte lock; never delete a lock owned by a peer."""
    def __init__(self, directory, scope):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / f"{scope}.lock").open("a+b")
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except Exception:
            self.file.close()
            raise RuntimeError("相同账号和日志目录已有 ctptest 实例运行，请先关闭旧实例")

    def close(self):
        import msvcrt
        try:
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.file.close()
