# Tailscale SSL Certificate Setup

When using Tailscale, your Pi and Server are on a private mesh network (100.x.x.x). Here's how to handle SSL certificates.

## Option 1: Disable SSL Verification (Development Only)

Edit `config.json`:
```json
{
  "ssl": {
    "verify": false,
    "cert_path": null
  }
}
```

**Pros:** Simple, works immediately
**Cons:** Vulnerable to MITM attacks (only use in trusted networks)

---

## Option 2: Use Tailscale's Built-in HTTPS (Recommended)

Tailscale provides automatic HTTPS certificates for your nodes.

### On the Server (Linux/Mac)

```bash
# Enable HTTPS in Tailscale
sudo tailscale up --accept-dns

# Get certificate
tailscale cert <your-server-tailscale-ip>

# This creates:
# - <ip>.crt (certificate)
# - <ip>.key (private key)
```

### On the Pi

```bash
# Copy the certificate from server to Pi
scp user@server:/home/user/.config/tailscale/*.crt /home/pi/cabinet/ssl/

# Or generate your own for the Pi's Tailscale IP
tailscale cert <your-pi-tailscale-ip>
```

### Update config.json

```json
{
  "server_url": "https://<server-tailscale-ip>:3000",
  "ssl": {
    "verify": true,
    "cert_path": "/home/pi/.config/tailscale/<server-ip>.crt"
  }
}
```

---

## Option 3: Use HTTP Instead of HTTPS

If both devices are on the private Tailscale network:

```json
{
  "server_url": "http://<server-tailscale-ip>:3000"
}
```

**Note:** Make sure your server allows HTTP connections.

---

## Option 4: Self-Signed Certificate

Generate a self-signed certificate on the server:

```bash
# On server
cd /path/to/server
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes
```

Copy `cert.pem` to the Pi, then:

```json
{
  "ssl": {
    "verify": true,
    "cert_path": "/home/pi/cabinet/ssl/server-cert.pem"
  }
}
```

---

## Testing SSL Connection

```bash
# From the Pi
curl -v --cacert /path/to/cert.pem https://<server-ip>:3000/api/health

# Or skip verification (test only)
curl -vk https://<server-ip>:3000/api/health
```

## Troubleshooting

**Error: "SSL: CERTIFICATE_VERIFY_FAILED"**
- Certificate is missing or incorrect
- Try Option 1 (disable verify) temporarily

**Error: "Connection refused"**
- Server isn't running or not listening on the IP
- Check firewall: `sudo ufw allow 3000`

**Tailscale IP not working**
- Check both devices are connected: `tailscale status`
- Ensure MagicDNS is enabled in Tailscale admin panel
