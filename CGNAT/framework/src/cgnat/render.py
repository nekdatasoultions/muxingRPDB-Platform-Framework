from __future__ import annotations

from typing import Any


def _category_entry(path: str, value: Any, owner: str, rationale: str) -> dict[str, Any]:
    return {
        "path": path,
        "value": value,
        "owner": owner,
        "rationale": rationale,
    }


def _backend_pool(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    preferred_class = bundle["sot"]["backend_selection"]["preferred_class"]
    return list(bundle["operations"]["backend_vpn_head_ends"].get(preferred_class) or [])


def _selected_backend_entry(bundle: dict[str, Any]) -> dict[str, Any]:
    preferred_class = bundle["sot"]["backend_selection"]["preferred_class"]
    loopback = bundle["sot"]["backend_selection"]["termination_public_loopback"]
    for entry in _backend_pool(bundle):
        if isinstance(entry, dict) and entry.get("public_loopback") == loopback:
            return entry
    return {
        "name": f"unmatched-{preferred_class}-backend",
        "gre_remote": "",
        "public_loopback": loopback,
    }


def render_deployment_summary(bundle: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    preferred_class = bundle["sot"]["backend_selection"]["preferred_class"]
    loopback = bundle["sot"]["backend_selection"]["termination_public_loopback"]
    customer_facing_public_ip = bundle["sot"]["backend_selection"]["customer_facing_public_ip"]
    devices = bundle["sot"]["customer_devices"]
    operations = bundle["operations"]

    return {
        "service_id": bundle["sot"]["service_id"],
        "customer_id": bundle["sot"]["customer_id"],
        "environment_name": bundle["operations"]["environment_name"],
        "deployment_ready": validation["ok"],
        "outer_tunnel": {
            "auth_method": bundle["framework"]["topology"]["outer_tunnel"]["auth_method"],
            "peer_ip_mode": bundle["framework"]["topology"]["outer_tunnel"]["peer_ip_mode"],
        },
        "inner_vpn": {
            "auth_method": bundle["framework"]["topology"]["inner_vpn"]["auth_method"],
            "termination_model": bundle["framework"]["topology"]["inner_vpn"]["termination_model"],
            "customer_device_count": len(devices),
            "customer_facing_public_ip": customer_facing_public_ip,
            "customer_loopback_ip": bundle["sot"]["identities"]["customer_loopback_ip"],
        },
        "placement": {
            "cgnat_head_end_subnet": bundle["operations"]["cgnat_head_end"]["subnet_id"],
            "cgnat_isp_head_end_transit_subnet": bundle["operations"]["cgnat_isp_head_end"]["transit_subnet_id"],
            "cgnat_isp_head_end_customer_subnet": bundle["operations"]["cgnat_isp_head_end"]["customer_subnet_id"],
        },
        "backend_selection": {
            "preferred_class": preferred_class,
            "termination_public_loopback": loopback,
        },
        "gre_inventory": {
            "inventory_ref": operations["gre_inventory"]["inventory_ref"],
            "assignment_mode": operations["gre_inventory"]["assignment_mode"],
        },
        "translation": {
            "mode": bundle["sot"]["addressing"]["translation_mode"],
            "customer_original_inside_space": bundle["sot"]["addressing"]["customer_original_inside_space"],
            "platform_assigned_inside_space": bundle["sot"]["addressing"]["platform_assigned_inside_space"],
        },
        "go_no_go_ready": validation["ok"],
    }


def render_infra_deployables(bundle: dict[str, Any]) -> dict[str, Any]:
    operations = bundle["operations"]
    return {
        "environment_name": operations["environment_name"],
        "aws": operations["aws"],
        "deployables": {
            "cgnat_head_end": operations["cgnat_head_end"],
            "cgnat_isp_head_end": operations["cgnat_isp_head_end"],
        },
        "external_dependencies": {
            "backend_vpn_head_ends": operations["backend_vpn_head_ends"],
            "gre_inventory": operations["gre_inventory"],
            "certificate_references": operations["certificates"],
        },
    }


def render_server_side_shapes(bundle: dict[str, Any]) -> dict[str, Any]:
    framework = bundle["framework"]
    operations = bundle["operations"]
    sot = bundle["sot"]
    return {
        "outer_tunnel": {
            "auth_method": framework["topology"]["outer_tunnel"]["auth_method"],
            "peer_ip_mode": framework["topology"]["outer_tunnel"]["peer_ip_mode"],
            "identity_ref": sot["identities"]["outer_tunnel_identity_ref"],
            "cgnat_head_end_interface": operations["cgnat_head_end"]["outer_tunnel_interface"],
            "cgnat_isp_head_end_interface": operations["cgnat_isp_head_end"]["outer_tunnel_source_interface"],
        },
        "inner_vpn": {
            "auth_method": framework["topology"]["inner_vpn"]["auth_method"],
            "termination_model": framework["topology"]["inner_vpn"]["termination_model"],
            "customer_facing_public_ip": sot["backend_selection"]["customer_facing_public_ip"],
            "inner_customer_identity": sot["identities"]["inner_customer_identity"],
            "customer_loopback_ip": sot["identities"]["customer_loopback_ip"],
            "customer_devices": sot["customer_devices"],
        },
        "steering": {
            "transport": framework["topology"]["handoff"]["transport"],
            "gre_inventory_ref": operations["gre_inventory"]["inventory_ref"],
            "gre_assignment_mode": operations["gre_inventory"]["assignment_mode"],
            "preferred_backend_class": sot["backend_selection"]["preferred_class"],
            "termination_public_loopback": sot["backend_selection"]["termination_public_loopback"],
        },
        "translation": {
            "mode": sot["addressing"]["translation_mode"],
            "boundary": framework["topology"]["translation"]["boundary"],
            "customer_original_inside_space": sot["addressing"]["customer_original_inside_space"],
            "platform_assigned_inside_space": sot["addressing"]["platform_assigned_inside_space"],
        },
    }


def render_backend_contract(bundle: dict[str, Any]) -> dict[str, Any]:
    framework = bundle["framework"]
    operations = bundle["operations"]
    sot = bundle["sot"]
    selected_backend = _selected_backend_entry(bundle)

    return {
        "record_type": "cgnat_backend_contract",
        "service_id": sot["service_id"],
        "customer_id": sot["customer_id"],
        "customer_facing_target": {
            "target_public_ip": sot["backend_selection"]["customer_facing_public_ip"],
            "description": "Customer Device keeps targeting the existing public IP used by the muxer-backed service.",
        },
        "cgnat_path": {
            "outer_tunnel": {
                "auth_method": framework["topology"]["outer_tunnel"]["auth_method"],
                "peer_ip_mode": framework["topology"]["outer_tunnel"]["peer_ip_mode"],
                "cgnat_isp_head_end_identity_ref": sot["identities"]["outer_tunnel_identity_ref"],
            },
            "inner_vpn": {
                "auth_method": framework["topology"]["inner_vpn"]["auth_method"],
                "inner_customer_identity": sot["identities"]["inner_customer_identity"],
                "customer_loopback_ip": sot["identities"]["customer_loopback_ip"],
            },
        },
        "gre_handoff": {
            "transport": framework["topology"]["handoff"]["transport"],
            "inventory_ref": operations["gre_inventory"]["inventory_ref"],
            "assignment_mode": operations["gre_inventory"]["assignment_mode"],
            "cgnat_head_end_source_interface": operations["cgnat_head_end"]["gre_source_interface"],
            "selected_backend_name": selected_backend["name"],
            "selected_backend_gre_remote": selected_backend["gre_remote"],
        },
        "backend_termination": {
            "preferred_class": sot["backend_selection"]["preferred_class"],
            "termination_public_loopback": sot["backend_selection"]["termination_public_loopback"],
            "selected_backend_public_loopback": selected_backend["public_loopback"],
        },
        "translation": {
            "mode": sot["addressing"]["translation_mode"],
            "boundary": framework["topology"]["translation"]["boundary"],
            "customer_original_inside_space": sot["addressing"]["customer_original_inside_space"],
            "platform_assigned_inside_space": sot["addressing"]["platform_assigned_inside_space"],
        },
        "path_statement": {
            "summary": "Customer keeps the same public IP target; CGNAT changes the packet path through the CGNAT ISP HEAD END, the CGNAT HEAD END, and GRE to the selected backend head end.",
        },
    }


def render_sot_record_shape(bundle: dict[str, Any]) -> dict[str, Any]:
    sot = bundle["sot"]
    return {
        "record_type": "cgnat_service",
        "version": 1,
        "service_id": sot["service_id"],
        "customer_id": sot["customer_id"],
        "identities": {
            "outer_tunnel_identity_ref": sot["identities"]["outer_tunnel_identity_ref"],
            "inner_customer_identity": sot["identities"]["inner_customer_identity"],
            "customer_loopback_ip": sot["identities"]["customer_loopback_ip"],
        },
        "addressing": {
            "customer_original_inside_space": sot["addressing"]["customer_original_inside_space"],
            "platform_assigned_inside_space": sot["addressing"]["platform_assigned_inside_space"],
            "translation_mode": sot["addressing"]["translation_mode"],
        },
        "backend_selection": {
            "preferred_class": sot["backend_selection"]["preferred_class"],
            "customer_facing_public_ip": sot["backend_selection"]["customer_facing_public_ip"],
            "termination_public_loopback": sot["backend_selection"]["termination_public_loopback"],
        },
        "customer_devices": sot["customer_devices"],
    }


def render_field_categories(bundle: dict[str, Any]) -> dict[str, Any]:
    framework = bundle["framework"]
    operations = bundle["operations"]
    sot = bundle["sot"]

    return {
        "framework_control_fields": [
            _category_entry("framework.version", framework["version"], "framework", "Controls framework contract versioning."),
            _category_entry("framework.topology.outer_tunnel.auth_method", framework["topology"]["outer_tunnel"]["auth_method"], "framework", "Defines reusable outer-tunnel behavior."),
            _category_entry("framework.topology.outer_tunnel.peer_ip_mode", framework["topology"]["outer_tunnel"]["peer_ip_mode"], "framework", "Defines how the framework treats source IP expectations."),
            _category_entry("framework.topology.inner_vpn.auth_method", framework["topology"]["inner_vpn"]["auth_method"], "framework", "Defines reusable inner VPN behavior."),
            _category_entry("framework.topology.inner_vpn.termination_model", framework["topology"]["inner_vpn"]["termination_model"], "framework", "Defines the reusable termination boundary."),
            _category_entry("framework.topology.handoff.transport", framework["topology"]["handoff"]["transport"], "framework", "Defines the reusable steering transport."),
            _category_entry("framework.topology.translation.default_mode", framework["topology"]["translation"]["default_mode"], "framework", "Defines the framework translation default."),
            _category_entry("framework.topology.translation.boundary", framework["topology"]["translation"]["boundary"], "framework", "Defines where translation belongs in the design."),
        ],
        "infra_deployable_fields": [
            _category_entry("operations.environment_name", operations["environment_name"], "operations", "Names the deployment environment."),
            _category_entry("operations.aws.region", operations["aws"]["region"], "operations", "AWS region for infra deployment."),
            _category_entry("operations.aws.vpc_id", operations["aws"]["vpc_id"], "operations", "VPC selection for infra deployment."),
            _category_entry("operations.cgnat_head_end.instance_name", operations["cgnat_head_end"]["instance_name"], "operations", "Instance identity for the CGNAT HEAD END resource."),
            _category_entry("operations.cgnat_head_end.instance_type", operations["cgnat_head_end"]["instance_type"], "operations", "Instance type for the CGNAT HEAD END resource."),
            _category_entry("operations.cgnat_head_end.subnet_id", operations["cgnat_head_end"]["subnet_id"], "operations", "Subnet placement for the CGNAT HEAD END resource."),
            _category_entry("operations.cgnat_head_end.public_eip_allocation_id", operations["cgnat_head_end"]["public_eip_allocation_id"], "operations", "Public EIP allocation for the CGNAT HEAD END resource."),
            _category_entry("operations.cgnat_isp_head_end.instance_name", operations["cgnat_isp_head_end"]["instance_name"], "operations", "Instance identity for the CGNAT ISP HEAD END resource."),
            _category_entry("operations.cgnat_isp_head_end.instance_type", operations["cgnat_isp_head_end"]["instance_type"], "operations", "Instance type for the CGNAT ISP HEAD END resource."),
            _category_entry("operations.cgnat_isp_head_end.transit_subnet_id", operations["cgnat_isp_head_end"]["transit_subnet_id"], "operations", "Transit-side subnet placement for the CGNAT ISP HEAD END resource."),
            _category_entry("operations.cgnat_isp_head_end.customer_subnet_id", operations["cgnat_isp_head_end"]["customer_subnet_id"], "operations", "Customer-side subnet placement for the CGNAT ISP HEAD END resource."),
            _category_entry("operations.gre_inventory.assignment_mode", operations["gre_inventory"]["assignment_mode"], "operations", "Operations-owned GRE endpoint allocation policy."),
        ],
        "server_side_renderable_fields": [
            _category_entry("operations.cgnat_head_end.outer_tunnel_interface", operations["cgnat_head_end"]["outer_tunnel_interface"], "operations", "Host-side interface used by the outer tunnel on the CGNAT HEAD END."),
            _category_entry("operations.cgnat_head_end.gre_source_interface", operations["cgnat_head_end"]["gre_source_interface"], "operations", "Host-side interface used by GRE on the CGNAT HEAD END."),
            _category_entry("operations.cgnat_isp_head_end.outer_tunnel_source_interface", operations["cgnat_isp_head_end"]["outer_tunnel_source_interface"], "operations", "Host-side interface used by the outer tunnel on the CGNAT ISP HEAD END."),
            _category_entry("operations.cgnat_isp_head_end.customer_facing_interface", operations["cgnat_isp_head_end"]["customer_facing_interface"], "operations", "Customer-facing host interface on the CGNAT ISP HEAD END."),
            _category_entry("sot.identities.outer_tunnel_identity_ref", sot["identities"]["outer_tunnel_identity_ref"], "sot", "Outer-tunnel identity rendered into server-side tunnel shape."),
            _category_entry("sot.identities.inner_customer_identity", sot["identities"]["inner_customer_identity"], "sot", "Inner customer service identity rendered into server-side VPN shape."),
            _category_entry("sot.identities.customer_loopback_ip", sot["identities"]["customer_loopback_ip"], "sot", "Customer loopback identity rendered into the inner VPN shape."),
            _category_entry("sot.addressing.translation_mode", sot["addressing"]["translation_mode"], "sot", "Translation behavior rendered onto the service side."),
            _category_entry("sot.addressing.customer_original_inside_space", sot["addressing"]["customer_original_inside_space"], "sot", "Customer-original addressing rendered into server-side translation logic."),
            _category_entry("sot.addressing.platform_assigned_inside_space", sot["addressing"]["platform_assigned_inside_space"], "sot", "Platform-assigned addressing rendered into server-side translation logic."),
            _category_entry("sot.backend_selection.preferred_class", sot["backend_selection"]["preferred_class"], "sot", "Backend steering class rendered into the service path."),
            _category_entry("sot.backend_selection.customer_facing_public_ip", sot["backend_selection"]["customer_facing_public_ip"], "sot", "Customer-facing public IP rendered into the inner VPN target shape."),
            _category_entry("sot.backend_selection.termination_public_loopback", sot["backend_selection"]["termination_public_loopback"], "sot", "Backend public loopback rendered into termination behavior."),
        ],
        "external_dependency_fields": [
            _category_entry("operations.backend_vpn_head_ends", operations["backend_vpn_head_ends"], "operations", "Existing backend VPN inventory referenced by the framework but not created by it."),
            _category_entry("operations.gre_inventory.inventory_ref", operations["gre_inventory"]["inventory_ref"], "operations", "Existing shared GRE inventory referenced by the framework but not created by it."),
            _category_entry("operations.certificates.cgnat_head_end_server_cert_ref", operations["certificates"]["cgnat_head_end_server_cert_ref"], "operations", "Server certificate reference expected to exist outside this framework block."),
            _category_entry("operations.certificates.cgnat_isp_head_end_client_cert_ref", operations["certificates"]["cgnat_isp_head_end_client_cert_ref"], "operations", "Client certificate reference expected to exist outside this framework block."),
        ],
        "sot_service_intent_fields": [
            _category_entry("sot.service_id", sot["service_id"], "sot", "Service identity owned by SoT."),
            _category_entry("sot.customer_id", sot["customer_id"], "sot", "Customer identity owned by SoT."),
            _category_entry("sot.identities.outer_tunnel_identity_ref", sot["identities"]["outer_tunnel_identity_ref"], "sot", "Outer identity reference owned by SoT."),
            _category_entry("sot.identities.inner_customer_identity", sot["identities"]["inner_customer_identity"], "sot", "Inner customer identity owned by SoT."),
            _category_entry("sot.identities.customer_loopback_ip", sot["identities"]["customer_loopback_ip"], "sot", "Customer loopback identity owned by SoT."),
            _category_entry("sot.addressing.customer_original_inside_space", sot["addressing"]["customer_original_inside_space"], "sot", "Customer address intent owned by SoT."),
            _category_entry("sot.addressing.platform_assigned_inside_space", sot["addressing"]["platform_assigned_inside_space"], "sot", "Assigned address intent owned by SoT."),
            _category_entry("sot.addressing.translation_mode", sot["addressing"]["translation_mode"], "sot", "Translation intent owned by SoT."),
            _category_entry("sot.backend_selection.preferred_class", sot["backend_selection"]["preferred_class"], "sot", "Backend class selection owned by SoT."),
            _category_entry("sot.backend_selection.customer_facing_public_ip", sot["backend_selection"]["customer_facing_public_ip"], "sot", "Customer-facing public target owned by SoT."),
            _category_entry("sot.backend_selection.termination_public_loopback", sot["backend_selection"]["termination_public_loopback"], "sot", "Termination loopback intent owned by SoT."),
            _category_entry("sot.customer_devices", sot["customer_devices"], "sot", "Customer device service shape owned by SoT."),
        ],
    }


def render_go_no_go_checklist(bundle: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    ready = validation["ok"]
    questions = [
        "Do we understand the exact outer-tunnel cert-auth model?",
        "Do we understand the exact inner-VPN model?",
        "Do we know where NAT from customer-original to assigned space occurs?",
        "Are subnet placement rules fully documented?",
        "Are deployment variables defined?",
        "Do we know exactly which AWS resources must be created?",
        "Do we have a rollback approach for the test deployment?",
        "Do we understand which values come from the framework, which come from operations, and which come from SoT?",
        "Does deployment require touching files outside CGNAT/?",
        "Is the current design mature enough to justify test infrastructure?",
    ]
    items = []
    for index, question in enumerate(questions, start=1):
        if index == 9:
            status = "NO" if ready else "UNKNOWN"
        else:
            status = "YES" if ready else "UNKNOWN"
        items.append({"id": index, "question": question, "status": status})

    return {
        "service_id": bundle["sot"]["service_id"],
        "environment_name": bundle["operations"]["environment_name"],
        "gate_result": "GO" if ready else "NO_GO",
        "items": items,
        "validation_error_count": validation["error_count"],
        "validation_warning_count": validation["warning_count"],
    }


def render_topology_markdown(bundle: dict[str, Any], validation: dict[str, Any]) -> str:
    service_id = bundle["sot"]["service_id"]
    env_name = bundle["operations"]["environment_name"]
    backend_class = bundle["sot"]["backend_selection"]["preferred_class"]
    loopback = bundle["sot"]["backend_selection"]["termination_public_loopback"]
    customer_facing_public_ip = bundle["sot"]["backend_selection"]["customer_facing_public_ip"]
    customer_space = ", ".join(bundle["sot"]["addressing"]["customer_original_inside_space"])
    assigned_space = ", ".join(bundle["sot"]["addressing"]["platform_assigned_inside_space"])
    return "\n".join(
        [
            "# CGNAT Deployment Shape",
            "",
            f"- Service ID: `{service_id}`",
            f"- Environment: `{env_name}`",
            f"- Validation OK: `{validation['ok']}`",
            f"- Preferred backend class: `{backend_class}`",
            f"- Customer-facing public IP: `{customer_facing_public_ip}`",
            f"- Customer loopback IP: `{bundle['sot']['identities']['customer_loopback_ip']}`",
            f"- Termination public loopback: `{loopback}`",
            f"- GRE inventory ref: `{bundle['operations']['gre_inventory']['inventory_ref']}`",
            f"- GRE assignment mode: `{bundle['operations']['gre_inventory']['assignment_mode']}`",
            f"- Customer-original inside space: `{customer_space}`",
            f"- Platform-assigned inside space: `{assigned_space}`",
            "",
            "## Role Placement",
            "",
            f"- CGNAT HEAD END subnet: `{bundle['operations']['cgnat_head_end']['subnet_id']}`",
            f"- CGNAT ISP HEAD END transit subnet: `{bundle['operations']['cgnat_isp_head_end']['transit_subnet_id']}`",
            f"- CGNAT ISP HEAD END customer subnet: `{bundle['operations']['cgnat_isp_head_end']['customer_subnet_id']}`",
            "",
            "## Packet Flow",
            "",
            "1. Customer Device initiates the inner VPN toward the existing customer-facing public IP.",
            "2. CGNAT ISP HEAD END carries that traffic through the outer certificate-authenticated tunnel.",
            "3. CGNAT HEAD END classifies the inner VPN and steers it over GRE.",
            "4. Backend VPN head end presents the public loopback and terminates the inner VPN.",
            "5. Optional address translation maps customer-original inside space to platform-assigned inside space.",
        ]
    ) + "\n"
