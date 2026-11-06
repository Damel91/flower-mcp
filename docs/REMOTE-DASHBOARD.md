# Remote dashboard over HTTPS

Run Flower under the operating-system account that owns the profile. Give the
dashboard a reachable IP address on the server and a DNS name or IP address
that your browser will use.

```sh
flower-mcp serve --transport streamable-http --profile management \
  --host 127.0.0.1 --port 8015 \
  --dashboard-bind 192.0.2.10 --dashboard-name flower.example.com \
  --dashboard-port 8443
```

Replace the example IP with an address assigned to the server and the example
name with your DNS name. The dashboard port defaults to 8443. Open
`https://flower.example.com:8443/dashboard` and sign in with the local account
that owns Flower. Coding clients on the server continue using the loopback
MCP endpoint on port 8015. The two endpoints share the same profile and
maintenance state.

Flower creates a private profile CA and a server certificate for the configured
name. The startup output gives the location of the public CA certificate.
Importing that certificate on a client is optional. If your browser requires
trust before allowing a connection, verify the certificate through a trusted
channel and add the public CA to that client, or use a certificate the client
already trusts. Keep the CA key and server key private.

To use an existing certificate, pass both PEM files in the same command:

```text
--dashboard-cert /absolute/path/fullchain.pem --dashboard-key /absolute/path/server.key
```

The certificate must cover the exact dashboard DNS name or IP address. Clients
validate the HTTPS connection before sending credentials. Flower enforces the
configured HTTPS address and origin. Open the advertised address directly.

A restored browser tab, a new tab and a page reload each require a fresh login.
The browser keeps the page's proof in memory. A restored session cookie alone
cannot open the dashboard. The latest successful login on the same browser
origin replaces the previous session cookie.
