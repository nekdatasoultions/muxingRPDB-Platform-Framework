from __future__ import annotations

from dataclasses import dataclass, asdict
import ipaddress
from typing import Any


ALLOWED_PEER_IP_MODES = {"dynamic_or_unknown", "dynamic", "unknown", "cgnated"}
ALLOWED_TRANSLATION_MODES = {"no_translation", "one_to_one", "subnet_pool"}
ALLOWED_BACKEND_CLASSES = {"nat_t", "non_nat"}
ALLOWED_GRE_ASSIGNMENT_MODES = {"next_available"}


@dataclass
class ValidationMessage:
    level: str
    code: str
    message: str


def _msg(level: str, code: str, message: str) -> ValidationMessage:
    return ValidationMessage(level=level, code=code, message=message)


def _get(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for item in path:
        if not isinstance(current, dict) or item not in current:
            return None
        current = current[item]
    return current


def validate_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    messages: list[ValidationMessage] = []

    framework = bundle.get("framework")
    operations = bundle.get("operations")
    sot = bundle.get("sot")

    for name, section in (
        ("framework", framework),
        ("operations", operations),
        ("sot", sot),
    ):
        if not isinstance(section, dict):
            messages.append(_msg("error", f"missing_{name}", f"Missing top-level `{name}` section."))

    if messages:
        return _finalize(messages, bundle)

    _validate_framework(messages, framework)
    _validate_operations(messages, framework, operations)
    _validate_sot(messages, operations, sot)

    return _finalize(messages, bundle)


def _validate_framework(messages: list[ValidationMessage], framework: dict[str, Any]) -> None:
    version = framework.get("version")
    if version != 1:
        messages.append(_msg("error", "framework_version", "Framework version must be `1`."))

    outer_auth = _get(framework, "topology", "outer_tunnel", "auth_method")
    if outer_auth != "certificate":
        messages.append(_msg("error", "outer_auth", "Outer tunnel auth method must be `certificate`."))

    peer_mode = _get(framework, "topology", "outer_tunnel", "peer_ip_mode")
    if peer_mode not in ALLOWED_PEER_IP_MODES:
        messages.append(_msg("error", "peer_ip_mode", "Outer tunnel peer_ip_mode is invalid."))

    inner_auth = _get(framework, "topology", "inner_vpn", "auth_method")
    if inner_auth != "key_based":
        messages.append(_msg("error", "inner_auth", "Inner VPN auth method must be `key_based`."))

    handoff_transport = _get(framework, "topology", "handoff", "transport")
    if handoff_transport != "gre":
        messages.append(_msg("error", "handoff_transport", "Handoff transport must be `gre`."))

    translation_mode = _get(framework, "topology", "translation", "default_mode")
    if translation_mode not in ALLOWED_TRANSLATION_MODES:
        messages.append(_msg("error", "translation_mode", "Framework translation default_mode is invalid."))


def _validate_operations(
    messages: list[ValidationMessage],
    framework: dict[str, Any],
    operations: dict[str, Any],
) -> None:
    head_subnets = set(_get(framework, "placement_constraints", "cgnat_head_end", "allowed_subnets") or [])
    isp_subnets = set(_get(framework, "placement_constraints", "cgnat_isp_head_end", "allowed_subnets") or [])
    customer_subnets = set(_get(framework, "placement_constraints", "customer_devices", "allowed_subnets") or [])

    head_subnet = _get(operations, "cgnat_head_end", "subnet_id")
    if head_subnet not in head_subnets:
        messages.append(_msg("error", "head_subnet", "CGNAT HEAD END subnet is outside the allowed set."))

    isp_transit_subnet = _get(operations, "cgnat_isp_head_end", "transit_subnet_id")
    isp_customer_subnet = _get(operations, "cgnat_isp_head_end", "customer_subnet_id")
    if isp_transit_subnet not in isp_subnets:
        messages.append(_msg("error", "isp_transit_subnet", "CGNAT ISP HEAD END transit subnet is outside the allowed set."))
    if isp_customer_subnet not in isp_subnets:
        messages.append(_msg("error", "isp_customer_subnet", "CGNAT ISP HEAD END customer subnet is outside the allowed set."))
    if isp_customer_subnet not in customer_subnets:
        messages.append(_msg("error", "customer_side_subnet", "CGNAT ISP HEAD END customer subnet is not in the customer-device subnet set."))

    backends = _get(operations, "backend_vpn_head_ends") or {}
    if not any(backends.get(name) for name in ALLOWED_BACKEND_CLASSES):
        messages.append(_msg("error", "backend_inventory", "At least one backend VPN head end must be defined."))

    gre_inventory_ref = _get(operations, "gre_inventory", "inventory_ref")
    gre_assignment_mode = _get(operations, "gre_inventory", "assignment_mode")
    if not gre_inventory_ref:
        messages.append(_msg("error", "gre_inventory_ref", "GRE inventory reference is required."))
    if gre_assignment_mode not in ALLOWED_GRE_ASSIGNMENT_MODES:
        messages.append(_msg("error", "gre_assignment_mode", "GRE assignment_mode must be `next_available` for the current Scenario 1 model."))

    cert_server = _get(operations, "certificates", "cgnat_head_end_server_cert_ref")
    cert_client = _get(operations, "certificates", "cgnat_isp_head_end_client_cert_ref")
    if not cert_server or not cert_client:
        messages.append(_msg("error", "cert_refs", "Both outer-tunnel certificate references must be present."))


def _validate_sot(
    messages: list[ValidationMessage],
    operations: dict[str, Any],
    sot: dict[str, Any],
) -> None:
    service_id = sot.get("service_id")
    customer_id = sot.get("customer_id")
    if not service_id or not customer_id:
        messages.append(_msg("error", "service_identity", "SoT service_id and customer_id are required."))

    outer_identity = _get(sot, "identities", "outer_tunnel_identity_ref")
    inner_identity = _get(sot, "identities", "inner_customer_identity")
    customer_loopback_ip = _get(sot, "identities", "customer_loopback_ip")
    if not outer_identity or not inner_identity or not customer_loopback_ip:
        messages.append(_msg("error", "identity_refs", "SoT outer identity, inner identity, and customer_loopback_ip are required."))
    else:
        try:
            loopback_ip = ipaddress.ip_address(customer_loopback_ip)
        except ValueError:
            messages.append(_msg("error", "customer_loopback_ip_format", "customer_loopback_ip must be a valid IP address."))
            loopback_ip = None
        if loopback_ip is not None:
            if not str(loopback_ip).startswith("10."):
                messages.append(_msg("warning", "customer_loopback_ip_demo_range", "Scenario 1 demo loopback is expected to use non-overlapping 10.x space."))

    addressing = _get(sot, "addressing") or {}
    translation_mode = addressing.get("translation_mode")
    if translation_mode not in ALLOWED_TRANSLATION_MODES:
        messages.append(_msg("error", "sot_translation_mode", "SoT translation_mode is invalid."))
    customer_space = addressing.get("customer_original_inside_space") or []
    assigned_space = addressing.get("platform_assigned_inside_space") or []
    if not customer_space:
        messages.append(_msg("error", "customer_space", "Customer original inside space is required."))
    if translation_mode != "no_translation" and not assigned_space:
        messages.append(_msg("error", "assigned_space", "Platform-assigned inside space is required when translation is enabled."))
    if customer_loopback_ip:
        try:
            loopback_ip = ipaddress.ip_address(customer_loopback_ip)
            for cidr in assigned_space:
                if loopback_ip in ipaddress.ip_network(cidr, strict=False):
                    messages.append(_msg("error", "customer_loopback_overlap_assigned", "customer_loopback_ip must not overlap with platform-assigned inside space."))
        except ValueError:
            pass

    preferred_class = _get(sot, "backend_selection", "preferred_class")
    if preferred_class not in ALLOWED_BACKEND_CLASSES:
        messages.append(_msg("error", "preferred_class", "Preferred backend class is invalid."))

    customer_facing_public_ip = _get(sot, "backend_selection", "customer_facing_public_ip")
    if not customer_facing_public_ip:
        messages.append(_msg("error", "customer_facing_public_ip", "Customer-facing public IP is required."))

    public_loopback = _get(sot, "backend_selection", "termination_public_loopback")
    if customer_facing_public_ip and public_loopback and customer_facing_public_ip != public_loopback:
        messages.append(
            _msg(
                "error",
                "backend_public_target_mismatch",
                "For the current Scenario 1 model, customer_facing_public_ip must match termination_public_loopback.",
            )
        )
    backend_pool = (_get(operations, "backend_vpn_head_ends", preferred_class) or []) if preferred_class else []
    loopbacks = {entry.get("public_loopback") for entry in backend_pool if isinstance(entry, dict)}
    if preferred_class in ALLOWED_BACKEND_CLASSES and public_loopback not in loopbacks:
        messages.append(_msg("error", "termination_loopback", "Termination public loopback is not present in the selected backend class inventory."))

    customer_devices = sot.get("customer_devices") or []
    if not customer_devices:
        messages.append(_msg("error", "customer_devices", "At least one Customer Device must be defined in SoT."))
    else:
        allowed_customer_subnet = _get(operations, "cgnat_isp_head_end", "customer_subnet_id")
        for index, device in enumerate(customer_devices, start=1):
            if device.get("subnet_id") != allowed_customer_subnet:
                messages.append(
                    _msg(
                        "error",
                        f"customer_device_subnet_{index}",
                        f"Customer Device {index} is outside the approved customer subnet.",
                    )
                )
            if not device.get("known_inside_identity"):
                messages.append(
                    _msg(
                        "error",
                        f"customer_device_identity_{index}",
                        f"Customer Device {index} is missing known_inside_identity.",
                    )
                )


def _finalize(messages: list[ValidationMessage], bundle: dict[str, Any]) -> dict[str, Any]:
    errors = [message for message in messages if message.level == "error"]
    warnings = [message for message in messages if message.level == "warning"]
    return {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "messages": [asdict(message) for message in messages],
        "summary": {
            "service_id": _get(bundle, "sot", "service_id"),
            "environment_name": _get(bundle, "operations", "environment_name"),
            "preferred_backend_class": _get(bundle, "sot", "backend_selection", "preferred_class"),
            "translation_mode": _get(bundle, "sot", "addressing", "translation_mode"),
        },
    }
