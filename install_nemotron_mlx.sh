#!/bin/bash
# Kept for older docs/links. The shared MLX runtime installer now lives in
# install_mlx_runtime.sh; this just installs it with the Nemotron weights.
set -e
cd "$(dirname "$0")"
exec ./install_mlx_runtime.sh nemotron
