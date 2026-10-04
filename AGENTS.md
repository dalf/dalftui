# Local Codex guidance

## GitHub access

- Use the authenticated `gh` CLI to inspect GitHub issues and pull requests.
- Read an issue with `gh issue view <number-or-url> --json number,title,body,state,labels,comments,createdAt,updatedAt,closedAt,url`.
- If the sandbox blocks GitHub access, retry the command with scoped network approval.

## Editor bridge compatibility

The bridge contract and versioning rules live in [bridge_protocol.py](bridge_protocol.py).
They cover requests and responses, framing, authentication, endpoint syntax,
environment names, and SSH credential delivery and bootstrap behavior. Networking
and editor launch code live elsewhere, but changes there can still affect the contract.

When changing the contract or SSH bootstrap:

- Assess both old-remote/new-desktop and new-remote/old-desktop compatibility.
  Explain in the change summary whether a protocol bump is required and why.
- Add a compatibility test in [tests/test_bridge_protocol.py](tests/test_bridge_protocol.py)
  that exercises the affected behavior against a supported historical peer.
- If a previously supported pairing can no longer perform a valid operation
  correctly, increment `PROTOCOL_VERSION` and document the break in the module.
  Add the new version to `SUPPORTED_PROTOCOL_VERSIONS` only when the decoder
  implements it; retain older versions only while their behavior is supported.
- Preserve [tests/fixtures/bridge_protocol_v1.py](tests/fixtures/bridge_protocol_v1.py)
  and other historical fixtures. Do not rewrite an old peer to match the current
  implementation or construct both peers from current helpers. Add a new fixture
  for a new protocol version.
- Missing request version metadata is the known authenticated v1 wire format.
  Keep that explicit compatibility rule while v1 is supported. A remote checkout
  without a readable protocol declaration is different: it must not receive bridge
  credentials. Unsupported versions must not launch an editor.
- Pre-declaration peers ignore version metadata. A future breaking client must
  establish peer compatibility before sending an operation; detecting a version
  mismatch after a response cannot undo an editor launch on an old bridge.

Refactoring, logging, and fixes that preserve the existing contract usually do
not require a bump. Optional fields are compatible only when supported old peers
ignore them safely and new peers do not require them. Identical field shapes do
not establish compatibility when their meaning or bootstrap behavior changes.
