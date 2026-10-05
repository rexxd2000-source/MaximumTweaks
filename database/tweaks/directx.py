"""Category: DirectX — runtime checks and DirectX behaviour."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("DirectX", win_default="7,8,10,11")
CATEGORY = "DirectX"
_ALL_GPU = {"gpu": ["nvidia", "amd", "intel"]}

TWEAKS = validate_module("directx", [
    T("dx-001", "Run DirectX Diagnostic",
      "Launches dxdiag to dump the graphics stack.",
      actions=[("cmd", "start dxdiag")],
      revert=[("guidance", "Close the dxdiag window.")],
      why="A dxdiag report shows driver, display and DirectX feature level details useful before tuning.",
      changes="Opens the DirectX Diagnostic Tool.",
      risk="safe", impact="very low", recommended="recommended",
      when=_ALL_GPU,
      tags=["dxdiag", "diagnostics", "gpu"]),
    T("dx-003", "Check DirectX 12 Support",
      "Reports whether the GPU supports feature level 12.",
      actions=[("cmd", "dxdiag /whql:off /t %TEMP%\\dxdiag.txt")],
      revert=[("guidance", "No change to revert.")],
      why="Feature level 12.x gates modern effects in DX12 games.",
      changes="Writes a dxdiag report to the temp folder.",
      risk="safe", impact="very low", recommended="recommended",
      when=_ALL_GPU,
      tags=["dx12", "featurelevel", "gpu"]),
])
