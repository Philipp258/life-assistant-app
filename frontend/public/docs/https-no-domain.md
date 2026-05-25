# HTTPS without owning a domain

Life Assistant can run on plain HTTP while you are setting it up, but browser features such as push notifications and microphone access require a secure context: `https://` or `localhost`.

This guide uses **Tailscale Serve** because it gives you a stable HTTPS URL without buying or configuring a domain. The URL is available to devices in your Tailscale network, which is usually the right privacy boundary for a personal assistant.

## What you get

- A permanent HTTPS URL like `https://life-assistant.your-tailnet.ts.net`
- A valid certificate managed by Tailscale
- No domain purchase and no public inbound firewall port
- Access limited to devices signed in to your Tailscale account

## Prerequisites

- Life Assistant is already running on the server at `http://127.0.0.1:8000` or `http://<server-ip>:8000`
- You can SSH into the server
- You have a Tailscale account and can add the server to your tailnet

## 1. Install Tailscale on the server

SSH into the server, then install and start Tailscale:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Open the login URL printed by `tailscale up` and approve the server.

## 2. Enable MagicDNS and HTTPS certificates

In the Tailscale admin console:

1. Open **DNS**.
2. Enable **MagicDNS**.
3. Open **DNS → HTTPS Certificates** and enable certificates for your tailnet.

After this, the server gets a name under your tailnet, for example:

```text
life-assistant.your-tailnet.ts.net
```

You can see the exact name with:

```bash
tailscale status
```

## 3. Serve Life Assistant over HTTPS

On the server, proxy Tailscale HTTPS port 443 to Life Assistant's local HTTP port:

```bash
sudo tailscale serve --bg --https=443 localhost:8000
```

`--bg` makes the Serve configuration persistent. Tailscale resumes it after reboots and Tailscale restarts until you disable it.

Check the active Serve config:

```bash
tailscale serve status
```

## 4. Open Life Assistant from a trusted device

Install and sign in to Tailscale on your laptop or phone, then open:

```text
https://<server-name>.<tailnet-name>.ts.net/
```

Log in to Life Assistant as usual. Push notifications and microphone access should now work because the app is loaded over HTTPS.

## Troubleshooting

- **The URL does not load:** make sure the client device is connected to Tailscale and can see the server in `tailscale status`.
- **Serve cannot bind port 443:** stop any other reverse proxy using 443, or choose another HTTPS port, for example `sudo tailscale serve --bg --https=8443 localhost:8000` and open `https://<name>:8443/`.
- **Life Assistant itself is not responding locally:** check the service with `systemctl status life-assistant` and `journalctl -u life-assistant -n 100` on the server.
- **You need public internet access, not tailnet-only access:** Tailscale Funnel can expose a Serve target publicly, but that changes the security model. Only enable it if you understand who can reach the URL.

## Turning it off

```bash
sudo tailscale serve --https=443 off
```
