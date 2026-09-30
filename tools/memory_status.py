"""Read Windows memory counters without launching a CAD kernel or WMI."""

import ctypes
from ctypes import wintypes
import json


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
        (name, ctypes.c_ulonglong) for name in (
            "total_physical", "available_physical", "total_page_file",
            "available_page_file", "total_virtual", "available_virtual",
            "available_extended_virtual",
        )
    ]


def read_memory():
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return {
        "physical_load_percent": status.load,
        "total_physical_gib": round(status.total_physical / 2**30, 3),
        "available_physical_gib": round(status.available_physical / 2**30, 3),
        "available_commit_gib": round(status.available_page_file / 2**30, 3),
    }


if __name__ == "__main__":
    print(json.dumps(read_memory(), indent=2))
