# Open the dashboard over HTTPS

## Enable access from the LAN

Run Flower under the operating-system account that owns the profile. Start it
in streamable HTTP mode using the same profile and loopback MCP address you
normally use.

```sh
flower-mcp serve --transport streamable-http --profile management \
  --host 127.0.0.1 --port 8015
```

1. Open the local `/dashboard` and sign in as the profile owner.
2. Open **Impostazioni Flower → Accesso dalla LAN**, select **Consenti l’accesso
   dalla LAN**, choose the **Porta HTTPS** and click **Salva accesso dalla LAN**.
   The default HTTPS port is 8443. Use a free port distinct from the loopback
   IPv4 MCP port.
3. Restart Flower with the same profile. The HTTPS listener binds to
   `0.0.0.0` and Flower prints the URLs for its hostname and detected IPv4
   addresses. Open one of those links from another device and sign in.

LAN access starts disabled. The dashboard shows the saved choice and the
currently running listener separately. To turn LAN access off, clear the
checkbox, save and restart. The dashboard and the loopback MCP endpoint share
the same profile and maintenance state.

For a workstation service index, use the printed hostname link such as
`https://workstation.local:8443/` if client devices can resolve that name.
On macOS, Flower uses the workstation's Bonjour name when available. A printed
IP link also works when the client can reach that address. A hostname link can
remain useful when the IP changes, provided it resolves to the workstation's
current IPv4 address.

## Trust the HTTPS certificate

Flower generates a private profile CA and a server certificate covering the
detected IPv4 addresses and hostname. It refreshes the server certificate as
those identities change. The startup output prints the public CA certificate's
path. You can verify and import that CA on each client to make its browser
recognize Flower. Keep the CA key and server key private.

Sign in with the local account that owns the profile. A restored browser tab,
a new tab and a page reload each require a fresh login. The browser keeps the
page's proof in memory, and the latest successful login on the same browser
origin replaces the previous session cookie. [Owner sign-in guide](OWNER-LOGIN.md)

## Override the saved settings at launch

You can enable automatic IPv4 HTTPS for a single start with the wildcard bind
option. Flower discovers the addresses and generates the certificate.

```sh
flower-mcp serve --transport streamable-http --profile management \
  --host 127.0.0.1 --port 8015 \
  --dashboard-bind 0.0.0.0 --dashboard-port 8443
```

For a single local-only start, pass `--dashboard-local` by itself. This is
useful if you need to change a saved HTTPS port that another process is using.
Omit the dashboard options on a later start to use the saved network settings.

To serve one specific interface and identity, pass the interface IP with
`--dashboard-bind` and the client-facing DNS name or IP with
`--dashboard-name`. Flower generates a certificate for that identity unless
you supply both PEM files.

```sh
flower-mcp serve --transport streamable-http --profile management \
  --host 127.0.0.1 --port 8015 \
  --dashboard-bind 192.0.2.10 --dashboard-name flower.example.com \
  --dashboard-port 8443 \
  --dashboard-cert /absolute/path/fullchain.pem \
  --dashboard-key /absolute/path/server.key
```

Replace the example IP and DNS name with your own. The certificate must cover
the dashboard name or IP in the browser URL. Open the HTTPS address Flower
prints, such as `https://flower.example.com:8443/dashboard`.
