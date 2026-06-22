<#
.SYNOPSIS
  Build the arxmcp-server image and make it visible to k3s (Rancher Desktop) on
  Windows, without an external registry. (k3s-rancher-deploy-m1)

.DESCRIPTION
  k3s pulls from its OWN containerd (namespace "k8s.io"). In Rancher Desktop's
  containerd mode, nerdctl.exe is on the Windows PATH and can build straight
  into k8s.io. In dockerd (moby) mode there is no nerdctl, so we build with
  docker and tell the operator the one-line WSL import to run (the bash loader
  handles the cross-runtime import). The Deployment uses imagePullPolicy:Never,
  so the image MUST exist in k8s.io before `kubectl apply`.

.PARAMETER Image
  Image ref to build. Default: arxmcp-server:dev (NEVER :latest — CLAUDE.md §4.7).
#>
[CmdletBinding()]
param(
  [string]$Image = "arxmcp-server:dev"
)
$ErrorActionPreference = "Stop"

if ($Image -like "*:latest" -or $Image -notmatch ":") {
  throw "Refusing image '$Image': pin a non-:latest tag (name:tag)."
}

# Resolve repo root from this script's location (infra/k8s/scripts/ -> repo root).
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Dockerfile = Join-Path $RepoRoot "docker\Dockerfile.server"
if (-not (Test-Path $Dockerfile)) { throw "Dockerfile not found at $Dockerfile" }

Write-Host ">> arXMCP image loader (Windows) — image=$Image  repo=$RepoRoot"

$nerdctl = Get-Command nerdctl -ErrorAction SilentlyContinue
$docker  = Get-Command docker  -ErrorAction SilentlyContinue

if ($nerdctl) {
  # Containerd mode — build directly into the k8s.io namespace.
  Write-Host ">> nerdctl found -> building into containerd namespace k8s.io"
  & nerdctl --namespace k8s.io build -t $Image -f $Dockerfile $RepoRoot
  if ($LASTEXITCODE -ne 0) { throw "nerdctl build failed (exit $LASTEXITCODE)" }
  Write-Host ">> verifying image in k8s.io:"
  & nerdctl --namespace k8s.io images
}
elseif ($docker) {
  # Moby mode — build with docker, then hand off to the WSL bash loader, which
  # imports into k3s' containerd. (k3s containerd lives in the WSL2 VM.)
  Write-Host ">> docker found (moby mode) -> building image"
  & docker build -t $Image -f $Dockerfile $RepoRoot
  if ($LASTEXITCODE -ne 0) { throw "docker build failed (exit $LASTEXITCODE)" }
  Write-Host ""
  Write-Host "Image built in the Docker daemon, but k3s uses its OWN containerd."
  Write-Host "Import it into k3s (k8s.io namespace) from the Rancher Desktop shell:"
  Write-Host "    docker save $Image | nerdctl --namespace k8s.io load"
  Write-Host "  or run the bash loader inside WSL:"
  Write-Host "    wsl bash infra/k8s/scripts/load-image.sh"
}
else {
  throw "Neither nerdctl nor docker on PATH. Start Rancher Desktop (containerd mode gives nerdctl.exe)."
}

Write-Host ">> done. Next: kubectl apply -f infra/k8s/  (see docs/ops/k3s-rancher-desktop.md)"
