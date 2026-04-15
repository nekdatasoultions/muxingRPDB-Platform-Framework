"""Smart allocation helpers for RPDB customer provisioning."""

from __future__ import annotations

import copy
import ipaddress
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .customer_merge import load_yaml_file
from .customer_model import parse_customer_source


POOL_CLASS_ALIASES = {
    "nat": "nat",
    "non-nat": "non-nat",
    "nonnat": "non-nat",
    "strict-non-nat": "non-nat",
    "strict_non_nat": "non-nat",
}

EXCLUSIVE_RESOURCE_TYPES = (
    "customer_id",
    "fwmark",
    "route_table",
    "rpdb_priority",
    "tunnel_key",
    "overlay_block",
    "transport_interface",
    "vti_interface",
)

SHARED_TRACKED_RESOURCE_TYPES = (
    "backend_assignment",
    "backend_role",
)


def load_allocation_pools(path: str | Path) -> Dict[str, Any]:
    return load_yaml_file(path)


def discover_customer_source_paths(*search_roots: str | Path) -> List[Path]:
    candidates: dict[str, Path] = {}
    for root in search_roots:
        path = Path(root).resolve()
        if path.is_file():
            candidates[str(path)] = path
            continue
        if not path.exists():
            continue
        for candidate in sorted(path.rglob("customer.yaml")):
            if candidate.is_file():
                candidates[str(candidate.resolve())] = candidate.resolve()
    return [candidates[key] for key in sorted(candidates)]


def load_customer_source_docs(*search_roots: str | Path) -> List[Dict[str, Any]]:
    return [load_yaml_file(path) for path in discover_customer_source_paths(*search_roots)]


def normalize_pool_class(customer_class: str, backend_cluster: str = "") -> str:
    normalized_class = POOL_CLASS_ALIASES.get(str(customer_class or "").strip().lower())
    if not normalized_class:
        raise ValueError(f"unsupported customer_class {customer_class!r}")

    if backend_cluster:
        normalized_cluster = POOL_CLASS_ALIASES.get(str(backend_cluster).strip().lower())
        if not normalized_cluster:
            raise ValueError(f"unsupported backend.cluster {backend_cluster!r}")
        if normalized_cluster != normalized_class:
            raise ValueError(
                f"customer_class={customer_class!r} conflicts with backend.cluster={backend_cluster!r}"
            )

    return normalized_class


def empty_allocation_inventory() -> Dict[str, Any]:
    return {
        "customer_name": set(),
        "customer_id": set(),
        "fwmark": set(),
        "route_table": set(),
        "rpdb_priority": set(),
        "tunnel_key": set(),
        "overlay_block": set(),
        "transport_interface": set(),
        "vti_interface": set(),
        "backend_assignment_counts": {},
        "backend_role_counts": {},
        "customers": {},
    }


def _pool_value(pool_doc: Dict[str, Any], slot_index: int) -> int:
    start = int(pool_doc["start"])
    step = int(pool_doc.get("step") or 1)
    return start + (slot_index * step)


def _pool_capacity(pool_doc: Dict[str, Any]) -> int:
    start = int(pool_doc["start"])
    end = int(pool_doc["end"])
    step = int(pool_doc.get("step") or 1)
    if end < start:
        raise ValueError(f"invalid pool range start={start} end={end}")
    return ((end - start) // step) + 1


def _format_numeric_resource(pool_doc: Dict[str, Any], value: int) -> str:
    if str(pool_doc.get("format") or "").strip().lower() == "hex":
        return hex(value)
    return str(value)


def _overlay_block(pool_doc: Dict[str, Any], slot_index: int) -> ipaddress.IPv4Network:
    network = ipaddress.ip_network(str(pool_doc["network"]), strict=False)
    prefixlen = int(pool_doc["prefixlen"])
    start_index = int(pool_doc.get("start_index") or 0)
    subnets = list(network.subnets(new_prefix=prefixlen))
    wanted_index = start_index + slot_index
    if wanted_index >= len(subnets):
        raise ValueError(
            f"overlay pool {network} with /{prefixlen} cannot satisfy slot {slot_index}"
        )
    return subnets[wanted_index]


def _overlay_capacity(pool_doc: Dict[str, Any]) -> int:
    network = ipaddress.ip_network(str(pool_doc["network"]), strict=False)
    prefixlen = int(pool_doc["prefixlen"])
    start_index = int(pool_doc.get("start_index") or 0)
    return len(list(network.subnets(new_prefix=prefixlen))) - start_index


def _overlay_endpoints(block: ipaddress.IPv4Network) -> Dict[str, str]:
    prefixlen = block.prefixlen
    base = int(block.network_address)
    return {
        "mux_ip": f"{ipaddress.IPv4Address(base + 1)}/{prefixlen}",
        "router_ip": f"{ipaddress.IPv4Address(base + 2)}/{prefixlen}",
    }


def _render_interface_name(template: str, *, customer_id: int, slot_index: int) -> str:
    return str(template).format(
        customer_id=customer_id,
        slot_index=slot_index,
        slot=slot_index + 1,
    )


def _truthy_request_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "enable"}


def request_uses_vti(request_doc: Dict[str, Any]) -> bool:
    ipsec_doc = ((request_doc.get("customer") or {}).get("ipsec") or {})
    return any(
        _truthy_request_flag(ipsec_doc.get(key))
        for key in ("vti_routing", "vti_shared")
    )


def collect_customer_source_allocations(source_doc: Dict[str, Any]) -> Dict[str, Any]:
    source = parse_customer_source(source_doc)
    backend = source.customer.backend
    ipsec_cfg = source.customer.ipsec
    transport = source.customer.transport
    pool_class = normalize_pool_class(
        source.customer.customer_class,
        backend.cluster if backend else "",
    )
    overlay_block = str(ipaddress.ip_interface(transport.overlay.mux_ip).network)
    return {
        "customer_name": source.customer.name,
        "pool_class": pool_class,
        "customer_id": int(source.customer.id),
        "fwmark": int(str(transport.mark), 0),
        "route_table": int(transport.table),
        "rpdb_priority": (
            int(transport.rpdb_priority)
            if transport.rpdb_priority is not None
            else None
        ),
        "tunnel_key": int(transport.tunnel_key),
        "overlay_block": overlay_block,
        "transport_interface": str(transport.interface),
        "vti_interface": str(ipsec_cfg.vti_interface) if ipsec_cfg else "",
        "backend_assignment": str(backend.assignment) if backend else "",
        "backend_role": str(backend.role) if backend else "",
    }


def build_allocation_inventory(customer_source_docs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    inventory = empty_allocation_inventory()
    for source_doc in customer_source_docs:
        alloc = collect_customer_source_allocations(source_doc)
        customer_name = str(alloc["customer_name"])
        inventory["customer_name"].add(customer_name)
        inventory["customer_id"].add(int(alloc["customer_id"]))
        inventory["fwmark"].add(int(alloc["fwmark"]))
        inventory["route_table"].add(int(alloc["route_table"]))
        if alloc["rpdb_priority"] is not None:
            inventory["rpdb_priority"].add(int(alloc["rpdb_priority"]))
        inventory["tunnel_key"].add(int(alloc["tunnel_key"]))
        inventory["overlay_block"].add(str(alloc["overlay_block"]))
        inventory["transport_interface"].add(str(alloc["transport_interface"]))
        if str(alloc["vti_interface"]).strip():
            inventory["vti_interface"].add(str(alloc["vti_interface"]).strip())

        backend_assignment = str(alloc["backend_assignment"]).strip()
        if backend_assignment:
            counts = inventory["backend_assignment_counts"]
            counts[backend_assignment] = int(counts.get(backend_assignment, 0)) + 1

        backend_role = str(alloc["backend_role"]).strip()
        if backend_role:
            counts = inventory["backend_role_counts"]
            counts[backend_role] = int(counts.get(backend_role, 0)) + 1

        inventory["customers"][customer_name] = alloc
    return inventory


def validate_customer_allocations(
    customer_source_docs: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    seen: Dict[str, Dict[str, str]] = {resource: {} for resource in EXCLUSIVE_RESOURCE_TYPES}
    collisions: List[Dict[str, str]] = []
    inventory = build_allocation_inventory(customer_source_docs)

    for customer_name in sorted(inventory["customers"]):
        alloc = inventory["customers"][customer_name]
        for resource in EXCLUSIVE_RESOURCE_TYPES:
            raw_value = alloc.get(resource)
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if not value:
                continue
            if value in seen[resource]:
                collisions.append(
                    {
                        "resource_type": resource,
                        "resource_value": value,
                        "first_customer": seen[resource][value],
                        "second_customer": customer_name,
                    }
                )
                continue
            seen[resource][value] = customer_name

    return {
        "valid": not collisions,
        "customer_count": len(inventory["customers"]),
        "exclusive_resources_checked": list(EXCLUSIVE_RESOURCE_TYPES),
        "collisions": collisions,
        "backend_assignment_counts": dict(sorted(inventory["backend_assignment_counts"].items())),
        "backend_role_counts": dict(sorted(inventory["backend_role_counts"].items())),
    }


def _class_pools(pools_doc: Dict[str, Any], pool_class: str) -> Dict[str, Any]:
    pools = pools_doc.get("pools") or {}
    resolved: Dict[str, Any] = {}
    for name, pool_value in pools.items():
        if isinstance(pool_value, dict) and pool_class in pool_value:
            resolved[name] = copy.deepcopy(pool_value[pool_class])
    required = {
        "customer_id",
        "fwmark",
        "route_table",
        "rpdb_priority",
        "tunnel_key",
        "overlay_block",
        "transport_interface",
        "backend_role",
    }
    missing = sorted(required - set(resolved))
    if missing:
        raise ValueError(f"missing allocation pools for {pool_class}: {', '.join(missing)}")
    return resolved


def _slot_limit(class_pools: Dict[str, Any]) -> int:
    capacities = [
        _pool_capacity(class_pools["customer_id"]),
        _pool_capacity(class_pools["fwmark"]),
        _pool_capacity(class_pools["route_table"]),
        _pool_capacity(class_pools["rpdb_priority"]),
        _pool_capacity(class_pools["tunnel_key"]),
        _overlay_capacity(class_pools["overlay_block"]),
    ]
    return min(capacities)


def _choose_backend_assignment(
    requested_assignment: str,
    assignment_pool: Dict[str, Any] | None,
    inventory: Dict[str, Any],
) -> str:
    options = list((assignment_pool or {}).get("options") or [])
    if requested_assignment:
        if options and requested_assignment not in options:
            raise ValueError(
                f"backend.assignment {requested_assignment!r} is not present in the allocation pool options"
            )
        return requested_assignment

    if not options:
        return ""

    counts = inventory.get("backend_assignment_counts") or {}
    return sorted(options, key=lambda option: (int(counts.get(option, 0)), option))[0]


def _choose_backend_role(requested_role: str, role_pool: Dict[str, Any]) -> str:
    if requested_role:
        pool_value = str(role_pool.get("value") or "").strip()
        if pool_value and requested_role != pool_value:
            raise ValueError(
                f"backend.role {requested_role!r} does not match the pool default {pool_value!r}"
            )
        return requested_role
    return str(role_pool.get("value") or "").strip()


def _candidate_plan_for_slot(
    request_doc: Dict[str, Any],
    class_pools: Dict[str, Any],
    slot_index: int,
    inventory: Dict[str, Any],
) -> Dict[str, Any] | None:
    customer_doc = request_doc.get("customer") or {}
    backend_doc = customer_doc.get("backend") or {}
    wants_vti = request_uses_vti(request_doc)

    customer_id = _pool_value(class_pools["customer_id"], slot_index)
    fwmark_int = _pool_value(class_pools["fwmark"], slot_index)
    route_table = _pool_value(class_pools["route_table"], slot_index)
    rpdb_priority = _pool_value(class_pools["rpdb_priority"], slot_index)
    tunnel_key = _pool_value(class_pools["tunnel_key"], slot_index)
    overlay_block = _overlay_block(class_pools["overlay_block"], slot_index)
    overlay = _overlay_endpoints(overlay_block)
    transport_interface = _render_interface_name(
        str(class_pools["transport_interface"]["template"]),
        customer_id=customer_id,
        slot_index=slot_index,
    )

    vti_interface = ""
    if wants_vti and class_pools.get("vti_interface"):
        vti_interface = _render_interface_name(
            str(class_pools["vti_interface"]["template"]),
            customer_id=customer_id,
            slot_index=slot_index,
        )

    if customer_id in inventory["customer_id"]:
        return None
    if fwmark_int in inventory["fwmark"]:
        return None
    if route_table in inventory["route_table"]:
        return None
    if rpdb_priority in inventory["rpdb_priority"]:
        return None
    if tunnel_key in inventory["tunnel_key"]:
        return None
    if str(overlay_block) in inventory["overlay_block"]:
        return None
    if transport_interface in inventory["transport_interface"]:
        return None
    if vti_interface and vti_interface in inventory["vti_interface"]:
        return None

    backend_assignment = _choose_backend_assignment(
        str(backend_doc.get("assignment") or "").strip(),
        class_pools.get("backend_assignment"),
        inventory,
    )
    backend_role = _choose_backend_role(
        str(backend_doc.get("role") or "").strip(),
        class_pools["backend_role"],
    )

    return {
        "pool_class": normalize_pool_class(
            str(customer_doc.get("customer_class") or ""),
            str(backend_doc.get("cluster") or ""),
        ),
        "slot_index": slot_index,
        "customer_id": customer_id,
        "fwmark": _format_numeric_resource(class_pools["fwmark"], fwmark_int),
        "fwmark_int": fwmark_int,
        "route_table": route_table,
        "rpdb_priority": rpdb_priority,
        "tunnel_key": tunnel_key,
        "overlay_block": str(overlay_block),
        "overlay": overlay,
        "transport_interface": transport_interface,
        "vti_interface": vti_interface,
        "backend_assignment": backend_assignment,
        "backend_role": backend_role,
    }


def plan_customer_allocations(
    request_doc: Dict[str, Any],
    pools_doc: Dict[str, Any],
    inventory: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    working_inventory = inventory or empty_allocation_inventory()
    customer_doc = request_doc.get("customer") or {}
    customer_name = str(customer_doc.get("name") or "").strip()
    if not customer_name:
        raise ValueError("customer.name is required")
    if customer_name in working_inventory["customer_name"]:
        raise ValueError(f"customer.name {customer_name!r} is already present in the allocation inventory")

    pool_class = normalize_pool_class(
        str(customer_doc.get("customer_class") or ""),
        str(((customer_doc.get("backend") or {}).get("cluster") or "")),
    )
    class_pools = _class_pools(pools_doc, pool_class)

    for slot_index in range(_slot_limit(class_pools)):
        candidate = _candidate_plan_for_slot(request_doc, class_pools, slot_index, working_inventory)
        if candidate is not None:
            return candidate

    raise ValueError(f"no free allocation slot remains for pool class {pool_class}")


def render_allocated_customer_source(request_doc: Dict[str, Any], allocation_plan: Dict[str, Any]) -> Dict[str, Any]:
    customer_doc = copy.deepcopy(request_doc.get("customer") or {})
    backend_doc = copy.deepcopy(customer_doc.get("backend") or {})
    ipsec_doc = copy.deepcopy(customer_doc.get("ipsec") or {})

    pool_class = str(allocation_plan["pool_class"])
    backend_doc["cluster"] = str(backend_doc.get("cluster") or pool_class)
    if allocation_plan.get("backend_assignment"):
        backend_doc["assignment"] = str(allocation_plan["backend_assignment"])
    if allocation_plan.get("backend_role"):
        backend_doc["role"] = str(allocation_plan["backend_role"])

    if allocation_plan.get("vti_interface"):
        ipsec_doc["vti_interface"] = str(allocation_plan["vti_interface"])
        ipsec_doc["mark"] = f"{allocation_plan['fwmark']}/0xffffffff"

    transport_doc = {
        "mark": str(allocation_plan["fwmark"]),
        "table": int(allocation_plan["route_table"]),
        "tunnel_key": int(allocation_plan["tunnel_key"]),
        "interface": str(allocation_plan["transport_interface"]),
        "tunnel_type": "gre",
        "tunnel_ttl": 64,
        "rpdb_priority": int(allocation_plan["rpdb_priority"]),
        "overlay": {
            "mux_ip": str(allocation_plan["overlay"]["mux_ip"]),
            "router_ip": str(allocation_plan["overlay"]["router_ip"]),
        },
    }

    rendered_customer = {
        "id": int(allocation_plan["customer_id"]),
        "name": str(customer_doc["name"]),
        "customer_class": str(customer_doc["customer_class"]),
        "peer": copy.deepcopy(customer_doc.get("peer") or {}),
        "transport": transport_doc,
        "selectors": copy.deepcopy(customer_doc.get("selectors") or {}),
        "backend": backend_doc,
    }

    for optional_key in ("protocols", "natd_rewrite", "dynamic_provisioning", "post_ipsec_nat"):
        optional_doc = customer_doc.get(optional_key)
        if isinstance(optional_doc, dict) and optional_doc:
            rendered_customer[optional_key] = copy.deepcopy(optional_doc)

    if ipsec_doc:
        rendered_customer["ipsec"] = ipsec_doc

    return {
        "schema_version": int(request_doc.get("schema_version") or 1),
        "customer": rendered_customer,
    }


def build_allocation_records(
    request_doc: Dict[str, Any],
    allocation_plan: Dict[str, Any],
    *,
    source_ref: str,
) -> List[Dict[str, Any]]:
    customer_doc = request_doc.get("customer") or {}
    customer_name = str(customer_doc.get("name") or "")
    customer_class = str(customer_doc.get("customer_class") or "")
    customer_id = int(allocation_plan["customer_id"])

    records: List[Dict[str, Any]] = []

    def _record(
        resource_type: str,
        resource_value: str,
        *,
        exclusive: bool,
        pool_name: str,
    ) -> None:
        records.append(
            {
                "schema_version": 1,
                "resource_type": resource_type,
                "resource_value": resource_value,
                "exclusive": exclusive,
                "pool_name": pool_name,
                "customer_name": customer_name,
                "customer_id": customer_id,
                "customer_class": customer_class,
                "source_ref": source_ref,
            }
        )

    _record("customer_id", str(allocation_plan["customer_id"]), exclusive=True, pool_name=f"customer_id.{allocation_plan['pool_class']}")
    _record("fwmark", str(allocation_plan["fwmark"]), exclusive=True, pool_name=f"fwmark.{allocation_plan['pool_class']}")
    _record("route_table", str(allocation_plan["route_table"]), exclusive=True, pool_name=f"route_table.{allocation_plan['pool_class']}")
    _record("rpdb_priority", str(allocation_plan["rpdb_priority"]), exclusive=True, pool_name=f"rpdb_priority.{allocation_plan['pool_class']}")
    _record("tunnel_key", str(allocation_plan["tunnel_key"]), exclusive=True, pool_name=f"tunnel_key.{allocation_plan['pool_class']}")
    _record("overlay_block", str(allocation_plan["overlay_block"]), exclusive=True, pool_name=f"overlay_block.{allocation_plan['pool_class']}")
    _record("transport_interface", str(allocation_plan["transport_interface"]), exclusive=True, pool_name=f"transport_interface.{allocation_plan['pool_class']}")

    if allocation_plan.get("vti_interface"):
        _record("vti_interface", str(allocation_plan["vti_interface"]), exclusive=True, pool_name=f"vti_interface.{allocation_plan['pool_class']}")

    if allocation_plan.get("backend_assignment"):
        _record(
            "backend_assignment",
            str(allocation_plan["backend_assignment"]),
            exclusive=False,
            pool_name=f"backend_assignment.{allocation_plan['pool_class']}",
        )

    if allocation_plan.get("backend_role"):
        _record(
            "backend_role",
            str(allocation_plan["backend_role"]),
            exclusive=False,
            pool_name=f"backend_role.{allocation_plan['pool_class']}",
        )

    return records


def build_allocation_summary(
    request_doc: Dict[str, Any],
    allocation_plan: Dict[str, Any],
    *,
    source_ref: str,
) -> Dict[str, Any]:
    records = build_allocation_records(request_doc, allocation_plan, source_ref=source_ref)
    return {
        "schema_version": 1,
        "customer_name": str((request_doc.get("customer") or {}).get("name") or ""),
        "customer_class": str((request_doc.get("customer") or {}).get("customer_class") or ""),
        "pool_class": str(allocation_plan["pool_class"]),
        "slot_index": int(allocation_plan["slot_index"]),
        "source_ref": source_ref,
        "exclusive_resources": [record for record in records if record["exclusive"]],
        "shared_tracking": [record for record in records if not record["exclusive"]],
        "overlay": copy.deepcopy(allocation_plan["overlay"]),
    }
