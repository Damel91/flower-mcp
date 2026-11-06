# Flower MCP 0.12.0

Flower can now retain the owner's LAN dashboard settings across restarts and
publish HTTPS links for a workstation service index.

- Enable **Accesso dalla LAN** in **Impostazioni Flower**, save the HTTPS port
  and restart the same profile. The HTTPS dashboard listens on all IPv4
  interfaces when enabled. The saved settings and current listener are shown
  separately. [LAN access guide](REMOTE-DASHBOARD.md)
- Flower discovers the workstation's IPv4 addresses and hostname for its
  generated HTTPS certificate. Use the hostname link if clients can resolve
  it, or use a printed IP link. Flower refreshes the certificate as addresses
  change and retains the profile CA. [Certificates and login](REMOTE-DASHBOARD.md#trust-the-https-certificate)
- LAN access requires an explicit opt-in. The local OS account still signs in
  on a fresh dashboard page, and MCP uses its separate loopback endpoint.
  [Owner sign-in guide](OWNER-LOGIN.md)
- The stopped installer backs up SQLite and the profile YAML before replacing
  the package. Existing schema 55 profiles can upgrade in place.
  [Upgrade guide](UPGRADING.md#preparing-a-0120-upgrade)
