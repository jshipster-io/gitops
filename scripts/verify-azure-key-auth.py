#!/usr/bin/env python3
"""Read-only Azure authentication audit. Requires owner Azure CLI login; reads no keys."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
config = json.loads((root / "azure-auth/resources.json").read_text())

def az(*args):
    return json.loads(subprocess.check_output(["az", *args, "--subscription", config["subscription"], "-o", "json"]))

for entry in config["resources"]:
    kind, name, group = entry["kind"], entry["name"], entry["group"]
    if kind == "storage":
        state = az("storage", "account", "show", "-g", group, "-n", name)
        assert state.get("allowSharedKeyAccess") is False, name + ": Shared Key is enabled or unspecified"
    elif kind == "cognitive":
        state = az("cognitiveservices", "account", "show", "-g", group, "-n", name)
        assert state["properties"].get("disableLocalAuth") is True, name + ": local auth is enabled"
    else:
        resource = f'/subscriptions/{config["subscription"]}/resourceGroups/{group}/providers/Microsoft.Communication/communicationServices/{name}'
        state = az("rest", "--method", "get", "--url", resource + "?api-version=2025-05-01")
        assert state["properties"].get("disableLocalAuth") is True, name + ": local auth is enabled"
    print("PASS", name, "identity-only authentication setting")

state = az("storage", "blob", "show", "--account-name", "tfstateaks1c9c999c", "--container-name", "tfstate", "--name", "prod-aks.terraform.tfstate", "--auth-mode", "login", "--query", "name")
assert state == "prod-aks.terraform.tfstate"
print("PASS owner Entra read of Terraform state metadata")
print("Settings do not alone prove gateway propagation; verify actual workload operations separately.")
