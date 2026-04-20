# MOM Platform Shortlist (Forkable OSS)

Date: 2026-03-09

## 1. Goal

Select open-source platforms to build a MOM that deploys, manages, and monitors Muxer + VPN-HUB infrastructure, with clear forkability and license implications.

## 2. Evaluation Criteria

1. License compatibility for internal fork/customization.
2. Operational fit for Linux networking, IPsec, routing, and per-customer overlays.
3. API maturity and automation support.
4. Community velocity and long-term maintainability.
5. Ability to run self-hosted on EC2.

## 3. Monitoring Platform Candidates

| Platform | Primary Role | License | Fit for MOM | Forkability Notes |
|---|---|---|---|---|
| Prometheus | Metrics TSDB and scraping | Apache-2.0 | Strong | Permissive; low legal friction for internal fork |
| Alertmanager | Alert routing, inhibition, silencing | Apache-2.0 | Strong | Pairs natively with Prometheus |
| Grafana | Visualization and dashboards | AGPLv3 (core OSS) | Strong technically | Copyleft obligations if redistributed as modified network service |
| OpenSearch + Dashboards | Logs/search + dashboards | Apache-2.0 | Strong | Permissive alternative to avoid AGPL dashboard layer |
| Zabbix | Full monitoring suite | AGPL-3.0 (v7+) | Good all-in-one | Higher license obligations for forked service model |
| LibreNMS | Network/SNMP monitoring | GPLv3 | Good for network views | GPL obligations if distributing derivatives |
| VictoriaMetrics | Prometheus-compatible TSDB | Apache-2.0 | Strong at scale | Good Prometheus backend option |

## 4. Management/Deployment Platform Candidates

| Platform | Primary Role | License | Fit for MOM | Forkability Notes |
|---|---|---|---|---|
| NetBox | Source of truth (tenants, prefixes, devices, tunnels metadata) | Apache-2.0 | Strong | Excellent extensibility via plugins/API |
| AWX | Automation controller for Ansible jobs | Apache-2.0 | Strong | Good for playbook-based rollout/rollback; note release cadence caveat |
| Argo CD | GitOps deployment controller (Kubernetes-focused) | Apache-2.0 | Medium (current architecture is VM-centric) | Useful later if MOM control plane moves to K8s |

## 5. Recommended MOM V1 Stack

Recommended stack for lowest legal friction + fastest delivery on your current EC2 model:

1. NetBox (source of truth).
2. AWX (orchestrated deployment and rollback).
3. Prometheus + Alertmanager (metrics + alerting).
4. OpenSearch + OpenSearch Dashboards (logs and operator dashboards).

Inference from sources: this stack maximizes Apache-2.0 components, which reduces copyleft overhead compared with AGPL/GPL-heavy alternatives while still covering deploy/manage/monitor requirements.

## 6. Optional MOM V2 Enhancements

1. Add VictoriaMetrics as Prometheus long-term/high-cardinality backend.
2. Add Grafana only if required visualization features outweigh AGPL considerations.
3. Add Argo CD if/when MOM services are containerized on Kubernetes.

Inference from sources: staying VM-first (AWX + NetBox) is the shortest path now because your Muxer/VPN-HUB control model is host-centric, not Kubernetes-native yet.

## 7. Risks and Constraints

1. AWX upstream release cadence is currently paused during refactoring, so pin tested versions and maintain internal validation pipeline.
2. AGPL/GPL tools are usable, but legal/compliance workflow must be defined before productizing a forked distribution.
3. Monitoring cardinality can grow quickly with per-customer labels; enforce label hygiene from day one.

## 8. Decision Summary

1. Use an Apache-first core stack for MOM V1.
2. Treat Grafana/Zabbix/LibreNMS as optional or bounded-scope components.
3. Keep all customer intent in NetBox + Git, and make AWX the execution layer.

## 9. Source Links

1. Prometheus GitHub: https://github.com/prometheus/prometheus
2. Grafana licensing: https://grafana.com/licensing/
3. OpenSearch FAQ/license context: https://opensearch.org/faq/
4. OpenSearch docs (Apache-2.0 statement): https://docs.opensearch.org/docs/1.2/
5. NetBox GitHub: https://github.com/netbox-community/netbox
6. NetBox docs intro/license statement: https://netbox.readthedocs.io/en/stable/development/
7. AWX GitHub README (release pause note): https://github.com/ansible/awx
8. Argo CD GitHub: https://github.com/argoproj/argo-cd
9. Zabbix GitHub: https://github.com/zabbix/zabbix
10. Zabbix Docker README (AGPLv3 from 7.0): https://github.com/zabbix/zabbix-docker
11. LibreNMS GitHub: https://github.com/librenms/librenms
12. VictoriaMetrics repositories: https://github.com/orgs/VictoriaMetrics/repositories
