# Install into Codex, Claude Code, or GitHub Copilot

This repository is both a self-contained plugin and a repository marketplace.
It uses one local Python MCP implementation across clients. No public directory
submission, repository visibility change, or third-party account connection is
performed by the installer.

## Prerequisites and scope

- Local Windows and an existing Python 3.12+ interpreter.
- Classic OrCAD X / Allegro X PCB Editor 25.1 and a suitable local license for
  native operations. These are not bundled or installed.
- A client/version supporting local stdio MCP, image results, and the relevant
  plugin format. Browser-only/cloud environments cannot access this local GUI.
- Marketplace bootstrapping uses the Windows `py -3` launcher. If `py` is not
  installed, the generated direct MCP configurations use an absolute Python
  path and do not need it.
- If the repository is private, each user needs GitHub access and working Git
  credentials. Never put tokens in plugin manifests or configuration samples.

The plugin starts **read-only by default**: inspection, visual proposals,
reference search and recovery are available. The original fixture is the
default native model. Experimental managed-board-v1 is explicitly selected at
staging and is limited to documented unrouted, embedded simple SMT geometry;
it is not arbitrary production-board support. Native acceptance is pending.

## 1. Prepare the runtime once

Clone the trusted repository, then run the Python installer with an explicit
supported interpreter. Do not invoke a legacy Cadence Python by accident.

```powershell
gh repo clone ooyang0325/OrCad-PCB-Review-Agent
Set-Location OrCad-PCB-Review-Agent
& 'C:\path\to\Python3\python.exe' -I -X utf8 scripts\install.py --plan
& 'C:\path\to\Python3\python.exe' -I -X utf8 scripts\install.py --client all
```

If the Windows Python launcher selects a supported interpreter, `py -3`
can replace the explicit interpreter path. Existing developers may use the
repository's `.venv\Scripts\python.exe`.

The installer creates an owned, versioned environment at
`%LOCALAPPDATA%\OrCadPlacementAgent\plugin-envs\0.6.0` and generates client
snippets inside its `client-configs` directory. It does not change PATH,
Python 2.7, execution policy, Cadence settings, existing client configuration,
or any board. Re-running is idempotent for the same installed version; it
refuses to repurpose an unrelated environment or overwrite different snippets.
Use a new version/directory for upgrades, and restart clients deliberately.

PowerShell script execution was restricted on the development machine. These
Python entry points and direct configurations avoid requiring PowerShell
scripts; the installer does not bypass or change that policy.

**PCB expertise is bundled:** the default install includes 36 original rules
and needs no books, index, PDF parser, embedding service or extra model.
Search and full-rule lookup work immediately after MCP registration. Cadence,
design-specific inputs and native human-approval requirements remain separate.

Optional local books can be indexed explicitly (this installs PDF dependencies):

```powershell
& 'C:\path\to\Python3\python.exe' -I -X utf8 scripts\install.py `
    --books 'C:\my-local-reference-books' --client all
```

With `--books`, the optional index is written to
`%LOCALAPPDATA%\OrCadPlacementAgent\knowledge.sqlite3`, and generated direct
configs explicitly select it. Without that flag, setup installs only the
integration dependencies and does not configure or create an index.
No books, extracted passages, screenshots, or board files are distributed.
For marketplace startup, set `OPA_KNOWLEDGE_DB` explicitly if you want this
optional enrichment; it is not auto-discovered. Adding `--books` after a default
installation writes separate snippets to `client-configs-with-books`, preserving
the no-book `client-configs` files. Review and deliberately select the new entry
in your client; existing client settings are never changed automatically.

## 2A. Direct MCP configuration

Use this route if your client lacks plugin support or the `py` launcher is
unavailable. Generated commands use isolated Python mode, so a client project
cannot shadow the installed package with a same-named local module.
Choose one MCP registration route; do not leave a second failing/duplicate
plugin server enabled alongside the direct server.

| Client | Generated file | Where to add the named entry |
|---|---|---|
| Codex CLI/desktop/IDE | `codex-mcp.toml` | User or trusted-project `config.toml`, under `mcp_servers.orcad-placement` |
| Claude Code | `claude-mcp.json` | Claude MCP configuration, or use its `mcp add` command |
| Copilot CLI | `copilot-mcp.json` | Copilot `mcp-config.json`, under `mcpServers` |
| VS Code Copilot | `vscode-mcp.json` | `.vscode\mcp.json` or the user MCP configuration, under `servers` |

Merge **only the named server entry**, not the entire generated file over an
existing configuration. Alternatively, with the installed Python path:

```powershell
codex mcp add orcad-placement -- 'C:\installed-env\Scripts\python.exe' -I -X utf8 -m orcad_placement_agent.mcp_server
claude mcp add --transport stdio --scope local orcad-placement -- 'C:\installed-env\Scripts\python.exe' -I -X utf8 -m orcad_placement_agent.mcp_server
```

No database argument is needed. Add `--knowledge-db <local-index>` only for
optional PDF enrichment; generated files include it only when `--books` was used.
Keep server registration explicit; the installer does not modify global client
settings or delete an existing server with the same name.

Direct MCP installation provides the tools. The shared `skills` directory can
also be installed without a marketplace: copy each complete skill folder into
the selected project's discovery directory, refusing existing same-named
folders rather than overwriting them:

| Client | Project skill directory |
|---|---|
| Codex and Copilot | `.agents\skills` |
| Claude Code | `.claude\skills` |

For example, from this checkout:

```powershell
$destination = 'C:\your-project\.agents\skills'
$names = 'pcb-placement-orchestrate', 'pcb-placement-plan', 'pcb-placement-review', 'pcb-placement-execute'
foreach ($name in $names) {
    if (Test-Path (Join-Path $destination $name)) { throw "Skill already exists: $name" }
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in $names) { Copy-Item (Join-Path 'skills' $name) $destination -Recurse }
```

Restart/reload the client if needed. Copilot recognizes several skill
directories, so avoid installing duplicate copies of the same workflow into
multiple locations. Plugin installation below bundles both skills and MCP.
Existing `.github\agents` profiles are for the
app/project SDK-extension workflow, not a claim of cross-client tool-name parity.

## 2B. Repository marketplace or plugin installation

Prepare the runtime first. Marketplace installation never silently installs
Python dependencies or licenses Cadence on first tool invocation.

### Codex

```powershell
codex plugin marketplace add ooyang0325/OrCad-PCB-Review-Agent --ref main
```

Open `/plugins` in a supported current Codex CLI, or the Plugins directory in
the supported desktop client, choose **OrCAD PCB Tools**, and install
`orcad-placement`. Start a new session. The Codex IDE extension uses direct
MCP configuration rather than plugin installation.

The catalog is `.agents\plugins\marketplace.json`; the portable entry points
are root `plugin.json`, `mcp.json`, and `skills`.

### Claude Code

```powershell
claude plugin marketplace add https://github.com/ooyang0325/OrCad-PCB-Review-Agent.git
claude plugin install orcad-placement@orcad-pcb-tools --scope local
```

For local development:

```powershell
claude plugin validate . --strict
claude --plugin-dir .
```

Claude uses `.claude-plugin\plugin.json` and the inline MCP entry with
`${CLAUDE_PLUGIN_ROOT}`. Its persistent plugin install is marketplace-based;
do not substitute an undocumented `claude plugin install OWNER/REPO` command.

### GitHub Copilot

Direct repository plugin:

```powershell
copilot plugin install ooyang0325/OrCad-PCB-Review-Agent
```

Or choose the marketplace route instead:

```powershell
copilot plugin marketplace add ooyang0325/OrCad-PCB-Review-Agent
copilot plugin install orcad-placement@orcad-pcb-tools
```

Use `copilot plugin list` and `copilot mcp list` to inspect the installation.
Current Copilot supports the portable root manifest and the shared Claude-format
marketplace. Open Plugin Spec support requires a compatible current client
(introduced in CLI 1.0.74). The app's plugin entry point is **Customize > Plugins**;
exact UI fields vary by client.

Do not enable the shared MCP plugin and the existing project SDK extension for
the same workflow simultaneously. The portable bundle does not register the
project `.github\extensions` as an installed plugin extension.

## Shared workflows and approval

The plugin bundles `pcb-placement-orchestrate` above `pcb-placement-plan`,
`pcb-placement-review`, and `pcb-placement-execute`. Use the client's skill picker/slash interface;
namespacing varies. All workflows require examining actual returned PNGs.
The orchestration and execution skills are opt-in, not implicitly invoked.
The coordinator manages intake, batches and routing review, but does not add
raw logical import or routing capabilities. The new mission engine and explicit
managed-board model implement conditional initial placement; see
[the executable workflow](placement-missions.md) and its acceptance limits.

Portable skills guide the client's main agent; they do not remove its other
tools or act as a sandbox. Configure the host's permissions appropriately.
The bounded MCP implementation and its default read-only gate are separate
enforcement, while the existing app-specific agent profiles have their own
explicit tool allowlists.

The MCP tool basenames are stable, but Claude plugin tools are scoped, for
example `mcp__plugin_orcad-placement_orcad-placement__pcb_inspect`.
Discover the host's loaded names; do not copy Claude prefixes into other clients.

**Elicitation support is not proof of human input.** Copilot documents
auto-handling elicitation in Autopilot, and Claude supports auto-answering hooks.
Therefore all shipped launch/configuration paths leave portable writes disabled.
Only an operator may add `--allow-interactive-writes` to server arguments after
ensuring genuine interactive input and disabling auto-answer behavior.
Never enable it through an agent tool call or in unattended/autonomous sessions.
The server still requires the exact phrase, fresh native state, and one-use
approval; these controls do not attest that an untrusted client used a human.

The app-specific SDK extension separately refuses Apply unless its session mode
is `interactive`, checked before and after prompting. It never changes modes
on the user's behalf. Native mutation acceptance remains separately gated.

## Package safely and publish deliberately

For a clean local archive after committing intended changes:

```powershell
& 'C:\path\to\Python3\python.exe' -I scripts\package.py
```

This uses `git archive`, not a recursive copy of the working directory. Use the
clean archive for local distribution. Do not zip or publish a dirty checkout
containing the ignored books, vendor manuals, boards, captures or environments.
Remote Git marketplace installs receive tracked files only.

The marketplace manifests make this repository a catalog; they do **not**
submit it to OpenAI's universal public directory, an official Claude directory,
or another public listing. Packaging does not change repository visibility.
No new open-source
license is assigned here; choose licensing, privacy/terms and publication
requirements deliberately before broader distribution. OpenAI's public MCP
submission path generally expects a remote HTTPS integration; this local
Windows GUI tool must not be exposed remotely just to satisfy that requirement.

## Evidence and limitations

The package's schemas, official SDK protocol/elicitation behavior, PNG results,
wheel assets, isolated non-checkout launch, and generated configuration formats
are exercised locally. Native clients are not installed by these tests, and
client marketplace discovery/UI behavior is not implied by an MCP handshake.
No board move or save is performed by installation or packaging.

References:

- [OpenAI plugin packaging and marketplaces](https://developers.openai.com/plugins/build/plugins)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
- [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude MCP and elicitation](https://code.claude.com/docs/en/mcp)
- [Copilot plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Copilot changelog](https://github.com/github/copilot-cli/blob/main/changelog.md)
- [Agent Plugins 1.0.0 specification](https://agent-plugins.org/specification)
