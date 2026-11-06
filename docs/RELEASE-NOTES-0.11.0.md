# Flower MCP 0.11.0

Flower can serve its authenticated dashboard remotely over HTTPS while coding
clients on the host continue using the local MCP endpoint.

- Opt in with a bind IP and the name or IP that browsers will use. Flower
  generates and retains a profile certificate authority and issues a server
  certificate for that name. Client CA trust is optional, and you can provide
  an existing PEM certificate and key. [Remote dashboard guide](REMOTE-DASHBOARD.md)
- Browser restoration requires a fresh sign-in. Reloading or opening a new
  dashboard tab also requires sign-in. The session proof stays in page memory.
  [Owner sign-in guide](OWNER-LOGIN.md)
- Existing profiles can upgrade with the stopped installer and its SQLite
  and YAML backup. [Upgrade guide](UPGRADING.md#preparing-a-0110-upgrade)
