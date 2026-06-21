import hashlib


def signal_id(source_id: str, native_id: str) -> str:
    return hashlib.sha256(f"{source_id}|{native_id}".encode()).hexdigest()[:32]
