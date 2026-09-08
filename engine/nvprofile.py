"""Direct NvAPI DRS wrapper (ctypes) for NVIDIA driver game profiles.

Talks straight to ``nvapi64.dll`` through ``nvapi_QueryInterface`` — no
external SDK or driver-interop pip packages required.

Struct versions below were verified empirically against a 2026-era driver:

    NVDRS_PROFILE_V1      0x11014   (4116, natural alignment)
    NVDRS_APPLICATION_V4  0x4500C   (20492, natural alignment; pack8 rejected)
    NVDRS_SETTING_V1      0x13020   (12320, explicit pack(4))
    NVDRS_SETTING_VALUES  0x1651A0  (414112, explicit pack(4))

Signatures follow the current NVIDIA header:

    NvAPI_DRS_CreateProfile(hSession, pProfileInfo, phProfile)
    NvAPI_DRS_FindApplicationByName(hSession, appName, phProfile, pApplication)

Typical usage (engine layer above this handles the game catalog + snapshots):

    nv = Nvapi()
    with nv.session() as drs:
        prof = drs.find_profile("Fortnite")
        val = drs.get_setting_dword(prof, 0x1057EB71)
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os

from rexlog import logger

NVAPI_OK = 0
NVAPI_ERROR = -1
NVAPI_NOT_SUPPORTED = -4
NVAPI_INCOMPATIBLE_STRUCT_VERSION = -9
NVAPI_EXPECTED_ERROR = -34
NVAPI_DRIVER_NOT_FOUND = -80
NVAPI_SETTING_NOT_FOUND = -160
NVAPI_APPLICATION_NOT_FOUND = -164
NVAPI_PROFILE_NOT_FOUND = -167
NVAPI_EXECUTABLE_PATH_IS_AMBIGUOUS = -182
NVAPI_ACCESS_DENIED = -38

NVAPI_UNICODE_STRING_MAX = 2048
NVAPI_SHORT_STRING_MAX = 64
NVAPI_BINARY_DATA_MAX = 4096
NVAPI_SETTING_MAX_VALUES = 100
NVAPI_MAX_PHYSICAL_GPUS = 64

NVDRS_DWORD_TYPE = 0
NVDRS_BINARY_TYPE = 1
NVDRS_STRING_TYPE = 2
NVDRS_WSTRING_TYPE = 3
NVDRS_QWORD_TYPE = 4

# Error codes that simply mean "the thing you looked for is not there".
_EXPECTED = {
    NVAPI_SETTING_NOT_FOUND,
    NVAPI_APPLICATION_NOT_FOUND,
    NVAPI_PROFILE_NOT_FOUND,
    NVAPI_EXECUTABLE_PATH_IS_AMBIGUOUS,
}


class NvapiError(Exception):
    """Raised when an NvAPI call fails. ``code`` is the NvAPI_Status value."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class _NvDRS_GpuSupport(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint32)]


class NvDRS_Profile(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("profileName", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
        ("gpuSupport", _NvDRS_GpuSupport),
        ("isPredefined", ctypes.c_uint32),
        ("numOfApps", ctypes.c_uint32),
        ("numOfSettings", ctypes.c_uint32),
    ]


class NvDRS_Application(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("isPredefined", ctypes.c_uint32),
        ("appName", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
        ("userFriendlyName", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
        ("launcher", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
        ("fileInFolder", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
        ("isMetro", ctypes.c_uint32, 1),
        ("isCommandLine", ctypes.c_uint32, 1),
        ("reserved", ctypes.c_uint32, 30),
        ("commandLine", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
    ]


class NvDRS_BinarySetting(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("valueLength", ctypes.c_uint32),
        ("valueData", ctypes.c_ubyte * NVAPI_BINARY_DATA_MAX),
    ]


class _NvDRS_Value(ctypes.Union):
    _pack_ = 4
    _fields_ = [
        ("u32", ctypes.c_uint32),
        ("binary", NvDRS_BinarySetting),
        ("wsz", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
        ("u64", ctypes.c_uint64),
    ]


class NvDRS_SettingValues(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("numSettingValues", ctypes.c_uint32),
        ("settingType", ctypes.c_uint32),
        ("defaultValue", _NvDRS_Value),
        ("settingValues", _NvDRS_Value * NVAPI_SETTING_MAX_VALUES),
    ]


class NvDRS_Setting(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("settingName", ctypes.c_wchar * NVAPI_UNICODE_STRING_MAX),
        ("settingId", ctypes.c_uint32),
        ("settingType", ctypes.c_uint32),
        ("settingLocation", ctypes.c_uint32),
        ("isCurrentPredefined", ctypes.c_uint32),
        ("isPredefinedValid", ctypes.c_uint32),
        ("predefined", _NvDRS_Value),
        ("current", _NvDRS_Value),
    ]


# Versions are sizeof | (api_version << 16) — verified against a 2026-era
# driver (natural alignment for profile/application, pack(4) for settings).
NVDRS_PROFILE_VER = ctypes.sizeof(NvDRS_Profile) | (1 << 16)          # 0x11014
NVDRS_APPLICATION_VER = ctypes.sizeof(NvDRS_Application) | (4 << 16)  # 0x4500C
NVDRS_SETTING_VER = ctypes.sizeof(NvDRS_Setting) | (1 << 16)          # 0x13020
NVDRS_SETTING_VALUES_VER = ctypes.sizeof(NvDRS_SettingValues) | (1 << 16)  # 0x751A0


class _Funcs:
    """Resolved NvAPI entry points (lazy singleton)."""

    _IDS = {
        "Initialize": 0x0150E828,
        "EnumPhysicalGPUs": 0xE5AC921F,
        "GPU_GetFullName": 0xCEEE8E9F,
        "GetErrorMessage": 0x6C2D048C,
        "DRS_CreateSession": 0x0694D52E,
        "DRS_DestroySession": 0xDAD9CFF8,
        "DRS_LoadSettings": 0x375DBD6B,
        "DRS_SaveSettings": 0xFCBC7E14,
        "DRS_GetNumProfiles": 0x1DAE4FBC,
        "DRS_EnumProfiles": 0xBC371EE0,
        "DRS_GetProfileInfo": 0x61CD6FD6,
        "DRS_FindProfileByName": 0x7E4A9A0B,
        "DRS_CreateProfile": 0xCC176068,
        "DRS_DeleteProfile": 0x17093206,
        "DRS_GetSettingIdFromName": 0xCB7309CD,
        "DRS_GetSettingNameFromId": 0xD61CBE6E,
        "DRS_EnumSettings": 0xAE3039DA,
        "DRS_GetSetting": 0x73BF8338,
        "DRS_SetSetting": 0x577DD202,
        "DRS_DeleteProfileSetting": 0xE4A26362,
        "DRS_RestoreProfileDefaultSetting": 0x53F0381E,
        "DRS_EnumAvailableSettingValues": 0x2EC39F90,
        "DRS_CreateApplication": 0x4347A9DE,
        "DRS_FindApplicationByName": 0xEEE566B2,
        "DRS_DeleteApplication": 0x2C694BC6,
    }

    def __init__(self) -> None:
        dll_name = "nvapi64.dll"
        self._lib = None
        for name in (dll_name, "nvapi.dll"):
            try:
                self._lib = ctypes.WinDLL(name)
                break
            except OSError as exc:  # noqa: BLE001
                logger.debug(f"nvprofile: could not load {name}: {exc}")
        if self._lib is None:
            raise NvapiError("NVIDIA driver not found (nvapi64.dll not loadable).",
                             NVAPI_DRIVER_NOT_FOUND)

        self._qi = self._lib.nvapi_QueryInterface
        self._qi.restype = ctypes.c_void_p
        self._qi.argtypes = [ctypes.c_uint]

        self.fn: dict[str, ctypes.c_void_p] = {}
        missing = []
        for name, fnid in self._IDS.items():
            ptr = self._qi(fnid)
            if ptr:
                self.fn[name] = ptr
            else:
                missing.append(name)
        if not self.fn.get("Initialize") or not self.fn.get("GetErrorMessage"):
            raise NvapiError(
                "NVIDIA driver does not expose the required NvAPI entry points.",
                NVAPI_NOT_SUPPORTED)
        if missing:
            logger.warning(f"nvprofile: missing entry points: {', '.join(missing)}")

    def fnp(self, name, argtypes, restype=ctypes.c_int):
        """Return a callable ctypes function for a named entry point."""
        ptr = self.fn.get(name)
        if not ptr:
            raise NvapiError(f"NvAPI function {name} is not available.",
                             NVAPI_NOT_SUPPORTED)
        proto = ctypes.WINFUNCTYPE(restype, *argtypes)
        return ctypes.cast(ptr, proto)

    def error_text(self, code: int) -> str:
        try:
            buf = ctypes.create_string_buffer(NVAPI_SHORT_STRING_MAX)
            fn = self.fnp("GetErrorMessage", [ctypes.c_int, ctypes.c_char_p])
            fn(code, buf)
            return buf.value.decode("ascii", "replace") or f"status {code}"
        except Exception:  # noqa: BLE001
            return f"status {code}"


_funcs: _Funcs | None = None


def _get_funcs() -> _Funcs:
    global _funcs
    if _funcs is None:
        _funcs = _Funcs()
    return _funcs


class DrsSession:
    """An open DRS session (also usable as a context manager)."""

    def __init__(self, funcs: _Funcs, session: ctypes.c_void_p) -> None:
        self._f = funcs
        self._handle = session

    # ---- lifecycle ------------------------------------------------------

    def __enter__(self) -> "DrsSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._handle.value:
            try:
                self._f.fnp("DRS_DestroySession", [ctypes.c_void_p])(self._handle)
            except NvapiError:  # noqa: BLE001
                pass
            self._handle.value = None

    def _check(self, code: int, what: str) -> int:
        if code != NVAPI_OK and code not in _EXPECTED:
            logger.warning(f"nvprofile: {what} -> {code} ({self._f.error_text(code)})")
        return code

    # ---- profiles -------------------------------------------------------

    def find_profile(self, name: str):
        """Return the profile handle for ``name``, or ``None`` if absent."""
        h = ctypes.c_void_p()
        fn = self._f.fnp("DRS_FindProfileByName",
                         [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)])
        code = fn(self._handle, name, ctypes.byref(h))
        if code == NVAPI_OK:
            return h
        if code == NVAPI_PROFILE_NOT_FOUND:
            return None
        raise NvapiError(f"FindProfileByName({name!r}) failed: "
                         f"{self._f.error_text(code)}", code)

    def profile_info(self, hprofile) -> dict:
        info = NvDRS_Profile()
        info.version = NVDRS_PROFILE_VER
        fn = self._f.fnp("DRS_GetProfileInfo",
                         [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
        code = fn(self._handle, hprofile, ctypes.byref(info))
        if code != NVAPI_OK:
            raise NvapiError(f"GetProfileInfo failed: {self._f.error_text(code)}", code)
        name = info.profileName[: info.profileName.index("\x00")] \
            if "\x00" in info.profileName else info.profileName
        return {
            "name": name,
            "num_of_apps": info.numOfApps,
            "num_of_settings": info.numOfSettings,
            "is_predefined": bool(info.isPredefined),
        }

    def create_profile(self, name: str):
        """Create a new empty profile and return its handle."""
        info = NvDRS_Profile()
        ctypes.memset(ctypes.byref(info), 0, ctypes.sizeof(info))
        info.version = NVDRS_PROFILE_VER
        info.profileName = name
        h = ctypes.c_void_p()
        fn = self._f.fnp("DRS_CreateProfile",
                         [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)])
        code = fn(self._handle, ctypes.byref(info), ctypes.byref(h))
        if code != NVAPI_OK:
            raise NvapiError(f"CreateProfile({name!r}) failed: "
                             f"{self._f.error_text(code)}", code)
        return h

    def delete_profile(self, hprofile) -> bool:
        fn = self._f.fnp("DRS_DeleteProfile", [ctypes.c_void_p, ctypes.c_void_p])
        code = fn(self._handle, hprofile)
        return code == NVAPI_OK

    def ensure_profile(self, name: str, exe_names: list[str] | None = None):
        """Return (handle, created). Reuses an existing driver profile when
        present, otherwise creates one and attaches ``exe_names`` to it."""
        h = self.find_profile(name)
        if h is not None:
            return h, False
        h = self.create_profile(name)
        created = True
        for exe in exe_names or []:
            try:
                self.create_application(h, exe)
            except NvapiError as exc:  # noqa: BLE001
                logger.warning(f"nvprofile: attach {exe!r} to {name!r}: {exc}")
        return h, created

    # ---- applications ---------------------------------------------------

    def create_application(self, hprofile, exe_name: str,
                           friendly_name: str | None = None) -> None:
        app = NvDRS_Application()
        ctypes.memset(ctypes.byref(app), 0, ctypes.sizeof(app))
        app.version = NVDRS_APPLICATION_VER
        app.appName = exe_name
        app.userFriendlyName = friendly_name or exe_name
        fn = self._f.fnp("DRS_CreateApplication",
                         [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
        code = fn(self._handle, hprofile, ctypes.byref(app))
        if code != NVAPI_OK:
            raise NvapiError(f"CreateApplication({exe_name!r}) failed: "
                             f"{self._f.error_text(code)}", code)

    def find_application(self, exe_name: str):
        """Return the profile handle that currently owns ``exe_name``, or None."""
        h = ctypes.c_void_p()
        app = NvDRS_Application()
        ctypes.memset(ctypes.byref(app), 0, ctypes.sizeof(app))
        app.version = NVDRS_APPLICATION_VER
        fn = self._f.fnp("DRS_FindApplicationByName",
                         [ctypes.c_void_p, ctypes.c_wchar_p,
                          ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p])
        code = fn(self._handle, exe_name, ctypes.byref(h), ctypes.byref(app))
        if code == NVAPI_OK:
            return h
        if code in (NVAPI_APPLICATION_NOT_FOUND, NVAPI_EXECUTABLE_PATH_IS_AMBIGUOUS):
            return None
        raise NvapiError(f"FindApplicationByName({exe_name!r}) failed: "
                         f"{self._f.error_text(code)}", code)

    def delete_application(self, hprofile, exe_name: str) -> bool:
        fn = self._f.fnp("DRS_DeleteApplication",
                         [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p])
        code = fn(self._handle, hprofile, exe_name)
        return code == NVAPI_OK

    # ---- settings -------------------------------------------------------

    def setting_id(self, names: list[str]) -> int | None:
        """Resolve the DRS setting id from a list of candidate display names."""
        fn = self._f.fnp("DRS_GetSettingIdFromName",
                         [ctypes.c_wchar_p, ctypes.POINTER(w.DWORD)])
        for name in names:
            sid = w.DWORD()
            code = fn(name, ctypes.byref(sid))
            if code == NVAPI_OK:
                return sid.value
        return None

    def setting_name(self, setting_id: int) -> str | None:
        fn = self._f.fnp("DRS_GetSettingNameFromId", [w.DWORD, ctypes.c_wchar_p])
        buf = ctypes.create_unicode_buffer(NVAPI_UNICODE_STRING_MAX)
        code = fn(setting_id, buf)
        if code != NVAPI_OK:
            return None
        return buf.value

    def get_setting(self, hprofile, setting_id: int) -> NvDRS_Setting | None:
        """Read a setting from a profile; ``None`` when it is not set there."""
        s = NvDRS_Setting()
        ctypes.memset(ctypes.byref(s), 0, ctypes.sizeof(s))
        s.version = NVDRS_SETTING_VER
        fn = self._f.fnp("DRS_GetSetting",
                         [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p])
        code = fn(self._handle, hprofile, setting_id, ctypes.byref(s))
        if code == NVAPI_OK:
            return s
        if code == NVAPI_SETTING_NOT_FOUND:
            return None
        raise NvapiError(f"GetSetting(0x{setting_id:08X}) failed: "
                         f"{self._f.error_text(code)}", code)

    def get_setting_dword(self, hprofile, setting_id: int) -> int | None:
        s = self.get_setting(hprofile, setting_id)
        if s is None:
            return None
        return s.current.u32

    def set_setting_dword(self, hprofile, setting_id: int, value: int) -> None:
        s = NvDRS_Setting()
        ctypes.memset(ctypes.byref(s), 0, ctypes.sizeof(s))
        s.version = NVDRS_SETTING_VER
        s.settingId = setting_id
        s.settingType = NVDRS_DWORD_TYPE
        s.settingLocation = 0  # NVDRS_CURRENT_PROFILE_LOCATION
        s.current.u32 = value & 0xFFFFFFFF
        fn = self._f.fnp("DRS_SetSetting",
                         [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
        code = fn(self._handle, hprofile, ctypes.byref(s))
        if code != NVAPI_OK:
            raise NvapiError(f"SetSetting(0x{setting_id:08X}={value}) failed: "
                             f"{self._f.error_text(code)}", code)

    def delete_setting(self, hprofile, setting_id: int) -> bool:
        fn = self._f.fnp("DRS_DeleteProfileSetting",
                         [ctypes.c_void_p, ctypes.c_void_p, w.DWORD])
        code = fn(self._handle, hprofile, setting_id)
        return code == NVAPI_OK

    def enum_setting_values(self, setting_id: int) -> list[int]:
        """Return the driver's known DWORD values for a setting id."""
        maxn = w.DWORD(NVAPI_SETTING_MAX_VALUES)
        arr = (NvDRS_SettingValues * 1)()
        arr[0].version = NVDRS_SETTING_VALUES_VER
        fn = self._f.fnp("DRS_EnumAvailableSettingValues",
                         [w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p])
        code = fn(setting_id, ctypes.byref(maxn), ctypes.byref(arr))
        if code != NVAPI_OK:
            return []
        return [arr[0].settingValues[i].u32 for i in range(maxn.value)]

    # ---- save -----------------------------------------------------------

    def save(self) -> None:
        fn = self._f.fnp("DRS_SaveSettings", [ctypes.c_void_p])
        code = fn(self._handle)
        if code != NVAPI_OK:
            raise NvapiError(f"SaveSettings failed ({self._f.error_text(code)}). "
                             "Run Maximum Tweaks as administrator.",
                             code)


class Nvapi:
    """Top-level NvAPI handle."""

    def __init__(self) -> None:
        self._f = _get_funcs()

    @classmethod
    def available(cls) -> bool:
        try:
            nv = cls()
            nv._f.fnp("Initialize", [])()
            return True
        except (NvapiError, OSError):  # noqa: BLE001
            return False

    def session(self) -> DrsSession:
        """Open + load a DRS session (close it or use as a context manager)."""
        fn = self._f.fnp("DRS_CreateSession", [ctypes.POINTER(ctypes.c_void_p)])
        h = ctypes.c_void_p()
        code = fn(ctypes.byref(h))
        if code != NVAPI_OK:
            raise NvapiError(f"DRS_CreateSession failed: {self._f.error_text(code)}", code)
        load = self._f.fnp("DRS_LoadSettings", [ctypes.c_void_p])
        code = load(h)
        if code != NVAPI_OK:
            raise NvapiError(f"DRS_LoadSettings failed: {self._f.error_text(code)}", code)
        return DrsSession(self._f, h)

    def gpu_names(self) -> list[str]:
        handles = (ctypes.c_void_p * NVAPI_MAX_PHYSICAL_GPUS)()
        count = w.DWORD()
        fn = self._f.fnp("EnumPhysicalGPUs", [ctypes.c_void_p, ctypes.POINTER(w.DWORD)])
        code = fn(handles, ctypes.byref(count))
        if code != NVAPI_OK:
            raise NvapiError(f"EnumPhysicalGPUs failed: {self._f.error_text(code)}", code)
        names = []
        get_name = self._f.fnp("GPU_GetFullName", [ctypes.c_void_p, ctypes.c_char_p])
        for i in range(min(count.value, NVAPI_MAX_PHYSICAL_GPUS)):
            buf = ctypes.create_string_buffer(NVAPI_SHORT_STRING_MAX)
            if get_name(handles[i], buf) == NVAPI_OK:
                names.append(buf.value.decode("ascii", "replace"))
        return names

    def error_text(self, code: int) -> str:
        return self._f.error_text(code)
