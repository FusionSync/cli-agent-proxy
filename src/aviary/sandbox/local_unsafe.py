from aviary.sandbox.embedded import EmbeddedSandboxDriver


# Backward-compatible import path for early pre-embedded releases.
LocalUnsafeSandboxDriver = EmbeddedSandboxDriver

__all__ = ["LocalUnsafeSandboxDriver"]
