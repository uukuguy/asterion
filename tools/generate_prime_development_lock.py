"""Maintainer-only generator for the immutable development preparation lock."""

from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from asterion.applications.prime_agent.operator.release_recipe import (
    PRIME_IPYTHON_SOURCE,
)

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "packages/typescript/prime-gateway"


def aggregate(root: Path, paths: list[Path]) -> tuple[list[str], str]:
    values = []
    for path in sorted(paths):
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root)
        ):
            raise ValueError("unsafe gateway input")
        rel = path.relative_to(root).as_posix()
        values.append({"path": rel, "sha256": sha256(path.read_bytes()).hexdigest()})
    if len({x["path"] for x in values}) != len(values):
        raise ValueError("duplicate gateway input")
    return [x["path"] for x in values], sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main() -> None:
    inputs, input_digest = aggregate(
        GATEWAY,
        list((GATEWAY / "src").rglob("*.ts"))
        + [
            GATEWAY / "package.json",
            GATEWAY / "package-lock.json",
            GATEWAY / "tsconfig.json",
        ],
    )
    outputs, output_digest = aggregate(
        GATEWAY, [path for path in (GATEWAY / "dist").rglob("*") if path.is_file()]
    )
    value = {
        "format": "asterion.prime-development-preparation-lock/v1",
        "node": {
            "amd64": {
                "url": "https://nodejs.org/dist/v22.23.2/node-v22.23.2-linux-x64.tar.xz",
                "archive_sha256": "d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307",
                "node_sha256": "3517c2df0b2f8cd7f422b4b8450ef81c6889f08eb03e281d6de9079b15e6a327",
            },
            "arm64": {
                "url": "https://nodejs.org/dist/v22.23.2/node-v22.23.2-linux-arm64.tar.xz",
                "archive_sha256": "fff4078c5def658577f92c88db7db3bc0072924bfb93fe52c1e744a54e94abb8",
                "node_sha256": "1a638b0fe2b68da0489276aca95526c5122fc61ba54d6a2d0d00c1c92ab7b876",
            },
        },
        "seccomp": {
            "canonical_sha256": "9da637d2ab0a204fcbd91bd88f1be9e004a3acab61c571a9f5b8870e588a17d2",
            "raw_sha256": "536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74",
            "commit": "836ae4d37ef2ec995c77c99fc55f5b5f3af3a897",
        },
        "gateway": {
            "inputs": inputs,
            "inputs_sha256": input_digest,
            "outputs": outputs,
            "outputs_sha256": output_digest,
        },
        "source": {
            "commit": PRIME_IPYTHON_SOURCE.commit,
            "tree_sha256": PRIME_IPYTHON_SOURCE.tree_sha256,
            "package_lock_sha256": PRIME_IPYTHON_SOURCE.package_lock_sha256,
        },
        "images": {
            "p1": [
                "asterion-p1b-development:20260906",
                "sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657",
            ],
            "p2": [
                "asterion-p2-development:20260906",
                "sha256:7d97b51a21bfffe6caa574063294f72205c60b05d8650fab8c70fdf661921c33",
            ],
            "p3": [
                "asterion-p3-development:20260906",
                "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243",
            ],
        },
    }
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
