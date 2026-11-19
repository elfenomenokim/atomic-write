# Security policy

## Supported versions

Security fixes go into the latest release. Upgrade before reporting, in case the
problem is already fixed.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Older | No |

## Reporting a vulnerability

Report it privately, not in a public issue: use the
[Report a vulnerability](https://github.com/elfenomenokim/atomic-write/security/advisories/new)
form on the repository's Security tab.

Include the call you made, the Python version and platform, and what an attacker
could do with the result. You get a reply within a few days, and you hear when a
fix is out. Say how you want to be credited if you want a name in the release
note.

## In scope

- A partially written file becoming visible to a reader, because the temporary
  file and the destination are not on the same filesystem or the rename is not
  used.
- A temporary file left readable with wider permissions than the final file, so a
  credential is exposed for a moment.
- `overwrite=False` overwriting an existing file, or two racing creators both
  succeeding, where a caller relies on it to claim a resource exclusively.
- A `durability` level silently not doing the fsync it names.
- A `dir_fd` write that escapes the descriptor it was given through the library
  itself.

## Out of scope

- A name containing `..` resolved by the kernel when a caller passes it with
  `dir_fd`. `dir_fd` is a containment tool for an already-validated name, not a
  sandbox; the caller validates the name.
- A caller that needs a read-modify-write cycle without holding its own lock. This
  library publishes one complete file and does not lock.
- Data left behind because the caller passed `durability="none"`.
- The contents of a file being wrong. This library moves bytes, not validates
  them.
