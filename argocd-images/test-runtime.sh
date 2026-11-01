#!/usr/bin/env bash
set -euo pipefail
argo=${1:?Argo image digest required}
ksops=${2:?KSOPS image digest required}
[[ "$argo" == *@sha256:* && "$ksops" == *@sha256:* ]]
umask 077
fixture_root=$(mktemp -d)
trap 'rm -rf "$fixture_root"' EXIT
mkdir "$fixture_root/fixture" "$fixture_root/tools"
chmod 755 "$fixture_root/fixture"
chmod 777 "$fixture_root/tools"
age-keygen -o "$fixture_root/fixture/keys.txt" 2>/dev/null
recipient=$(age-keygen -y "$fixture_root/fixture/keys.txt")
curl -fsSL --retry 3 https://github.com/getsops/sops/releases/download/v3.12.2/sops-v3.12.2.linux.amd64 -o "$fixture_root/sops"
printf '%s  %s\n' '14e2e1ba3bef31e74b70cf0b674f6443c80f6c5f3df15d05ffc57c34851b4998' "$fixture_root/sops" | sha256sum --check
chmod 700 "$fixture_root/sops"
printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: synthetic-only\nstringData:\n  probe: synthetic-only\n' > "$fixture_root/plain.yaml"
(cd "$fixture_root" && ./sops --encrypt --age "$recipient" --encrypted-regex '^(data|stringData)$' plain.yaml) > "$fixture_root/fixture/secret.enc.yaml"
printf 'generators:\n- generator.yaml\n' > "$fixture_root/fixture/kustomization.yaml"
printf 'apiVersion: viaduct.ai/v1\nkind: ksops\nmetadata:\n  name: fixture\nfiles:\n- secret.enc.yaml\n' > "$fixture_root/fixture/generator.yaml"
mkdir -p "$fixture_root/fixture/chart/templates"
printf 'apiVersion: v2\nname: rendering-probe\nversion: 0.1.0\n' > "$fixture_root/fixture/chart/Chart.yaml"
printf 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}\ndata:\n  probe: synthetic-helm\n' > "$fixture_root/fixture/chart/templates/probe.yaml"
chmod 444 "$fixture_root/fixture/"*
chmod 755 "$fixture_root/fixture/chart" "$fixture_root/fixture/chart/templates"
chmod 444 "$fixture_root/fixture/chart/Chart.yaml" "$fixture_root/fixture/chart/templates/probe.yaml"
docker run --rm --network none --read-only --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges --memory 128m \
  -v "$fixture_root/tools:/custom-tools" --entrypoint /usr/local/bin/ksops "$ksops" install /custom-tools
docker run --rm --network none --read-only --user 999:999 --cap-drop ALL --security-opt no-new-privileges --memory 512m \
  --tmpfs /tmp:rw,mode=1777,size=128m \
  -v "$fixture_root/fixture:/fixture:ro" \
  -v "$fixture_root/tools/ksops:/home/argocd/.config/kustomize/plugin/viaduct.ai/v1/ksops/ksops:ro" \
  -e SOPS_AGE_KEY_FILE=/fixture/keys.txt \
  -e KUSTOMIZE_PLUGIN_HOME=/home/argocd/.config/kustomize/plugin \
  --entrypoint /bin/sh "$argo" -ec '
    test "$(id -u)" = 999
    test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token
    test ! -e /usr/bin/pebble
    kustomize build /fixture --enable-alpha-plugins --enable-exec > /tmp/rendered.yaml
    grep -q "probe: synthetic-only" /tmp/rendered.yaml
    if SOPS_AGE_KEY_FILE=/dev/null kustomize build /fixture --enable-alpha-plugins --enable-exec >/dev/null 2>&1; then exit 1; fi
    argocd version --client
    # Argo prefixes v and adds commit metadata itself. Its REST gateway rejects
    # invalid embedded SemVer even when version --client exits successfully.
    argocd version --client --short | grep -E "^argocd: v[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?(\\+[0-9A-Za-z.-]+)?$"
    helm version --short
    helm template probe /fixture/chart > /tmp/helm.yaml
    grep -q "probe: synthetic-helm" /tmp/helm.yaml
    kustomize version
    git-lfs version
    echo "PASS synthetic decryption, missing-key rejection and hardened runtime"
  '
