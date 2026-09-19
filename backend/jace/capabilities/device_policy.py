from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceCapabilityDefinition:
    id: str
    title: str
    description: str
    risk: str
    read_only: bool
    enabled: bool = True


DEVICE_CAPABILITY_CATALOG: dict[str, DeviceCapabilityDefinition] = {
    "system.info": DeviceCapabilityDefinition(
        id="system.info",
        title="System information",
        description="Read operating-system, host, Python and Device Agent information.",
        risk="low",
        read_only=True,
    ),
    "process.list": DeviceCapabilityDefinition(
        id="process.list",
        title="List processes",
        description="Read a bounded list of process metadata without modifying processes.",
        risk="low",
        read_only=True,
    ),
    "filesystem.list": DeviceCapabilityDefinition(
        id="filesystem.list",
        title="List directory",
        description="List immediate directory-entry metadata without reading file contents.",
        risk="low",
        read_only=True,
    ),
}


def is_device_capability_allowed(capability: str) -> bool:
    definition = DEVICE_CAPABILITY_CATALOG.get(capability)
    return bool(
        definition
        and definition.enabled
        and definition.read_only
        and definition.risk == "low"
    )
