"""Parser for NVIDIA Profile Inspector .nip export files.

.nip files are XML in the format:
  <ArrayOfProfile>
    <Profile>
      <ProfileName>Fortnite</ProfileName>
      <Executeables><string>exe.exe</string>...</Executeables>
      <Settings>
        <ProfileSetting>
          <SettingNameInfo>...</SettingNameInfo>
          <SettingID>12345</SettingID>
          <SettingValue>0</SettingValue>
          <ValueType>Dword</ValueType>
        </ProfileSetting>
      </Settings>
    </Profile>
  </ArrayOfProfile>

This module parses them into a structure usable by the nvprofiles engine.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class NipSetting:
    name: str
    setting_id: int
    value: int | str
    value_type: str  # "Dword" or "String"

    def value_as_int(self) -> Optional[int]:
        if self.value_type == "Dword":
            try:
                return int(self.value)
            except (ValueError, TypeError):
                return None
        return None


@dataclass
class NipProfile:
    name: str
    exes: list[str] = field(default_factory=list)
    settings: list[NipSetting] = field(default_factory=list)


def parse_nip(path: str | os.PathLike) -> Optional[NipProfile]:
    """Parse a single .nip file and return the first profile found."""
    path = Path(path)
    if not path.exists():
        return None

    try:
        raw = path.read_bytes()
        if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
            text = raw.decode("utf-16")
        elif raw[:3] == b'\xef\xbb\xbf':
            text = raw.decode("utf-8-sig")
        else:
            text = raw.decode("utf-8")
        root = ET.fromstring(text)
    except (ET.ParseError, UnicodeDecodeError):
        return None
    profile_el = root.find("Profile")
    if profile_el is None:
        return None

    name_el = profile_el.find("ProfileName")
    name = name_el.text.strip() if name_el is not None and name_el.text else path.stem

    exes = []
    exes_el = profile_el.find("Executeables")
    if exes_el is not None:
        for s in exes_el.findall("string"):
            if s.text:
                exes.append(s.text.strip())

    settings = []
    settings_el = profile_el.find("Settings")
    if settings_el is not None:
        for ps in settings_el.findall("ProfileSetting"):
            name_info_el = ps.find("SettingNameInfo")
            sid_el = ps.find("SettingID")
            val_el = ps.find("SettingValue")
            vtype_el = ps.find("ValueType")

            if sid_el is None or val_el is None:
                continue

            try:
                sid = int(sid_el.text)
            except (ValueError, TypeError):
                continue

            value_text = val_el.text.strip() if val_el.text else "0"
            value_type = vtype_el.text.strip() if vtype_el is not None and vtype_el.text else "Dword"

            setting_name = name_info_el.text.strip() if name_info_el is not None and name_info_el.text else f"Setting {sid}"

            if value_type == "Dword":
                try:
                    value = int(value_text)
                except (ValueError, TypeError):
                    value = 0
            else:
                value = value_text

            settings.append(NipSetting(
                name=setting_name,
                setting_id=sid,
                value=value,
                value_type=value_type,
            ))

    return NipProfile(name=name, exes=exes, settings=settings)


def load_all_profiles(profiles_dir: str | os.PathLike) -> dict[str, NipProfile]:
    """Load all .nip files from a directory. Returns dict keyed by filename stem."""
    profiles = {}
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.exists():
        return profiles

    for nip_file in sorted(profiles_dir.glob("*.nip")):
        profile = parse_nip(nip_file)
        if profile is not None:
            profiles[nip_file.stem] = profile

    return profiles


def game_id_for_profile(profile: NipProfile) -> Optional[str]:
    """Map a profile name to a known GAMES key."""
    from engine.nvprofiles import GAMES
    name_lower = profile.name.lower().strip()
    for gid, meta in GAMES.items():
        game_name = meta["name"].lower()
        if game_name == name_lower or game_name in name_lower or name_lower in game_name:
            return gid
        for candidate in meta.get("profile_candidates", []):
            cand = candidate.lower()
            if cand == name_lower or cand in name_lower or name_lower in cand:
                return gid
    return None
