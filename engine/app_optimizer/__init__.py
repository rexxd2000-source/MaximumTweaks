"""App Optimizers — deep, real, reversible per-app debloat.

Public entry points (all pure Python, no Qt):
  * detect()                    -> current state of the five tracked apps
  * activate(key, option_ids)   -> run a plan's ops; returns (errors, changed)
  * reset(key)                  -> walk the ledger back and restore everything
  * optimize_all()              -> sequential Optimize All over installed apps
  * triage(engaged)             -> one pass re-applying live scheduling levers
  * engaged_keys()              -> which apps currently have a ledger
  * refresh_watcher()           -> add/drop the triage watcher task
  * is_admin()                  -> whether hosts/Program-Files ops will work in-process

The engine keeps no hardcoded "defaults" for revert: every op snapshots the
exact pre-state (file contents, registry values, hosts file, task State,
service start type, shortcut arguments) into a per-app ledger under
``%LOCALAPPDATA%/MaximumTweaks/app_optimizer`` and restores precisely that on
reset.

Two kinds of change are made, and the distinction matters:

* **Persistent** changes (files, registry, services, shortcut arguments) are
  snapshotted into the ledger and reverted exactly by ``reset``.
* **Live** changes (process priority class, CPU affinity, EcoQoS, suppressing
  helper child processes) cannot be written to disk, because they are
  properties of a running process. They are re-applied after every launch by
  the triage watcher, and ``reset`` puts the live processes back to normal.
"""
from engine.app_optimizer.apps import (  # noqa: F401
    activate,
    detect,
    engaged_keys,
    optimize_all,
    refresh_watcher,
    reset,
    restart_engaged,
    triage,
)
from engine.app_optimizer.core import APP_OPT_DIR, is_admin  # noqa: F401

__all__ = ["detect", "activate", "reset", "optimize_all", "is_admin",
           "APP_OPT_DIR", "triage", "engaged_keys", "refresh_watcher",
           "restart_engaged"]
