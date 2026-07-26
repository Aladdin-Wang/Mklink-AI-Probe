"""ResourceManager — Dashboard / AI 资源租约管理。

协调 MKLink Bridge、Serial Port、Modbus Port 三类资源的互斥访问。
优先级规则：user:* > ai:*，用户操作可强制抢占 AI 租约。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class ResourceGroup(Enum):
    MKLINK_BRIDGE = "mklink_bridge"
    TARGET_DEBUG = "target_debug"
    SERIAL_PORT = "serial_port"
    MODBUS_PORT = "modbus_port"


@dataclass
class ResourceLease:
    owner: str
    resource: ResourceGroup
    acquired_at: float = field(default_factory=time.monotonic)
    expires_at: float | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and time.monotonic() > self.expires_at

    @property
    def is_user(self) -> bool:
        return self.owner.startswith("user:")

    @property
    def is_ai(self) -> bool:
        return self.owner.startswith("ai:")


class ResourceError(Exception):
    def __init__(self, conflict_owner: str, resource: ResourceGroup):
        self.conflict_owner = conflict_owner
        self.resource = resource
        super().__init__(f"Resource {resource.value} is held by {conflict_owner}")


class ResourceManager:
    def __init__(self):
        self._leases: dict[ResourceGroup, ResourceLease] = {}
        self._on_preempt: list[Callable[[ResourceLease, str], None]] = []
        self._lock = threading.RLock()

    def on_preempt(self, callback: Callable[[ResourceLease, str], None]):
        """注册抢占回调。当 AI 租约被用户抢占时触发。"""
        with self._lock:
            self._on_preempt.append(callback)

    def acquire(
        self,
        resource: ResourceGroup,
        owner: str,
        ttl: float | None = None,
        preempt: bool = False,
        preempt_user_dashboard: bool = False,
    ) -> ResourceLease:
        """获取或刷新资源租约，按显式策略抢占 AI 或用户 Dashboard。"""
        with self._lock:
            lease, preempted = self._acquire_locked(
                resource, owner, ttl, preempt, preempt_user_dashboard,
            )
        if preempted is not None:
            try:
                self._notify_preempt(preempted, owner)
            except Exception:
                with self._lock:
                    current = self._leases.get(resource)
                    if current is lease:
                        self._leases[resource] = preempted
                raise
        return lease

    def acquire_many(
        self,
        resources: list[ResourceGroup] | tuple[ResourceGroup, ...],
        owner: str,
        ttl: float | None = None,
        preempt: bool = False,
        preempt_user_dashboard: bool = False,
    ) -> list[ResourceLease]:
        """Acquire all resources atomically and preserve prior owner leases."""
        unique_resources = list(dict.fromkeys(resources))
        preempted: list[ResourceLease] = []
        with self._lock:
            previous = {
                resource: self._leases.get(resource) for resource in unique_resources
            }
            try:
                leases = []
                for resource in unique_resources:
                    lease, displaced = self._acquire_locked(
                        resource, owner, ttl, preempt, preempt_user_dashboard,
                    )
                    leases.append(lease)
                    if displaced is not None:
                        preempted.append(displaced)
            except ResourceError:
                for resource, old_lease in previous.items():
                    if old_lease is None:
                        self._leases.pop(resource, None)
                    else:
                        self._leases[resource] = old_lease
                raise
        notified_owners: set[str] = set()
        try:
            for displaced in preempted:
                if displaced.owner in notified_owners:
                    continue
                self._notify_preempt(displaced, owner)
                notified_owners.add(displaced.owner)
        except Exception:
            with self._lock:
                for resource, old_lease in previous.items():
                    current = self._leases.get(resource)
                    if current is None or current.owner == owner:
                        if old_lease is None:
                            self._leases.pop(resource, None)
                        else:
                            self._leases[resource] = old_lease
            raise
        return leases

    def _acquire_locked(
        self,
        resource: ResourceGroup,
        owner: str,
        ttl: float | None,
        preempt: bool,
        preempt_user_dashboard: bool,
    ) -> tuple[ResourceLease, ResourceLease | None]:
        existing = self._leases.get(resource)
        if existing and existing.is_expired:
            del self._leases[resource]
            existing = None

        if existing is None or existing.owner == owner:
            lease = self._make_lease(resource, owner, ttl)
            self._leases[resource] = lease
            return lease, None

        if preempt and owner.startswith("user:") and existing.is_ai:
            lease = self._make_lease(resource, owner, ttl)
            self._leases[resource] = lease
            return lease, existing

        if (
            preempt_user_dashboard
            and owner.startswith("user:")
            and existing.owner.startswith("user:dashboard:")
        ):
            lease = self._make_lease(resource, owner, ttl)
            self._leases[resource] = lease
            return lease, existing

        raise ResourceError(existing.owner, resource)

    def release(self, owner: str) -> list[ResourceGroup]:
        """释放指定所有者的所有租约。返回被释放的资源列表。"""
        with self._lock:
            released = []
            for resource, lease in list(self._leases.items()):
                if lease.owner == owner:
                    del self._leases[resource]
                    released.append(resource)
            return released

    def release_all(self) -> None:
        """释放所有租约。"""
        with self._lock:
            self._leases.clear()

    def get_active_lease(self, resource: ResourceGroup) -> ResourceLease | None:
        """获取指定资源的活跃租约。"""
        with self._lock:
            lease = self._leases.get(resource)
            if lease and lease.is_expired:
                del self._leases[resource]
                return None
            return lease

    def get_status(self) -> dict:
        """返回所有资源的当前状态。"""
        with self._lock:
            for resource in list(self._leases):
                lease = self._leases.get(resource)
                if lease and lease.is_expired:
                    del self._leases[resource]
            return {
                resource.value: {
                    "owner": lease.owner,
                    "acquired_at": lease.acquired_at,
                    "expires_at": lease.expires_at,
                    "is_user": lease.is_user,
                    "is_ai": lease.is_ai,
                }
                for resource, lease in self._leases.items()
            }

    def _make_lease(
        self, resource: ResourceGroup, owner: str, ttl: float | None
    ) -> ResourceLease:
        now = time.monotonic()
        return ResourceLease(
            owner=owner,
            resource=resource,
            acquired_at=now,
            expires_at=now + ttl if ttl else None,
        )

    def _notify_preempt(self, lease: ResourceLease, new_owner: str):
        with self._lock:
            callbacks = list(self._on_preempt)
        for callback in callbacks:
            callback(lease, new_owner)
