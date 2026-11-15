import dataclasses
import re
from collections.abc import Iterator

from .help_model import Argument, Command, Option


@dataclasses.dataclass(frozen=True)
class Literals:
    values: tuple[str, ...]
    delimiter: str | None = None

    def __post_init__(self) -> None:
        for value in self.values:
            token = value.split("\t", 1)[0]
            if not token or token.startswith("$") or any(c.isspace() for c in token):
                raise ValueError(f"invalid literal completion: {value!r}")


@dataclasses.dataclass(frozen=True)
class Resource:
    name: str


@dataclasses.dataclass(frozen=True)
class Paths:
    macro: str


@dataclasses.dataclass(frozen=True)
class Exempt:
    reason: str


@dataclasses.dataclass(frozen=True)
class Documented:
    """Values listed in help text, matched by the `values` group of `pattern`."""

    pattern: str


Rule = Literals | Resource | Paths | Exempt | Documented
Completion = Literals | Resource | Paths | Exempt
VALUE_SEPARATOR = re.compile(r",\s+or\s+|,\s+|\s+or\s+")
PARENTHESIZED = Documented(r"\((?P<values>[^()]+)\)\.?$")
LISTED_AFTER_COLON = Documented(r": (?P<values>[^:]+)$")

FILES = Paths("$files")
DIRECTORIES = Paths("$directories")
ACCOUNTS = Resource("accounts")
DOMAINS = Resource("domains")
LOCAL_MCP_SERVERS = Resource("local-mcp-servers")
MODEL_PROVIDERS = Resource("model-providers")
PROJECTS = Resource("projects")
REMOTE_MCP_SERVERS = Resource("remote-mcp-servers")
RUNNERS = Resource("runners")
SECRETS = Resource("secrets")
SKILLS = Resource("skills")
THREADS = Resource("threads")
TOOLS = Resource("tools")
RESOURCES = frozenset(
    {
        ACCOUNTS,
        DOMAINS,
        LOCAL_MCP_SERVERS,
        MODEL_PROVIDERS,
        PROJECTS,
        REMOTE_MCP_SERVERS,
        RUNNERS,
        SECRETS,
        SKILLS,
        THREADS,
        TOOLS,
    }
)

ORB_SIZES = Literals(
    ("a1.tiny", "a1.small", "a1.medium", "a1.large", "a1.xxlarge", "a1.3xlarge")
)
AGENT_MODES = Literals(("low", "medium", "high", "ultra"))
REASONING_EFFORTS = Literals(("none", "minimal", "low", "medium", "high", "xhigh", "max"))
NEW_NAME = Exempt("new name")
NOT_LISTED = Exempt("Amp has no JSON listing for these values")
NOT_QUERIED = Exempt("helper does not query these values yet")
EXTERNAL_IDS = Exempt("external session IDs")

# NOTE: Lookup order: EXACT, FLAG_DEFAULTS, PLACEHOLDER_DEFAULTS, then *-file and *-dir flags.
EXACT: dict[tuple[str, ...], Rule] = {
    ("amp", "--attach"): FILES,
    ("amp", "--executor"): Literals(("local", "orb")),
    ("amp", "--runner-dir"): Exempt("directory on a remote runner"),
    ("amp", "boxes", "cp", "<destination>"): FILES,
    ("amp", "boxes", "cp", "<source>"): FILES,
    ("amp", "boxes", "create", "--size"): Exempt("machine sizes not documented"),
    ("amp", "boxes", "deploy", "--branch"): Exempt("Git branch name"),
    ("amp", "boxes", "deploy", "--domain"): DOMAINS,
    ("amp", "boxes", "deploy", "--size"): Exempt("machine sizes not documented"),
    ("amp", "boxes", "deploy", "<target>"): NOT_QUERIED,
    ("amp", "boxes", "rename", "<new-name>"): NEW_NAME,
    ("amp", "account", "switch", "<account>"): ACCOUNTS,
    ("amp", "clone", "<repository>"): Exempt("repository reference"),
    ("amp", "clone", "<target-dir>"): DIRECTORIES,
    ("amp", "completions", "<shell>"): Literals(("bash", "zsh", "fish", "pwsh")),
    ("amp", "config", "model-providers", "add-key", "<provider>"): LISTED_AFTER_COLON,
    ("amp", "config", "model-providers", "add-router", "<router>"): LISTED_AFTER_COLON,
    ("amp", "config", "model-providers", "check-access", "--provider-key"): MODEL_PROVIDERS,
    ("amp", "config", "model-providers", "delete", "<id>"): MODEL_PROVIDERS,
    ("amp", "config", "model-providers", "setup-guide", "<provider>"): LISTED_AFTER_COLON,
    ("amp", "config", "model-providers", "show", "<id>"): MODEL_PROVIDERS,
    ("amp", "config", "model-providers", "test", "<id>"): MODEL_PROVIDERS,
    ("amp", "domains", "add", "<hostname>"): Exempt("new hostname"),
    ("amp", "domains", "check", "<hostname>"): DOMAINS,
    ("amp", "domains", "remove", "<hostname>"): DOMAINS,
    ("amp", "logout", "<account>"): ACCOUNTS,
    ("amp", "mcp", "add", "<args>"): Exempt("server command arguments"),
    ("amp", "mcp", "add", "<name>"): NEW_NAME,
    ("amp", "mcp", "approve", "<name>"): LOCAL_MCP_SERVERS,
    ("amp", "mcp", "doctor", "<name>"): LOCAL_MCP_SERVERS,
    ("amp", "mcp", "oauth", "login", "<server-name>"): LOCAL_MCP_SERVERS,
    ("amp", "mcp", "oauth", "logout", "<server-name>"): LOCAL_MCP_SERVERS,
    ("amp", "mcp", "oauth", "status", "<server-name>"): LOCAL_MCP_SERVERS,
    ("amp", "mcp", "remote", "add", "<name>"): NEW_NAME,
    ("amp", "mcp", "remote", "check", "<server>"): REMOTE_MCP_SERVERS,
    ("amp", "mcp", "remote", "login", "<server>"): REMOTE_MCP_SERVERS,
    ("amp", "mcp", "remote", "logout", "<server>"): REMOTE_MCP_SERVERS,
    ("amp", "mcp", "remote", "remove", "<server>"): REMOTE_MCP_SERVERS,
    ("amp", "mcp", "remote", "tools", "<server>"): REMOTE_MCP_SERVERS,
    ("amp", "mcp", "remote", "update", "<server>"): REMOTE_MCP_SERVERS,
    ("amp", "mcp", "remove", "<name>"): LOCAL_MCP_SERVERS,
    ("amp", "net", "route", "<exit-node>"): NOT_LISTED,
    ("amp", "oauth-clients", "create", "--type"): Exempt("client types not documented"),
    ("amp", "oauth-clients", "edit", "<id>"): NOT_LISTED,
    ("amp", "orb", "portal", "--hostname"): DOMAINS,
    ("amp", "orb", "portal", "<target>"): Exempt("port or loopback URL"),
    ("amp", "orb", "portal", "access", "<value>"): Exempt("access values not documented"),
    ("amp", "orb", "provider", "<script>"): FILES,
    ("amp", "orb", "provider", "create", "<name>"): NEW_NAME,
    ("amp", "orb", "provider", "set-default", "<name>"): NOT_QUERIED,
    ("amp", "orb", "service", "logs", "<name>"): NOT_LISTED,
    ("amp", "orb", "service", "restart", "<name>"): NOT_LISTED,
    ("amp", "orb", "service", "start", "<name>"): NOT_LISTED,
    ("amp", "orb", "service", "status", "<name>"): NOT_LISTED,
    ("amp", "orb", "service", "stop", "<name>"): NOT_LISTED,
    ("amp", "orb", "simulator", "serve", "--device"): NOT_LISTED,
    ("amp", "orb", "simulator", "serve", "--runtime"): NOT_LISTED,
    ("amp", "permissions", "add", "--to"): FILES,
    ("amp", "permissions", "add", "<action>"): Documented(r"^Permission action: (?P<values>.+)$"),
    ("amp", "plugins", "add", "--target"): Literals(("system", "workspace")),
    ("amp", "plugins", "exec", "<event>"): Exempt("event names not documented"),
    ("amp", "plugins", "exec", "<plugin>"): FILES,
    ("amp", "plugins", "remove", "--target"): Literals(("system", "workspace")),
    ("amp", "plugins", "remove", "<plugin>"): NOT_LISTED,
    ("amp", "plugins", "update", "<plugin>"): NOT_LISTED,
    ("amp", "profile", "create", "<name>"): NEW_NAME,
    ("amp", "profile", "delete", "<name>"): NOT_QUERIED,
    ("amp", "profile", "rename", "<name>"): NOT_QUERIED,
    ("amp", "profile", "use", "<name>"): NOT_QUERIED,
    ("amp", "projects", "create", "<repository>"): Exempt("repository reference"),
    ("amp", "projects", "feedback-widget", "remove-origin", "<origins>"): NOT_QUERIED,
    ("amp", "projects", "snapshots", "delete", "--resource"): ORB_SIZES,
    ("amp", "runner", "desktop", "allow", "<permission>"): Exempt("permission names not documented"),
    ("amp", "runner", "dirs", "add", "<paths>"): DIRECTORIES,
    ("amp", "runner", "dirs", "remove", "<paths>"): DIRECTORIES,
    ("amp", "secrets", "delete", "<name>"): SECRETS,
    ("amp", "secrets", "get", "<name>"): SECRETS,
    ("amp", "secrets", "history", "<name>"): SECRETS,
    ("amp", "secrets", "set", "<name>"): SECRETS,
    ("amp", "skill", "add", "<source>"): FILES,
    ("amp", "skill", "info", "<name>"): SKILLS,
    ("amp", "skill", "remove", "<name>"): SKILLS,
    ("amp", "spaces", "create", "--shared-with"): Exempt("sharing values not documented"),
    ("amp", "spaces", "create", "<name>"): NEW_NAME,
    ("amp", "svc", "<service>"): Exempt("service list differs from MCP server listings"),
    ("amp", "svc", "<tool>"): Exempt("service tools are not listed"),
    ("amp", "threads", "color", "<color>"): Literals(
        ("blue", "purple", "pink", "red", "orange", "yellow", "green", "cyan")
    ),
    ("amp", "threads", "import", "codex", "<threadIds>"): EXTERNAL_IDS,
    ("amp", "threads", "import", "conductor", "--conductor-db"): FILES,
    ("amp", "tools", "list", "--mode"): AGENT_MODES,
    ("amp", "tools", "show", "--mode"): AGENT_MODES,
}

FLAG_DEFAULTS: dict[str, Rule] = {
    "anthropic-federation-rule-id": NOT_LISTED,
    "anthropic-organization-id": NOT_LISTED,
    "anthropic-service-account-id": NOT_LISTED,
    "anthropic-workspace-id": NOT_LISTED,
    "api-format": Documented(r"API format: (?P<values>.+)$"),
    "auth": Documented(r"^Authentication type: (?P<values>[^.(]+?)(?: \(|\.|$)"),
    "client-id": NOT_LISTED,
    "cloudflare-account-id": NOT_LISTED,
    "cloudflare-gateway-id": NOT_LISTED,
    "context": PARENTHESIZED,
    "deployment": NOT_LISTED,
    "effort": REASONING_EFFORTS,
    "entra-application": NOT_LISTED,
    "features": Literals(
        (
            "fast\tFaster serving",
            "plaid\tUltrafast serving",
            "pro\tGPT-5.6 Pro mode",
        ),
        delimiter=",",
    ),
    "foundry-resource": NOT_LISTED,
    "google-cloud-project": NOT_LISTED,
    "icon": FILES,
    "id": Exempt("new exit node ID"),
    "installation-id": NOT_LISTED,
    "log-file": FILES,
    "log-level": Literals(("debug", "info", "warn", "error", "audit")),
    "mcp-config": FILES,
    "mode": Documented(r"\((?P<values>[^()]+?)(?:, a model as [^,]+)?, or a plugin mode"),
    "name": NEW_NAME,
    "oauth-client-id": NOT_LISTED,
    "openai-identity-provider-id": NOT_LISTED,
    "openai-service-account-id": NOT_LISTED,
    "openrouter-federation-policy-id": NOT_LISTED,
    "orb-provider": NOT_QUERIED,
    "orb-size": ORB_SIZES,
    "orb-type": NOT_LISTED,
    "output": FILES,
    "profile": NOT_QUERIED,
    "reasoning-effort": REASONING_EFFORTS,
    "remote": Exempt("new Git remote name"),
    "repository-mode": Literals(("github", "mapped")),
    "runner-id": RUNNERS,
    "settings-file": FILES,
    "space": NOT_QUERIED,
    "ship-behavior": Literals(("ship", "push-to-branch", "custom")),
    "subject-scope": Documented(r"\((?P<values>[^();]+); default"),
    "visibility": PARENTHESIZED,
}

FREE_FORM = Exempt("free-form value")
PLACEHOLDER_DEFAULTS: dict[str, Rule] = {
    "chatIds": EXTERNAL_IDS,
    "connection-id": MODEL_PROVIDERS,
    "deployment": NOT_LISTED,
    "dir": DIRECTORIES,
    "folder": DIRECTORIES,
    "namespace/name": NOT_QUERIED,
    "new-name": NEW_NAME,
    "project": PROJECTS,
    "sessionIds": EXTERNAL_IDS,
    "thread": THREADS,
    "thread-url": THREADS,
    "thread-url-or-id": THREADS,
    "threads": THREADS,
    "tool": TOOLS,
    "tool-name": TOOLS,
    **dict.fromkeys(
        (
            "arn",
            "attachment-url",
            "audience",
            "author",
            "branch",
            "command",
            "count",
            "days",
            "description",
            "domain",
            "email",
            "goal",
            "HH:MM",
            "hours",
            "json",
            "kv",
            "label",
            "labels",
            "location",
            "machine",
            "mapping",
            "message",
            "minutes",
            "n",
            "names",
            "namespace",
            "newName",
            "number",
            "page",
            "port",
            "portal-url",
            "priority",
            "provider/model",
            "provider/name",
            "query",
            "region",
            "resource-name",
            "scope",
            "scopes",
            "seconds",
            "secret",
            "terms",
            "text",
            "timestamp",
            "title",
            "token",
            "uri",
            "url",
            "version",
            "weeks",
            "workspace",
            "zone",
        ),
        FREE_FORM,
    ),
}


@dataclasses.dataclass(frozen=True)
class Field:
    command: tuple[str, ...]
    option: Option | None = None
    argument: Argument | None = None

    @property
    def key(self) -> tuple[str, ...]:
        if self.option is not None:
            return (*self.command, self.option.canonical)
        assert self.argument is not None
        return (*self.command, f"<{self.argument.name}>")

    @property
    def placeholder(self) -> str:
        value = self.option.value if self.option is not None else self.argument
        assert value is not None
        return value.name

    @property
    def description(self) -> str:
        described = self.option if self.option is not None else self.argument
        assert described is not None
        return described.description


@dataclasses.dataclass(frozen=True)
class Resolution:
    completions: dict[tuple[str, ...], Completion]
    diagnostics: tuple[str, ...]
    stale_rules: tuple[str, ...] = ()

    def flags(self, path: tuple[str, ...], command: Command) -> list[tuple[str, Completion]]:
        return [
            (option.name, completion)
            for option in command.options
            if (completion := self.completions.get((*path, option.canonical)))
            and not isinstance(completion, Exempt)
        ]

    def positionals(
        self, path: tuple[str, ...], command: Command
    ) -> list[tuple[Argument, Completion | None]]:
        return [
            (argument, self.completions.get((*path, f"<{argument.name}>")))
            for argument in command.arguments
        ]


def fields(command: Command, parents: tuple[str, ...] = ()) -> Iterator[Field]:
    path = (*parents, command.name)
    for option in command.options:
        if option.value is not None:
            yield Field(path, option=option)
    for argument in command.arguments:
        yield Field(path, argument=argument)
    for child in command.commands:
        yield from fields(child, path)


def documented_values(rule: Documented, field: Field) -> Literals:
    match = re.search(rule.pattern, field.description)
    if not match:
        raise ValueError("help no longer documents values")
    return Literals(tuple(VALUE_SEPARATOR.split(match["values"].strip())))


def resolve(root: Command) -> Resolution:
    completions: dict[tuple[str, ...], Completion] = {}
    diagnostics = []
    used_flag_defaults = set()
    used_placeholder_defaults = set()

    for field in fields(root):
        completion: Rule | None = EXACT.get(field.key)
        if completion is None and field.option is not None:
            completion = FLAG_DEFAULTS.get(field.option.name)
            if completion is not None:
                used_flag_defaults.add(field.option.name)
        if completion is None:
            completion = PLACEHOLDER_DEFAULTS.get(field.placeholder)
            if completion is not None:
                used_placeholder_defaults.add(field.placeholder)
        if completion is None and field.option is not None and field.option.name.endswith("-file"):
            completion = FILES
        if completion is None and field.option is not None and field.option.name.endswith("-dir"):
            completion = DIRECTORIES
        if completion is None:
            diagnostics.append(f"no completion rule: {' '.join(field.key)}")
            continue
        if isinstance(completion, Documented):
            try:
                completion = documented_values(completion, field)
            except ValueError as error:
                diagnostics.append(f"{error}: {' '.join(field.key)}")
                continue
        completions[field.key] = completion

    live_keys = {field.key for field in fields(root)}
    stale_rules = [
        *(
            f"rule targets no value-taking field: {' '.join(key)}"
            for key in sorted(set(EXACT) - live_keys)
        ),
        *(f"unused flag default: --{name}" for name in sorted(set(FLAG_DEFAULTS) - used_flag_defaults)),
        *(
            f"unused placeholder default: <{name}>"
            for name in sorted(set(PLACEHOLDER_DEFAULTS) - used_placeholder_defaults)
        ),
    ]
    return Resolution(completions, tuple(diagnostics), tuple(stale_rules))
