from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ProviderName(str, Enum):
    CLAUDE_CODE = "claude-code"


class SessionStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    CLOSED = "closed"
    ERROR = "error"


class SupportLevel(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PARTIAL = "partial"
    PROVIDER_SPECIFIC = "provider_specific"


class ExecutionMode(str, Enum):
    DEFAULT = "default"
    READ_ONLY = "read_only"
    APPROVE_EDITS = "approve_edits"
    AUTO = "auto"
    BYPASS = "bypass"


class FilesystemPolicy(str, Enum):
    WORKSPACE_ONLY = "workspace_only"
    READ_ONLY = "read_only"
    UNRESTRICTED = "unrestricted"


class NetworkPolicy(str, Enum):
    DENY_BY_DEFAULT = "deny_by_default"
    ALLOWLIST = "allowlist"
    UNRESTRICTED = "unrestricted"


class WorkspaceRetention(str, Enum):
    DELETE = "delete"
    SNAPSHOT = "snapshot"
    KEEP = "keep"


class ApprovalMode(str, Enum):
    PROVIDER_NATIVE = "provider_native"
    BROKER = "broker"
    AUTO_DENY = "auto_deny"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    DENY = "deny"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SkillSourceType(str, Enum):
    LOCAL_PATH = "local_path"
    S3_URI = "s3_uri"


class ModelConfig(BaseModel):
    name: str | None = Field(default=None, description="Logical or provider model name.")
    fallback: str | None = Field(default=None, description="Fallback model when provider supports it.")


class RuntimeConfig(BaseModel):
    base_url: str | None = Field(default=None, description="Provider/model gateway base URL.")
    api_key_ref: str | None = Field(default=None, description="Reference to a server-side secret, not a raw API key.")
    cwd: str | None = Field(default=None, description="Working directory allocated by the runtime.")
    env: dict[str, str] = Field(default_factory=dict, description="Additional provider environment variables.")


class GenerationConfig(BaseModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, gt=0)
    stop: list[str] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    execution_mode: ExecutionMode = Field(default=ExecutionMode.DEFAULT)
    approval_mode: ApprovalMode = Field(default=ApprovalMode.PROVIDER_NATIVE)
    approval_timeout_seconds: float = Field(default=300, gt=0)
    allowed_tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    filesystem: FilesystemPolicy = Field(default=FilesystemPolicy.WORKSPACE_ONLY)
    network: NetworkPolicy = Field(default=NetworkPolicy.DENY_BY_DEFAULT)
    allowed_hosts: list[str] = Field(default_factory=list)


class SandboxConfig(BaseModel):
    profile: str | None = Field(default=None, description="Server-defined sandbox runtime profile.")
    workspace_retention: WorkspaceRetention = Field(default=WorkspaceRetention.DELETE)
    timeout_seconds: int | None = Field(default=None, gt=0)


class SkillSource(BaseModel):
    type: SkillSourceType
    path: str | None = Field(default=None, description="Absolute path visible inside the Aviary runtime container.")
    uri: str | None = Field(default=None, description="S3 URI for a skill bundle or skill root.")

    @model_validator(mode="after")
    def validate_source(self) -> "SkillSource":
        if self.type == SkillSourceType.LOCAL_PATH:
            if not self.path:
                raise ValueError("local_path skill source requires path")
            if not Path(self.path).expanduser().is_absolute():
                raise ValueError("local_path skill source path must be absolute")
            return self
        if self.type == SkillSourceType.S3_URI:
            if not self.uri:
                raise ValueError("s3_uri skill source requires uri")
            if not self.uri.startswith("s3://"):
                raise ValueError("s3_uri skill source uri must start with s3://")
            return self
        raise ValueError(f"unsupported skill source type: {self.type}")


class SkillConfig(BaseModel):
    names: list[str] | Literal["all"] | None = Field(
        default=None,
        description="Optional Claude Code skill names to expose. Use 'all' to expose all discovered skills.",
    )
    sources: list[SkillSource] = Field(
        default_factory=list,
        description="Skill directories or object-store prefixes materialized by Aviary.",
    )
    auto_allow_skill_tool: bool = Field(
        default=True,
        description="When true, Aviary adds the Claude Code Skill tool to allowed tools for this session.",
    )

    @field_validator("names")
    @classmethod
    def validate_names(cls, value: list[str] | Literal["all"] | None) -> list[str] | Literal["all"] | None:
        if value in (None, "all"):
            return value
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("skill names cannot be empty")
        return normalized

    def is_enabled(self) -> bool:
        return bool(self.sources or self.names)


class ProviderOptionSupport(BaseModel):
    level: SupportLevel
    fields: list[str] = Field(default_factory=list)
    notes: str | None = None


class CreateSessionRequest(BaseModel):
    provider: ProviderName = Field(default=ProviderName.CLAUDE_CODE)
    conversation_id: str | None = Field(default=None, min_length=1, description="Caller-provided conversation correlation id.")

    model: ModelConfig = Field(default_factory=ModelConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    skills: SkillConfig = Field(default_factory=SkillConfig)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, description="Non-authoritative caller metadata for correlation only.")

    # Backward-compatible flat fields. New integrations should prefer the DTOs above.
    cwd: str | None = None
    system_prompt: str | None = None
    permission_mode: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("conversation_id cannot be empty")
        return stripped

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = {**data}
        if isinstance(normalized.get("model"), str):
            normalized["model"] = {"name": normalized["model"]}
        return normalized


class SessionResponse(BaseModel):
    session_id: str
    provider: ProviderName
    conversation_id: str
    status: SessionStatus
    provider_session_id: str | None = None


class StreamMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message cannot be empty")
        return stripped


class AgentEvent(BaseModel):
    type: Literal[
        "start",
        "ai_chunk",
        "reasoning_delta",
        "tool_call",
        "tool_result",
        "error",
        "end",
        "raw",
    ]
    session_id: str
    conversation_id: str
    data: dict[str, Any] = Field(default_factory=dict)


class ApprovalResponse(BaseModel):
    approval_id: str
    session_id: str
    tool_name: str
    tool_input: dict[str, Any]
    status: ApprovalStatus
    reason: str | None = None
    tool_use_id: str | None = None
    agent_id: str | None = None
    created_at: float
    expires_at: float
    decided_at: float | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=1000)


class ProviderCapabilities(BaseModel):
    provider: ProviderName
    supports_streaming: bool = True
    supports_resume: bool = False
    supports_tools: bool = False
    supports_file_watch: bool = False
    supports_approval: bool = False
    supports_model_switch: bool = False
    session_config_fields: list[str] = Field(default_factory=list)
    config_schema: dict[str, ProviderOptionSupport] = Field(default_factory=dict)
    event_types: list[str] = Field(default_factory=list)
