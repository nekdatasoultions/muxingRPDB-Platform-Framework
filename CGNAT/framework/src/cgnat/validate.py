from __future__ import annotations

from dataclasses import dataclass, asdict
import ipaddress
from typing import Any


ALLOWED_PEER_IP_MODES = {"dynamic_or_unknown", "dynamic", "unknown", "cgnated"}
ALLOWED_TRANSLATION_MODES = {"no_translation", "one_to_one", "subnet_pool"}
ALLOWED_BACKEND_CLASSES = {"nat_t", "non_nat"}
ALLOWED_GRE_ASSIGNMENT_MODES = {"next_available"}
ALLOWED_HEAD_EIP_STRATEGIES = {"existing_allocation", "allocate_new"}
ALLOWED_ISP_EIP_STRATEGIES = {"none", "existing_allocation", "allocate_new"}
ALLOWED_CUSTOMER_ROUTER_EIP_STRATEGIES = {"none"}


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


def _is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


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
    default_tags = _get(operations, "default_tags")
    if not isinstance(default_tags, dict) or not default_tags:
        messages.append(_msg("error", "default_tags", "operations.default_tags must be a non-empty object."))
    head_ami = _get(operations, "cgnat_head_end", "ami_id")
    head_sgs = _get(operations, "cgnat_head_end", "security_group_ids")
    head_profile = _get(operations, "cgnat_head_end", "iam_instance_profile")
    head_key_pair = _get(operations, "cgnat_head_end", "key_pair_name")
    head_root = _get(operations, "cgnat_head_end", "root_volume") or {}
    head_eip_strategy = _get(operations, "cgnat_head_end", "public_eip_strategy")
    head_eip_alloc = _get(operations, "cgnat_head_end", "public_eip_allocation_id")
    if not head_ami:
        messages.append(_msg("error", "head_ami", "CGNAT HEAD END ami_id is required."))
    if not isinstance(head_sgs, list) or not head_sgs:
        messages.append(_msg("error", "head_security_groups", "CGNAT HEAD END security_group_ids must be a non-empty list."))
    if not head_profile:
        messages.append(_msg("error", "head_instance_profile", "CGNAT HEAD END iam_instance_profile is required."))
    if head_key_pair is not None and not isinstance(head_key_pair, str):
        messages.append(_msg("error", "head_key_pair_name", "CGNAT HEAD END key_pair_name must be a string or null."))
    if not head_root.get("device_name") or not head_root.get("size_gb") or not head_root.get("volume_type"):
        messages.append(_msg("error", "head_root_volume", "CGNAT HEAD END root_volume must define device_name, size_gb, and volume_type."))
    if head_eip_strategy and head_eip_strategy not in ALLOWED_HEAD_EIP_STRATEGIES:
        messages.append(_msg("error", "head_public_eip_strategy", "CGNAT HEAD END public_eip_strategy is invalid."))
    effective_head_eip_strategy = head_eip_strategy or "existing_allocation"
    if effective_head_eip_strategy == "existing_allocation" and not head_eip_alloc:
        messages.append(
            _msg(
                "error",
                "head_public_eip_allocation_id",
                "CGNAT HEAD END public_eip_allocation_id is required when public_eip_strategy is `existing_allocation`.",
            )
        )

    isp_transit_subnet = _get(operations, "cgnat_isp_head_end", "transit_subnet_id")
    isp_customer_subnet = _get(operations, "cgnat_isp_head_end", "customer_subnet_id")
    if isp_transit_subnet not in isp_subnets:
        messages.append(_msg("error", "isp_transit_subnet", "CGNAT ISP HEAD END transit subnet is outside the allowed set."))
    if isp_customer_subnet not in isp_subnets:
        messages.append(_msg("error", "isp_customer_subnet", "CGNAT ISP HEAD END customer subnet is outside the allowed set."))
    if isp_customer_subnet not in customer_subnets:
        messages.append(_msg("error", "customer_side_subnet", "CGNAT ISP HEAD END customer subnet is not in the customer-device subnet set."))
    isp_ami = _get(operations, "cgnat_isp_head_end", "ami_id")
    isp_sgs = _get(operations, "cgnat_isp_head_end", "security_group_ids")
    isp_profile = _get(operations, "cgnat_isp_head_end", "iam_instance_profile")
    isp_key_pair = _get(operations, "cgnat_isp_head_end", "key_pair_name")
    isp_root = _get(operations, "cgnat_isp_head_end", "root_volume") or {}
    isp_eip_strategy = _get(operations, "cgnat_isp_head_end", "public_eip_strategy")
    isp_eip_alloc = _get(operations, "cgnat_isp_head_end", "public_eip_allocation_id")
    if not isp_ami:
        messages.append(_msg("error", "isp_ami", "CGNAT ISP HEAD END ami_id is required."))
    if not isinstance(isp_sgs, list) or not isp_sgs:
        messages.append(_msg("error", "isp_security_groups", "CGNAT ISP HEAD END security_group_ids must be a non-empty list."))
    if not isp_profile:
        messages.append(_msg("error", "isp_instance_profile", "CGNAT ISP HEAD END iam_instance_profile is required."))
    if isp_key_pair is not None and not isinstance(isp_key_pair, str):
        messages.append(_msg("error", "isp_key_pair_name", "CGNAT ISP HEAD END key_pair_name must be a string or null."))
    if not isp_root.get("device_name") or not isp_root.get("size_gb") or not isp_root.get("volume_type"):
        messages.append(_msg("error", "isp_root_volume", "CGNAT ISP HEAD END root_volume must define device_name, size_gb, and volume_type."))
    if isp_eip_strategy and isp_eip_strategy not in ALLOWED_ISP_EIP_STRATEGIES:
        messages.append(_msg("error", "isp_public_eip_strategy", "CGNAT ISP HEAD END public_eip_strategy is invalid."))
    effective_isp_eip_strategy = isp_eip_strategy or "none"
    if effective_isp_eip_strategy == "existing_allocation" and not isp_eip_alloc:
        messages.append(
            _msg(
                "error",
                "isp_public_eip_allocation_id",
                "CGNAT ISP HEAD END public_eip_allocation_id is required when public_eip_strategy is `existing_allocation`.",
            )
        )
    isp_customer_private_ip = _get(operations, "cgnat_isp_head_end", "customer_facing_private_ip")
    if not isp_customer_private_ip or not _is_valid_ip(str(isp_customer_private_ip)):
        messages.append(
            _msg(
                "error",
                "isp_customer_facing_private_ip",
                "CGNAT ISP HEAD END customer_facing_private_ip must be a valid IPv4 address.",
            )
        )

    customer_vpn_routers = list(_get(operations, "customer_vpn_routers") or [])
    if len(customer_vpn_routers) < 2:
        messages.append(
            _msg(
                "error",
                "customer_vpn_router_count",
                "Scenario 1 demo requires at least two customer_vpn_routers behind the CGNAT ISP HEAD END.",
            )
        )
    router_roles: set[str] = set()
    router_private_ips: set[str] = set()
    for index, router in enumerate(customer_vpn_routers, start=1):
        role = str(router.get("role") or "").strip()
        if not role:
            messages.append(_msg("error", f"customer_vpn_router_role_{index}", f"Customer VPN router {index} is missing `role`."))
        elif role in router_roles:
            messages.append(
                _msg(
                    "error",
                    f"customer_vpn_router_duplicate_role_{index}",
                    f"Customer VPN router role `{role}` is duplicated.",
                )
            )
        else:
            router_roles.add(role)
        subnet_id = router.get("subnet_id")
        if subnet_id not in customer_subnets:
            messages.append(
                _msg(
                    "error",
                    f"customer_vpn_router_subnet_{index}",
                    f"Customer VPN router {index} subnet is outside the approved customer-device subnet set.",
                )
            )
        private_ip = str(router.get("private_ip_address") or "").strip()
        if not private_ip or not _is_valid_ip(private_ip):
            messages.append(
                _msg(
                    "error",
                    f"customer_vpn_router_private_ip_{index}",
                    f"Customer VPN router {index} private_ip_address must be a valid IPv4 address.",
                )
            )
        elif private_ip == str(isp_customer_private_ip):
            messages.append(
                _msg(
                    "error",
                    f"customer_vpn_router_private_ip_overlap_isp_{index}",
                    f"Customer VPN router {index} private_ip_address overlaps the ISP customer-facing private IP.",
                )
            )
        elif private_ip in router_private_ips:
            messages.append(
                _msg(
                    "error",
                    f"customer_vpn_router_duplicate_private_ip_{index}",
                    f"Customer VPN router private_ip_address `{private_ip}` is duplicated.",
                )
            )
        else:
            router_private_ips.add(private_ip)
        router_checks = {
            "ami_id": router.get("ami_id"),
            "security_group_ids": router.get("security_group_ids"),
            "iam_instance_profile": router.get("iam_instance_profile"),
            "customer_facing_interface": router.get("customer_facing_interface"),
        }
        for field_name, field_value in router_checks.items():
            if not field_value:
                messages.append(
                    _msg(
                        "error",
                        f"customer_vpn_router_{field_name}_{index}",
                        f"Customer VPN router {index} is missing `{field_name}`.",
                    )
                )
        router_root = router.get("root_volume") or {}
        if not router_root.get("device_name") or not router_root.get("size_gb") or not router_root.get("volume_type"):
            messages.append(
                _msg(
                    "error",
                    f"customer_vpn_router_root_volume_{index}",
                    f"Customer VPN router {index} root_volume must define device_name, size_gb, and volume_type.",
                )
            )
        router_eip_strategy = router.get("public_eip_strategy") or "none"
        if router_eip_strategy not in ALLOWED_CUSTOMER_ROUTER_EIP_STRATEGIES:
            messages.append(
                _msg(
                    "error",
                    f"customer_vpn_router_public_eip_strategy_{index}",
                    "Customer VPN routers currently support only `public_eip_strategy = none`.",
                )
            )

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
        router_roles = {str(router.get("role") or "").strip() for router in (_get(operations, "customer_vpn_routers") or [])}
        seen_loopbacks: set[str] = set()
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
            loopback_ip = str(device.get("customer_loopback_ip") or "").strip()
            if len(customer_devices) > 1 and not loopback_ip:
                messages.append(
                    _msg(
                        "error",
                        f"customer_device_loopback_{index}",
                        f"Customer Device {index} must define customer_loopback_ip when multiple customer devices are present.",
                    )
                )
            elif loopback_ip and not _is_valid_ip(loopback_ip):
                messages.append(
                    _msg(
                        "error",
                        f"customer_device_loopback_format_{index}",
                        f"Customer Device {index} customer_loopback_ip must be a valid IPv4 address.",
                    )
                )
            elif loopback_ip:
                if not loopback_ip.startswith("10."):
                    messages.append(
                        _msg(
                            "warning",
                            f"customer_device_loopback_demo_range_{index}",
                            f"Customer Device {index} loopback is expected to use non-overlapping 10.x space for the demo.",
                        )
                    )
                if loopback_ip in seen_loopbacks:
                    messages.append(
                        _msg(
                            "error",
                            f"customer_device_duplicate_loopback_{index}",
                            f"Customer Device loopback `{loopback_ip}` is duplicated.",
                        )
                    )
                seen_loopbacks.add(loopback_ip)
            router_role = str(device.get("router_role") or "").strip()
            if not router_role:
                messages.append(
                    _msg(
                        "error",
                        f"customer_device_router_role_{index}",
                        f"Customer Device {index} must define router_role.",
                    )
                )
            elif router_role not in router_roles:
                messages.append(
                    _msg(
                        "error",
                        f"customer_device_router_role_missing_{index}",
                        f"Customer Device {index} router_role `{router_role}` is not present in operations.customer_vpn_routers.",
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
