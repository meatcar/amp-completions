import type {
  PluginAPI,
  PluginThread,
  ToolCallEvent,
  ToolCallResult,
  ToolResultResult,
} from "@ampcode/plugin";

export const description =
  "In unattended automation threads, asks the owner before the agent uses tools outside an allowlist, changes guardrails, writes to other repositories, or contacts unknown hosts, and strips invisible Unicode from tool output.";

const REPOSITORY = "meatcar/amp-completions";
const UNATTENDED_MARKER = "[automation-guard: unattended]";
const PROTECTED_PATHS = [
  /^\.amp\//,
  /^\.agents\//,
  /^\.github\//,
  /^AGENTS\.md$/,
  /^CLAUDE\.md$/,
  /^flake\.nix$/,
  /^nix\//,
];
const ALLOWED_HOSTS = new Set([
  "github.com",
  "api.github.com",
  "raw.githubusercontent.com",
  "objects.githubusercontent.com",
  "codeload.github.com",
  "cache.nixos.org",
  "ampcode.com",
  "localhost",
  "127.0.0.1",
]);
const ALLOWED_API_WRITES = new RegExp(`^repos/${REPOSITORY}/(pulls|issues)(/[\\w/-]*)?$`);
// NOTE: Default deny. Tools not listed here need owner approval in unattended threads.
const ALLOWED_TOOLS = new Set([
  "Read",
  "read_file",
  "Grep",
  "grep",
  "glob",
  "list_directory",
  "edit_file",
  "create_file",
  "undo_edit",
  "shell_command",
  "async_shell_command",
  "shell_command_status",
  "shell_command_kill",
  "finder",
  "oracle",
  "Task",
  "skill",
  "view_media",
  "read_web_page",
]);
const GUARDED_GH_COMMANDS = new Set(["auth", "repo", "ruleset", "secret", "variable"]);
const ALLOWED_AMP_COMMANDS = new Set(["--help", "--version", "files", "orb", "usage"]);
const RAW_NETWORK_TOOLS = new Set(["nc", "ncat", "netcat", "scp", "sftp", "socat", "ssh"]);
const URL_TOOLS = new Set(["curl", "wget", "http", "xh"]);
const INVISIBLE =
  /[\u00AD\u180E\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069\uFEFF]|[\u{E0000}-\u{E007F}]/gu;

export function isProtectedPath(path: string): boolean {
  return PROTECTED_PATHS.some((pattern) => pattern.test(path));
}

function segments(command: string): string[][] {
  return command
    .split(/\n|;|&&|\|\||\|/)
    .map((segment) =>
      segment
        .trim()
        .split(/\s+/)
        .map((word) => word.replace(/^['"]|['"]$/g, ""))
        .filter((word) => word && !/^\w+=/.test(word)),
    )
    .filter((words) => words.length > 0);
}

function optionValue(words: string[], names: string[]): string | undefined {
  for (const [index, word] of words.entries()) {
    for (const name of names) {
      if (word === name) return words[index + 1];
      if (word.startsWith(`${name}=`)) return word.slice(name.length + 1);
    }
  }
  return undefined;
}

function ghViolation(words: string[]): string | null {
  const repository = optionValue(words, ["-R", "--repo"]);
  if (repository && repository !== REPOSITORY) return `gh targets ${repository}`;
  for (const word of words) {
    const url = word.match(/github\.com\/([^/\s]+\/[^/\s#?]+)/i)?.[1]?.replace(/\.git$/, "");
    if (url && url.toLowerCase() !== REPOSITORY) return `gh targets ${url}`;
  }
  const [subcommand] = words.slice(1).filter((word) => !word.startsWith("-"));
  if (GUARDED_GH_COMMANDS.has(subcommand))
    return `gh ${subcommand} changes account or repository settings`;
  if (subcommand !== "api") return null;

  const method = (optionValue(words, ["-X", "--method"]) ?? "GET").toUpperCase();
  const sendsBody = words.some((word) => /^(-f|-F|--field|--raw-field|--input)(=|$)/.test(word));
  if (method === "GET" && !sendsBody) return null;
  const path = words.find((word) => /^\/?repos\//.test(word))?.replace(/^\//, "");
  return path && ALLOWED_API_WRITES.test(path)
    ? null
    : `gh api writes ${path ?? "an unknown route"}`;
}

function networkViolation(words: string[]): string | null {
  const tool = words[0].split("/").at(-1) ?? "";
  if (RAW_NETWORK_TOOLS.has(tool)) return `${tool} opens a raw network connection`;
  if (!URL_TOOLS.has(tool)) return null;
  for (const word of words) {
    const match = word.match(
      /^(?:https?:\/\/)?([a-z0-9.-]+\.[a-z]{2,}|localhost|127\.0\.0\.1)(?=[:/]|$)/i,
    );
    if (match && !ALLOWED_HOSTS.has(match[1].toLowerCase())) return `${tool} contacts ${match[1]}`;
  }
  return null;
}

function urlViolation(value: unknown): string | null {
  try {
    const url = new URL(String(value));
    if (url.protocol === "https:" && ALLOWED_HOSTS.has(url.hostname)) return null;
    return `contacts ${url.host || url.protocol}`;
  } catch {
    return "contacts an unparseable URL";
  }
}

export function toolViolation(tool: string, input: Record<string, unknown>): string | null {
  if (!ALLOWED_TOOLS.has(tool)) return "is not on the unattended tool allowlist";
  return tool === "read_web_page" ? urlViolation(input.url) : null;
}

export function shellViolation(command: string): string | null {
  for (const words of segments(command)) {
    const tool = words[0].split("/").at(-1);
    if (tool === "gh") {
      const violation = ghViolation(words);
      if (violation) return violation;
    }
    if (tool === "amp" && !ALLOWED_AMP_COMMANDS.has(words[1] ?? ""))
      return `amp ${words[1] ?? ""} can change Amp settings or start threads`.trimEnd();
    if (tool === "git" && words.includes("push")) {
      const remote = words.slice(words.indexOf("push") + 1).find((word) => !word.startsWith("-"));
      if (remote && remote !== "origin") return `git push targets ${remote}`;
    }
    const violation = networkViolation(words);
    if (violation) return violation;
  }
  return null;
}

function clean(text: string): string {
  return text.replace(INVISIBLE, "\uFFFD");
}

function sanitize(value: unknown): unknown {
  if (typeof value === "string") return clean(value);
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, sanitize(item)]));
  return value;
}

export default function (amp: PluginAPI) {
  const root = amp.system.workspaceRoot
    ? amp.helpers.filePathFromURI(amp.system.workspaceRoot)
    : null;

  function shellCommand(event: ToolCallEvent): { command: string; dir?: string } | null {
    const known = amp.helpers.shellCommandFromToolCall(event);
    if (known) return known;
    const { command, workdir, cwd } = event.input;
    if (typeof command !== "string") return null;
    const dir = typeof workdir === "string" ? workdir : typeof cwd === "string" ? cwd : undefined;
    return { command, dir };
  }

  function relative(path: string): string {
    return root && path.startsWith(`${root}/`) ? path.slice(root.length + 1) : path;
  }

  async function outgoingProtectedFiles(
    event: ToolCallEvent,
    $: PluginAPI["$"],
  ): Promise<string[]> {
    const shell = shellCommand(event);
    if (
      !shell ||
      !segments(shell.command).some((words) => words[0] === "git" && words.includes("push"))
    )
      return [];
    const directory = shell.dir ?? root ?? ".";
    const result = await $`git -C ${directory} diff --name-only origin/main...HEAD`;
    if (result.exitCode !== 0) return ["(cannot list outgoing changes)"];
    return result.stdout.split("\n").filter((path) => path && isProtectedPath(path));
  }

  async function violation(event: ToolCallEvent, $: PluginAPI["$"]): Promise<string | null> {
    const toolReason = toolViolation(event.tool, event.input);
    if (toolReason) return toolReason;
    const edited = (amp.helpers.filesModifiedByToolCall(event) ?? [])
      .map((uri) => relative(amp.helpers.filePathFromURI(uri)))
      .filter(isProtectedPath);
    if (edited.length > 0) return `edits protected files: ${edited.join(", ")}`;
    const shell = shellCommand(event);
    const shellReason = shell ? shellViolation(shell.command) : null;
    if (shellReason) return shellReason;
    const pushed = await outgoingProtectedFiles(event, $);
    return pushed.length > 0 ? `pushes protected files: ${pushed.join(", ")}` : null;
  }

  const activation = new Map<string, boolean>();

  async function isActive(thread: PluginThread): Promise<boolean> {
    const cached = activation.get(thread.id);
    if (cached !== undefined) return cached;
    const [first] = await thread.messages({ full: true, from: "start", limit: 1 }).catch(() => []);
    // NOTE: Fail closed without caching when the first message is not readable yet.
    if (first?.role !== "user" || first.content.length === 0) return true;
    const marked = first.content.some(
      (block) => block.type === "text" && block.text.includes(UNATTENDED_MARKER),
    );
    const parent = marked ? null : await thread.parentThreadID().catch(() => undefined);
    const inherited = parent ? activation.get(parent) : false;
    // NOTE: Unknown parent (lookup failed or other process) fails closed without caching.
    if (parent === undefined || inherited === undefined) return true;
    const active = marked || inherited;
    activation.set(thread.id, active);
    return active;
  }

  amp.on("tool.call", async (event, ctx): Promise<ToolCallResult> => {
    if (!(await isActive(ctx.thread))) return { action: "allow" };
    const reason = await violation(event, ctx.$).catch(
      (error: unknown) => `could not be checked (${String(error)})`,
    );
    if (!reason) return { action: "allow" };
    try {
      const approved = await ctx.ui.confirm({
        title: "Automation guard",
        message: `The agent wants to run \`${event.tool}\`, which ${reason}. Allow it?`,
        confirmButtonText: "Allow",
        requireHuman: true,
        skipIfUnwatched: true,
      });
      if (approved) return { action: "allow" };
    } catch (error) {
      if (!amp.helpers.isPluginUINotAvailableError(error)) throw error;
    }
    return {
      action: "reject-and-continue",
      message: `Automation guard blocked this call: it ${reason}. The thread owner did not approve it. Do not retry it another way; report the blocked step instead.`,
    };
  });

  amp.on("tool.result", async (event, ctx): Promise<ToolResultResult> => {
    if (!(await isActive(ctx.thread))) return;
    if (event.status === "done") return { status: "done", output: sanitize(event.output) };
    return {
      status: event.status,
      error: event.error === undefined ? undefined : clean(event.error),
      output: sanitize(event.output),
    };
  });
}
