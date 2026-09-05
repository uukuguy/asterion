# Prime Authority Bundle Contract

Status: Astra implementation freeze following the accepted execution delta and independent Sol review. Private operator contract; no public Asterion v1 changes and no production execution grant.

## Ownership and interfaces

Implement in `src/asterion/applications/prime_agent/operator/authority_bundle.py` with `tests/test_prime_authority_bundle.py`.

```python
@dataclass(frozen=True, slots=True, repr=False)
class AuthorityRuntimeIdentityV2:
    interpreter_executable_sha256: str
    authority_bundle_sha256: str
    launch_profile_sha256: str

@dataclass(frozen=True, slots=True, repr=False)
class AuthorityBundleFile:
    path: str
    role: str
    mode: int
    size: int
    sha256: str

# Release/profile records recursively freeze nested values.
@dataclass(frozen=True, slots=True, repr=False)
class AuthorityBundleRelease:
    release_version: str
    target: ImagePlatformDescriptor
    interpreter_path: str
    files: tuple[AuthorityBundleFile, ...]
    launch_profile: AuthorityLaunchProfile

# AuthorityLaunchProfile uses the exact fields in the table below; nested
# profile records are frozen dataclasses and arrays become tuples.
def parse_authority_bundle_release(data: bytes) -> AuthorityBundleRelease: ...
def declared_authority_runtime_identity(
    release: AuthorityBundleRelease,
) -> AuthorityRuntimeIdentityV2: ...
def admit_authority_bundle(
    bundle_root_fd: int,
    release_inventory_fd: int,
    selected_target: ImagePlatformDescriptor,
    expected_identity: AuthorityRuntimeIdentityV2,
) -> AdmittedAuthorityBundle: ...

class AdmittedAuthorityBundle:
    def _runtime_identity(self) -> AuthorityRuntimeIdentityV2: ...
    def _revalidate_for_spawn(self) -> None: ...
    def close(self) -> None: ...
```

The parser and declared identity function are syntax/digest utilities, never admission or authorization. `expected_identity` comes from the trusted manager's exact operator-selected release record, not an application request or authority self-report. The production manager must separately admit deployment policy and scenario authority. Do not create another empty hardcoded catalog just for parsing; preserve the old standalone-ELF catalog and its meaning.

Valid exact integer input descriptors transfer at admission call entry. Immediately set each unique owned descriptor non-inheritable (FD_CLOEXEC); only the later exact Task 3 spawn may deliberately remap it across exec. Close each once on failure, including malformed target/identity and duplicate descriptor rejection. On success retain root, inventory and no-follow interpreter descriptors until close. Retain immutable initial stat identities and canonical inventory bytes. No generic exec, path/argv projection, copy or pickle interface. Constructor is sealed; errors/repr expose only fixed safe text. Closed/revalidation-failed resources cannot be reused.

## Canonical release inventory

Exact top-level keys:

```json
{
  "format": "asterion.prime-p1-authority-bundle-release/v1",
  "release_version": "2.0.0",
  "target": {"os": "linux", "architecture": "arm64", "variant": null},
  "interpreter_path": "bin/python3",
  "files": [],
  "launch_profile": {}
}
```

The empty arrays/object above illustrate field positions only and are invalid releases. Supported exact targets initially are Linux arm64/no variant and Linux amd64/no variant. No architecture inferred from the current host. Interpreter path is fixed to `bin/python3` for this release profile.

JSON is UTF-8, sorted keys, compact separators, `ensure_ascii=False`, no NaN/Infinity, duplicates, BOM or trailing newline. Require the input bytes equal canonical re-encoding. Native exact types only: bool is not an integer. Maximum inventory 16 MiB, 100,000 files, 512 MiB per file, 2 GiB total file bytes and nesting depth 16. Relative paths use POSIX separators and printable ASCII components `[A-Za-z0-9_.-]+`; reject empty/dot/dotdot components, backslashes and absolute paths. SHA-256 values are exactly 64 lowercase hex characters. `release_version` is exactly `2.0.0`, not an illustrative range. File sizes include zero-byte files and reject negative values; count and byte caps still apply.

Each file has exactly `{path,role,mode,size,sha256}`. Files are sorted uniquely by path. Roles are `bootstrap`, `interpreter`, `python-source`, `native-extension`, `shared-library`, `distribution-metadata`, `data`. Require exactly one interpreter and one bootstrap. Interpreter must be `bin/python3`, bootstrap must equal profile `bootstrap_path`. Allowed modes are 0444, 0555, 0644 and 0755; interpreter requires an executable mode. No `.pyc`, `.pyo`, `.pth`, `sitecustomize.py`, `usercustomize.py`, `.egg-link` or `direct_url.json` entries. This profile uses source imports and `-B`; bytecode/editable import mechanisms are not part of it.

Inventory is a root-owned private regular file outside the bundle root and is not itself a bundle entry. Expected directories are exactly the parents derived from file paths. No additional directory, even empty, is allowed. Include all package resources, dist-info, Python stdlib and dependencies actually made available to the process. The legacy thirteen-file artifact lock remains a source subset, not an import-closure proof.

## Exact launch profile

The profile is validated into immutable typed records, never accepted as an opaque arbitrary mapping. Exact keys and constraints:

| Key | Required value or validation |
|---|---|
| `profile_version` | `1.0.0` |
| `bootstrap_path` | Canonical relative path naming the sole bootstrap entry |
| `argv` | Ordered exact `["/proc/self/fd/7/bin/python3","-I","-S","-B","/proc/self/fd/9"]`; fd 9 must equal the bootstrap entry stat/digest |
| `python_flags` | Ordered exact `['-I','-S','-B']` |
| `python_path` | Nonempty sorted unique relative directories from the inventory-derived directory set; no ambient path |
| `environment` | Empty object; manager clears the environment |
| `cwd_role` | `runtime-directory` |
| `umask` | Integer 63 (0077) |
| `authority_uid`, `authority_gid` | Exact integers 1 through 4294967294; manager verifies separation from other roles |
| `supplementary_gids`, `capabilities` | Empty arrays |
| `no_new_privs` | `true` |
| `rlimits` | Exact keys `cpu_seconds`, `file_bytes`, `open_files`, `processes`, `address_space_bytes`; exact positive integers bounded respectively by 120, 16777216, 256, 64, 2147483648 |
| `inherited_fds` | Exact ordered entries listed below |
| `socket` | Exact object listed below |
| `ipc_protocol` | `asterion.prime-p1-authority-ipc/v2` |
| `receipt_format` | `asterion.prime-p1-authority-receipt/v2` |
| `max_packet_bytes` | 8192 |
| `deadline_milliseconds` | 60000 |
| `external_runtime` | Sorted unique absolute canonical file entries with exact `{path,role,mode,size,sha256}`, role `elf-loader` or `shared-library`; maximum 512 entries, same file size/mode/hash restrictions |

Inherited descriptor entries are exact `{fd,role}` pairs in ascending FD order: 3/config, 4/session-key, 5/runtime-directory, 6/launch-instance, 7/bundle-root, 8/release-inventory, 9/bootstrap. They survive exactly the intended exec, then immediately regain CLOEXEC. The interpreter FD used for fd-exec has CLOEXEC and is not a descriptor offered to application code. Task 3 consumes ownership explicitly; Task 2 does not expose spawn operations.

Socket object is exactly `{'basename':'authority.sock','runtime_dir_role':'runtime-directory','type':'SOCK_SEQPACKET','max_clients':1,'peer_policy':'exact-supervisor-pid-uid'}`. The authority owns bind/listen; the connecting peer is the supervisor, whose expected PID/UID the manager provides. The fixed argv is a launch identity, not permission to substitute a path exec for the retained interpreter fd-exec. Task 3 must prove bundled CPython prefix/stdlib resolution before accepting ready; an ambient `/usr/lib/pythonX` startup is a rejection, even before later sys.path replacement. Actual PID/run/session values are in the private launch instance, not this stable profile hash.

External runtime file paths are private operator inventory, not portable manifest fields. External paths have the same ASCII component grammar as bundle paths, with exactly one leading slash. Admit the canonical referent through no-follow opens of root-owned, non-group/world-writable directories, and a root-owned single-link regular final file. PT_INTERP aliases such as `/lib` are resolved only in the later loader audit through root-owned nonwritable symlink ancestry; their final real path must equal an admitted external entry. The release inventory itself records the canonical `/usr/lib/...` referent, never an alias. The ELF loader and native shared library closure must be enumerated and verified against actual process mappings in Task 3. Merely declaring libraries part of the TCB is not loaded-code identity proof. Task 2 validates and hashes the declared external entries; it cannot claim that an unlaunched process conforms to them.

## Identity equations and admission

Let `C` be the canonical JSON encoding above. Define:

- `I`: SHA-256 of the raw retained interpreter descriptor bytes; require equality with the sole interpreter entry digest.
- `B`: SHA-256 of `b'asterion.prime-p1-authority-bundle/v1\0' + C({release_version,target,interpreter_path,files})`.
- `P`: SHA-256 of `b'asterion.prime-p1-authority-launch-profile/v1\0' + C({**launch_profile,target,interpreter_executable_sha256:I,authority_bundle_sha256:B})`.

The declared identity function computes I from the inventory entry only. Admission computes actual I from bytes and requires the complete actual `(I,B,P)` equal the manager-supplied expected identity. This separation prevents digest computation being confused with resource admission. No caller-supplied duplicate derived hashes occur in the inventory.

Root and all directories must be uid 0 with no group/world writes. Inventory must be uid 0, single-link regular, no group/world writes, within its byte cap, and stable while read. Every file must have exact inventory mode/size/hash, uid 0, link count 1, and stable dev/ino/mode/uid/gid/nlink/size/mtime_ns/ctime_ns before and after read. Open descriptor-relative with O_NOFOLLOW, reject symlinks and all nonregular nodes, and reject extras/missing entries. Recheck root/parent identity during traversal. Keep inventory outside the bundle by rejecting its dev/ino among the walked files.

Validate interpreter ELF magic, ELFCLASS64, little-endian and e_machine 183 for arm64 or 62 for amd64. This identifies the candidate target only; actual fd-exec/import/mapping evidence belongs to Task 3. Before spawn, repeat exact inventory/tree/hash checks, retained interpreter identity validation and stat/hash validation of every declared external runtime file. Actual mapping coverage remains a Task 3 gate. Any failure closes the admitted bundle and raises the same public-safe error.

## Tests and delivery boundary

Use actual temporary file contents and `subTest` mutation matrices for canonicalization, exact keys/types, sorting, role uniqueness, target/header mismatch, unexpected files/directories, symlink/special/hard-linked files, owner/mode/size mismatch, read-time mutation, before-spawn replacement, failed-admission closure, close idempotence, copying/pickling and sentinel redaction. Root-owned filesystem success tests may execute in the existing Linux guest under a temporary root-owned test directory; non-root runs must report their exact skips. Do not mock these checks and call the result real Linux qualification.

Next consumers are manager/bootstrap and IPCv2. Ready binds manager-expected I/B/P plus request/resource identities; terminal verifies the same triple. Keep v1 receipt issuer/domain/payload byte-exact. Unpromoted real-bundle qualification uses its own domain or expected pre-ready UNAVAILABLE, never a production PASS minted through patched admission. Real P1-A, P1-B and the other six scenarios remain mandatory subsequent gates.
