# Private bastion SSH

The bastion remains a ClusterIP Service in `default`. Connect through the existing
Tailscale route for `10.0.0.0/16` and split DNS for `cluster.local`:

```sshconfig
Host azure-jshipster-bastion
  HostName jshipster-bastion.default.svc.cluster.local
  HostKeyAlias debug.jshipster.io
  User root
  IdentityFile ~/.ssh/azure_jshipster_bastion_key
```

`HostKeyAlias` retains the already trusted SSH host-key identity; it does not
resolve or connect to the former public hostname. The existing SSH authentication
is unchanged. This is ordinary SSH over Tailscale routing, not Tailscale SSH.
Existing `ProxyJump azure-jshipster-bastion` configurations continue to work.

Both owner Macs were updated and authenticated over this route before removing
public port 22. Tailscale must be connected with the subnet route and split DNS
enabled. Do not disable SSH host-key checking. On a new client, verify host-key
fingerprints through authenticated Kubernetes access before accepting them.

The public ingress Service exposes only HTTP/HTTPS. It no longer publishes the
legacy `debug.jshipster.io` DNS record. Its public IP is unchanged. CI rejects
LoadBalancer/NodePort manifests that expose port 22 or the `ssh` target port.

Checks:

```sh
ssh -o BatchMode=yes azure-jshipster-bastion true
ssh -o BatchMode=yes ids-wp-server true
```

If Tailscale is temporarily unavailable, an authenticated Kubernetes user with
port-forward permission can use `kubectl --context jshipster -n default
port-forward service/jshipster-bastion 2222:22`, then connect to localhost:2222
with the same key and `HostKeyAlias debug.jshipster.io`. Do not reopen public SSH
as the default recovery procedure.

## PostgreSQL 18 maintenance tools

The digest-pinned SSH image includes PostgreSQL 18.6 `psql`, `pg_dump`,
`pg_restore`, and `pg_dumpall` on the normal SSH command path.

```sh
ssh -o BatchMode=yes azure-jshipster-bastion 'psql --version; pg_dump --version'
```

`Dockerfile.postgres18` upgrades the immutable existing bastion image so its SSH
configuration and host keys survive the database-client update. The resulting
image passed actual SSH authentication with strict host-key checking and all
four client version checks before deployment. `Dockerfile` also installs the
PostgreSQL 18 client for future base rebuilds.

Pass database credentials through protected environment/input, never command
history or logs. No database credentials are embedded in the image.
