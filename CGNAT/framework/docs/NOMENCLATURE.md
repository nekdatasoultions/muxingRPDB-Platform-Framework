# CGNAT Nomenclature

## Purpose

This document fixes the role names used throughout the CGNAT project so we do
not mix platform-side, ISP-side, customer-side, and backend VPN roles.

## Role Definitions

### CGNAT HEAD END

The platform-side component we are designing and building code for.

Responsibilities:

- accept the outer tunnel from the CGNAT ISP HEAD END
- authenticate the outer tunnel with certificates
- establish the trusted access path into the platform
- steer inner customer S2S VPN traffic across GRE to backend VPN head ends

### CGNAT ISP HEAD END

The ISP-side or customer/carrier-side component.

Responsibilities:

- establish the outer certificate-authenticated tunnel to the CGNAT HEAD END
- sit between customer devices and the CGNAT HEAD END
- carry customer inner S2S VPN traffic through the outer tunnel

### Customer Devices

Devices behind the CGNAT ISP HEAD END.

Responsibilities:

- initiate the inner S2S VPN
- do not use certificates for the inner VPN
- use keys and known inside identity

### Backend VPN Head Ends

The existing RPDB NAT-T and non-NAT backend VPN head ends.

Responsibilities:

- receive inner VPN traffic from the CGNAT HEAD END across GRE
- present the public loopback identity
- terminate the inner VPN
- optionally NAT traffic from customer-original inside space to
  platform-assigned inside space
- provide correct routing and return-path behavior

## Tunnel Definitions

### Outer Tunnel

- runs between the CGNAT ISP HEAD END and the CGNAT HEAD END
- certificate-authenticated
- must support unknown, changing, or CGNATed public source IP

### Inner VPN

- initiated by customer devices behind the CGNAT ISP HEAD END
- carried inside the outer tunnel
- does not use certificates
- is steered to backend VPN head ends for termination

## Addressing Definitions

### Customer-Original Inside Space

The inside addressing the customer starts with before any platform translation.

### Platform-Assigned Inside Space

The inside addressing assigned by the platform and used after translation where
required.

### Public Loopback

The public identity presented by backend VPN head ends for customer-facing VPN
termination.

## Canonical Packet Flow

```text
Customer Device
  ->
CGNAT ISP HEAD END
  ->
Outer certificate-authenticated tunnel
  ->
CGNAT HEAD END
  ->
GRE steering
  ->
selected backend NAT-T or non-NAT VPN head end
  ->
public loopback identity
  ->
inner S2S VPN termination
  ->
optional NAT from customer-original inside space
     to platform-assigned inside space
```
