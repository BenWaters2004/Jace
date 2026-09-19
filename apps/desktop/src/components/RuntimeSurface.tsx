import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";

import {
  closeScopedTerminal,
  getExecutionScopes,
  getProcessOutput,
  getTerminalOutput,
  listProcesses,
  listTerminals,
  openScopedTerminal,
  resizeScopedTerminal,
  sendScopedTerminalInput,
  startScopedProcess,
  terminateScopedProcess,
} from "../api";
import type { ExecutionScope } from "../types";
import type {
  ProcessOutputItem,
  ProcessRuntimeMode,
  ProcessRuntimeRecord,
  ProcessRuntimeShell,
} from "../processRuntimeTypes";
import type {
  TerminalRuntimeRecord,
  TerminalRuntimeShell,
} from "../terminalRuntimeTypes";

type RuntimeTab = "terminal" | "processes";
type RuntimeShell = ProcessRuntimeShell & TerminalRuntimeShell;

const SHELLS: RuntimeShell[] = [
  "powershell",
  "cmd",
  "wsl",
  "bash",
];

const FINAL_PROCESS_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "timed_out",
  "lost",
]);

const FINAL_TERMINAL_STATUSES = new Set([
  "closed",
  "failed",
  "lost",
]);

function normalizeRuntimePath(value: string) {
  return value
    .replace(/\\/g, "/")
    .replace(/\/+/g, "/")
    .replace(/\/$/, "")
    .toLocaleLowerCase();
}

function runtimeBelongsToScope(
  deviceId: string,
  cwd: string | null,
  scope: ExecutionScope,
) {
  if (deviceId !== scope.device_id || !cwd) return false;

  const root = normalizeRuntimePath(scope.device_root_path);
  const runtime = normalizeRuntimePath(cwd);

  return runtime === root || runtime.startsWith(`${root}/`);
}

function shellLabel(shell: string) {
  if (shell === "powershell") return "PowerShell";
  if (shell === "cmd") return "Command Prompt";
  if (shell === "wsl") return "WSL";
  if (shell === "bash") return "Bash";
  return shell;
}

function formatDate(value: string | null) {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.valueOf())) return value;

  return date.toLocaleString();
}

function processOutputText(items: ProcessOutputItem[]) {
  return items
    .map((item) => {
      if (item.stream === "stderr") {
        return `[stderr] ${item.text}`;
      }

      if (item.stream === "system") {
        return `[system] ${item.text}`;
      }

      return item.text;
    })
    .join("");
}

export function RuntimeSurface() {
  const [tab, setTab] = useState<RuntimeTab>("terminal");
  const [scopes, setScopes] = useState<ExecutionScope[]>([]);
  const [selectedScopeId, setSelectedScopeId] = useState("");
  const [terminals, setTerminals] = useState<TerminalRuntimeRecord[]>([]);
  const [processes, setProcesses] = useState<ProcessRuntimeRecord[]>([]);
  const [selectedTerminalId, setSelectedTerminalId] = useState("");
  const [selectedProcessId, setSelectedProcessId] = useState("");
  const [terminalShell, setTerminalShell] =
    useState<RuntimeShell>("powershell");
  const [processShell, setProcessShell] =
    useState<RuntimeShell>("powershell");
  const [terminalCwd, setTerminalCwd] = useState(".");
  const [processCwd, setProcessCwd] = useState(".");
  const [processCommand, setProcessCommand] = useState("");
  const [processMode, setProcessMode] =
    useState<ProcessRuntimeMode>("background");
  const [processTimeout, setProcessTimeout] = useState("120");
  const [processOutput, setProcessOutput] = useState<ProcessOutputItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const terminalHostRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const terminalSequenceRef = useRef(0);
  const processSequenceRef = useRef(0);
  const inputQueueRef = useRef("");
  const inputTimerRef = useRef<number | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const activeTerminalRef = useRef<TerminalRuntimeRecord | null>(null);
  const activeScopeRef = useRef<ExecutionScope | null>(null);

  const selectedScope = useMemo(
    () => scopes.find((scope) => scope.id === selectedScopeId) ?? null,
    [scopes, selectedScopeId],
  );

  const scopedTerminals = useMemo(
    () =>
      selectedScope
        ? terminals.filter((terminal) =>
            runtimeBelongsToScope(
              terminal.device_id,
              terminal.cwd,
              selectedScope,
            ),
          )
        : [],
    [selectedScope, terminals],
  );

  const scopedProcesses = useMemo(
    () =>
      selectedScope
        ? processes.filter((process) =>
            runtimeBelongsToScope(
              process.device_id,
              process.cwd,
              selectedScope,
            ),
          )
        : [],
    [processes, selectedScope],
  );

  const selectedTerminal = useMemo(
    () =>
      scopedTerminals.find(
        (terminal) => terminal.id === selectedTerminalId,
      ) ?? null,
    [scopedTerminals, selectedTerminalId],
  );

  const selectedProcess = useMemo(
    () =>
      scopedProcesses.find(
        (process) => process.id === selectedProcessId,
      ) ?? null,
    [scopedProcesses, selectedProcessId],
  );

  const allowedShells = useMemo(
    () =>
      selectedScope
        ? SHELLS.filter((shell) =>
            selectedScope.allowed_shells.includes(shell),
          )
        : [],
    [selectedScope],
  );

  useEffect(() => {
    activeTerminalRef.current = selectedTerminal;
  }, [selectedTerminal]);

  useEffect(() => {
    activeScopeRef.current = selectedScope;
  }, [selectedScope]);

  const refresh = useCallback(async () => {
    try {
      const [scopeResponse, terminalResponse, processResponse] =
        await Promise.all([
          getExecutionScopes(true),
          listTerminals("limit=200"),
          listProcesses("limit=200"),
        ]);

      setScopes(scopeResponse.scopes);
      setTerminals(terminalResponse.terminals);
      setProcesses(processResponse.processes);

      setSelectedScopeId((current) => {
        if (
          current
          && scopeResponse.scopes.some((scope) => scope.id === current)
        ) {
          return current;
        }

        return scopeResponse.scopes[0]?.id ?? "";
      });
    } catch (refreshError) {
      setError(
        refreshError instanceof Error
          ? refreshError.message
          : "Could not load process/terminal runtime state.",
      );
    }
  }, []);

  useEffect(() => {
    void refresh();

    const timer = window.setInterval(() => {
      void refresh();
    }, 1500);

    return () => {
      window.clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    if (!selectedScope) {
      setSelectedTerminalId("");
      setSelectedProcessId("");
      return;
    }

    const firstShell =
      allowedShells[0] ?? "powershell";

    if (!allowedShells.includes(terminalShell)) {
      setTerminalShell(firstShell);
    }

    if (!allowedShells.includes(processShell)) {
      setProcessShell(firstShell);
    }

    setSelectedTerminalId((current) => {
      if (
        current
        && scopedTerminals.some((terminal) => terminal.id === current)
      ) {
        return current;
      }

      return scopedTerminals[0]?.id ?? "";
    });

    setSelectedProcessId((current) => {
      if (
        current
        && scopedProcesses.some((process) => process.id === current)
      ) {
        return current;
      }

      return scopedProcesses[0]?.id ?? "";
    });
  }, [
    allowedShells,
    processShell,
    scopedProcesses,
    scopedTerminals,
    selectedScope,
    terminalShell,
  ]);

  useEffect(() => {
    const host = terminalHostRef.current;

    if (!host || tab !== "terminal") return;

    const terminal = new Terminal({
      cursorBlink: true,
      convertEol: false,
      scrollback: 10000,
      fontFamily:
        '"Cascadia Mono", "Cascadia Code", Consolas, monospace',
      fontSize: 13,
      theme: {
        background: "#090d12",
        foreground: "#e5e7eb",
        cursor: "#e5e7eb",
      },
    });

    const fitAddon = new FitAddon();

    terminal.loadAddon(fitAddon);
    terminal.open(host);
    fitAddon.fit();
    terminal.focus();

    terminalRef.current = terminal;
    fitAddonRef.current = fitAddon;
    terminalSequenceRef.current = 0;

    const inputSubscription = terminal.onData((data) => {
      const activeTerminal = activeTerminalRef.current;
      const activeScope = activeScopeRef.current;

      if (
        !activeTerminal
        || !activeScope
        || FINAL_TERMINAL_STATUSES.has(activeTerminal.status)
      ) {
        return;
      }

      inputQueueRef.current += data;

      if (inputTimerRef.current !== null) return;

      inputTimerRef.current = window.setTimeout(() => {
        inputTimerRef.current = null;

        const payload = inputQueueRef.current;
        inputQueueRef.current = "";

        if (!payload) return;

        const currentTerminal = activeTerminalRef.current;
        const currentScope = activeScopeRef.current;

        if (!currentTerminal || !currentScope) return;

        void sendScopedTerminalInput(
          currentTerminal.id,
          currentScope.id,
          payload,
        ).catch((inputError: unknown) => {
          setError(
            inputError instanceof Error
              ? inputError.message
              : "Could not write terminal input.",
          );
        });
      }, 18);
    });

    const resizeObserver = new ResizeObserver(() => {
      try {
        fitAddon.fit();
      } catch {
        return;
      }

      const currentTerminal = activeTerminalRef.current;
      const currentScope = activeScopeRef.current;

      if (
        !currentTerminal
        || !currentScope
        || FINAL_TERMINAL_STATUSES.has(currentTerminal.status)
      ) {
        return;
      }

      if (resizeTimerRef.current !== null) {
        window.clearTimeout(resizeTimerRef.current);
      }

      resizeTimerRef.current = window.setTimeout(() => {
        resizeTimerRef.current = null;

        void resizeScopedTerminal(
          currentTerminal.id,
          currentScope.id,
          terminal.cols,
          terminal.rows,
        ).catch(() => {
          // Resize is best-effort; polling will surface terminal failure.
        });
      }, 120);
    });

    resizeObserver.observe(host);

    return () => {
      inputSubscription.dispose();
      resizeObserver.disconnect();

      if (inputTimerRef.current !== null) {
        window.clearTimeout(inputTimerRef.current);
        inputTimerRef.current = null;
      }

      if (resizeTimerRef.current !== null) {
        window.clearTimeout(resizeTimerRef.current);
        resizeTimerRef.current = null;
      }

      terminal.dispose();
      terminalRef.current = null;
      fitAddonRef.current = null;
    };
  }, [tab, selectedTerminalId]);

  useEffect(() => {
    if (
      tab !== "terminal"
      || !selectedTerminal
      || !terminalRef.current
    ) {
      return;
    }

    terminalSequenceRef.current = 0;
    terminalRef.current.reset();

    let cancelled = false;

    async function pollOutput() {
      const terminal = terminalRef.current;

      if (!terminal || cancelled || !selectedTerminal) return;

      try {
        const response = await getTerminalOutput(
          selectedTerminal.id,
          terminalSequenceRef.current,
          2000,
        );

        if (cancelled) return;

        for (const item of response.output) {
          terminal.write(item.text);
        }

        terminalSequenceRef.current = response.next_sequence;
      } catch (outputError) {
        if (!cancelled) {
          setError(
            outputError instanceof Error
              ? outputError.message
              : "Could not read terminal output.",
          );
        }
      }
    }

    void pollOutput();

    const timer = window.setInterval(() => {
      void pollOutput();
    }, FINAL_TERMINAL_STATUSES.has(selectedTerminal.status) ? 1200 : 250);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedTerminal, tab]);

  useEffect(() => {
    processSequenceRef.current = 0;
    setProcessOutput([]);

    if (!selectedProcess) return;

    const selectedProcessIdSnapshot = selectedProcess.id;
    let cancelled = false;

    async function pollProcessOutput() {
      try {
        const response = await getProcessOutput(
          selectedProcessIdSnapshot,
          processSequenceRef.current,
          1000,
        );

        if (cancelled) return;

        if (response.output.length > 0) {
          setProcessOutput((current) => [
            ...current,
            ...response.output,
          ]);
        }

        processSequenceRef.current = response.next_sequence;
      } catch (outputError) {
        if (!cancelled) {
          setError(
            outputError instanceof Error
              ? outputError.message
              : "Could not read process output.",
          );
        }
      }
    }

    void pollProcessOutput();

    const timer = window.setInterval(() => {
      void pollProcessOutput();
    }, FINAL_PROCESS_STATUSES.has(selectedProcess.status) ? 1500 : 500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedProcess]);

  async function createTerminal() {
    if (!selectedScope) return;

    setBusy(true);
    setError(null);

    try {
      const result = await openScopedTerminal({
        scope_id: selectedScope.id,
        shell: terminalShell,
        relative_cwd: terminalCwd || ".",
        cols: terminalRef.current?.cols ?? 120,
        rows: terminalRef.current?.rows ?? 30,
      });

      await refresh();
      setSelectedTerminalId(result.terminal.id);
      setTab("terminal");
    } catch (openError) {
      setError(
        openError instanceof Error
          ? openError.message
          : "Could not open terminal.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function closeTerminal(force: boolean) {
    if (!selectedScope || !selectedTerminal) return;

    setBusy(true);
    setError(null);

    try {
      await closeScopedTerminal(
        selectedTerminal.id,
        selectedScope.id,
        force,
      );

      await refresh();
    } catch (closeError) {
      setError(
        closeError instanceof Error
          ? closeError.message
          : "Could not close terminal.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function createProcess() {
    if (!selectedScope || !processCommand.trim()) return;

    const timeout = Number.parseInt(processTimeout, 10);

    setBusy(true);
    setError(null);

    try {
      const result = await startScopedProcess({
        scope_id: selectedScope.id,
        shell: processShell,
        command: processCommand,
        relative_cwd: processCwd || ".",
        mode: processMode,
        timeout_seconds:
          Number.isFinite(timeout) && timeout > 0
            ? timeout
            : 120,
      });

      setProcessCommand("");
      await refresh();
      setSelectedProcessId(result.process.id);
      setTab("processes");
    } catch (processError) {
      setError(
        processError instanceof Error
          ? processError.message
          : "Could not start process.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function stopProcess(force: boolean) {
    if (!selectedScope || !selectedProcess) return;

    setBusy(true);
    setError(null);

    try {
      await terminateScopedProcess(
        selectedProcess.id,
        selectedScope.id,
        force,
      );

      await refresh();
    } catch (processError) {
      setError(
        processError instanceof Error
          ? processError.message
          : "Could not terminate process.",
      );
    } finally {
      setBusy(false);
    }
  }

  const scopeReady =
    Boolean(selectedScope)
    && allowedShells.length > 0;

  return (
    <section className="runtime-surface">
      <header className="runtime-surface-header">
        <div>
          <span className="section-kicker">4B.3F · Device runtime</span>
          <h2>Terminal & processes</h2>
          <p>
            Interactive execution is always launched through an active
            Execution Scope. The Device Agent remains the runtime authority.
          </p>
        </div>

        <button
          type="button"
          className="secondary-button"
          onClick={() => void refresh()}
        >
          Refresh
        </button>
      </header>

      <div className="runtime-scope-bar">
        <label>
          <span>Execution scope</span>
          <select
            value={selectedScopeId}
            onChange={(event) => {
              setSelectedScopeId(event.target.value);
              setSelectedTerminalId("");
              setSelectedProcessId("");
            }}
          >
            {scopes.length === 0 && (
              <option value="">No active execution scopes</option>
            )}
            {scopes.map((scope) => (
              <option key={scope.id} value={scope.id}>
                {scope.label}
              </option>
            ))}
          </select>
        </label>

        {selectedScope && (
          <div className="runtime-scope-context">
            <strong>{selectedScope.label}</strong>
            <code>{selectedScope.device_root_path}</code>
            <span>
              {allowedShells.map(shellLabel).join(" · ")}
            </span>
            <span>
              Process {selectedScope.process_enabled ? "✓" : "×"}
              {" · "}
              Terminal {selectedScope.terminal_enabled ? "✓" : "×"}
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="runtime-surface-error">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}

      {!scopeReady ? (
        <div className="runtime-surface-empty">
          Configure an active Execution Scope with at least one allowed shell
          before using the runtime surface.
        </div>
      ) : (
        <>
          <div className="runtime-mode-tabs">
            <button
              type="button"
              className={tab === "terminal" ? "active" : ""}
              onClick={() => setTab("terminal")}
            >
              Terminal
              <span>{scopedTerminals.length}</span>
            </button>
            <button
              type="button"
              className={tab === "processes" ? "active" : ""}
              onClick={() => setTab("processes")}
            >
              Processes
              <span>{scopedProcesses.length}</span>
            </button>
          </div>

          {tab === "terminal" ? (
            <div className="runtime-terminal-layout">
              <aside className="runtime-runtime-list">
                <div className="runtime-create-card">
                  <strong>New terminal</strong>

                  <label>
                    <span>Shell</span>
                    <select
                      value={terminalShell}
                      onChange={(event) =>
                        setTerminalShell(
                          event.target.value as RuntimeShell,
                        )
                      }
                    >
                      {allowedShells.map((shell) => (
                        <option key={shell} value={shell}>
                          {shellLabel(shell)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    <span>Relative directory</span>
                    <input
                      value={terminalCwd}
                      onChange={(event) =>
                        setTerminalCwd(event.target.value)
                      }
                      placeholder="."
                    />
                  </label>

                  <button
                    type="button"
                    className="primary-button"
                    disabled={
                      busy
                      || !selectedScope?.terminal_enabled
                    }
                    onClick={() => void createTerminal()}
                  >
                    Open terminal
                  </button>
                </div>

                <div className="runtime-list-scroll">
                  {scopedTerminals.length === 0 ? (
                    <div className="runtime-list-empty">
                      No terminal sessions in this scope.
                    </div>
                  ) : (
                    scopedTerminals.map((terminal) => (
                      <button
                        type="button"
                        key={terminal.id}
                        className={
                          selectedTerminalId === terminal.id
                            ? "runtime-list-item active"
                            : "runtime-list-item"
                        }
                        onClick={() =>
                          setSelectedTerminalId(terminal.id)
                        }
                      >
                        <strong>
                          {shellLabel(terminal.shell)}
                        </strong>
                        <span>{terminal.status}</span>
                        <small>
                          PID {terminal.pid ?? "—"} ·{" "}
                          {formatDate(terminal.started_at)}
                        </small>
                      </button>
                    ))
                  )}
                </div>
              </aside>

              <section className="runtime-terminal-panel">
                <header className="runtime-panel-head">
                  <div>
                    <strong>
                      {selectedTerminal
                        ? `${shellLabel(selectedTerminal.shell)} · ${selectedTerminal.status}`
                        : "No terminal selected"}
                    </strong>
                    <span>
                      {selectedTerminal?.cwd ?? selectedScope?.device_root_path}
                    </span>
                  </div>

                  {selectedTerminal && (
                    <div className="runtime-panel-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={
                          busy
                          || FINAL_TERMINAL_STATUSES.has(
                            selectedTerminal.status,
                          )
                        }
                        onClick={() => void closeTerminal(false)}
                      >
                        Close
                      </button>
                      <button
                        type="button"
                        className="danger-button"
                        disabled={
                          busy
                          || FINAL_TERMINAL_STATUSES.has(
                            selectedTerminal.status,
                          )
                        }
                        onClick={() => void closeTerminal(true)}
                      >
                        Kill
                      </button>
                    </div>
                  )}
                </header>

                <div
                  ref={terminalHostRef}
                  className="runtime-terminal-host"
                  aria-label="Interactive terminal"
                />

                {!selectedTerminal && (
                  <div className="runtime-terminal-overlay">
                    Open or select a terminal session.
                  </div>
                )}

                {selectedTerminal?.output_truncated && (
                  <div className="runtime-truncation-warning">
                    Older terminal output was truncated by the configured
                    scrollback limit.
                  </div>
                )}
              </section>
            </div>
          ) : (
            <div className="runtime-process-layout">
              <aside className="runtime-runtime-list">
                <form
                  className="runtime-create-card"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void createProcess();
                  }}
                >
                  <strong>Run command</strong>

                  <label>
                    <span>Shell</span>
                    <select
                      value={processShell}
                      onChange={(event) =>
                        setProcessShell(
                          event.target.value as RuntimeShell,
                        )
                      }
                    >
                      {allowedShells.map((shell) => (
                        <option key={shell} value={shell}>
                          {shellLabel(shell)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    <span>Relative directory</span>
                    <input
                      value={processCwd}
                      onChange={(event) =>
                        setProcessCwd(event.target.value)
                      }
                      placeholder="."
                    />
                  </label>

                  <label>
                    <span>Command</span>
                    <textarea
                      rows={4}
                      value={processCommand}
                      onChange={(event) =>
                        setProcessCommand(event.target.value)
                      }
                      placeholder='Write-Output "Hello from Jace"'
                    />
                  </label>

                  <div className="runtime-create-row">
                    <label>
                      <span>Mode</span>
                      <select
                        value={processMode}
                        onChange={(event) =>
                          setProcessMode(
                            event.target.value as ProcessRuntimeMode,
                          )
                        }
                      >
                        <option value="background">Background</option>
                        <option value="foreground">Foreground</option>
                      </select>
                    </label>

                    <label>
                      <span>Timeout (s)</span>
                      <input
                        type="number"
                        min={1}
                        max={86400}
                        value={processTimeout}
                        onChange={(event) =>
                          setProcessTimeout(event.target.value)
                        }
                      />
                    </label>
                  </div>

                  <div className="runtime-direct-action-note">
                    Clicking Run is an explicit user action within the selected
                    scope. Agent-driven commands still use the separate
                    approval policy from 4B.3D.
                  </div>

                  <button
                    type="submit"
                    className="primary-button"
                    disabled={
                      busy
                      || !selectedScope?.process_enabled
                      || !processCommand.trim()
                    }
                  >
                    Run command
                  </button>
                </form>

                <div className="runtime-list-scroll">
                  {scopedProcesses.length === 0 ? (
                    <div className="runtime-list-empty">
                      No process history in this scope.
                    </div>
                  ) : (
                    scopedProcesses.map((process) => (
                      <button
                        type="button"
                        key={process.id}
                        className={
                          selectedProcessId === process.id
                            ? "runtime-list-item active"
                            : "runtime-list-item"
                        }
                        onClick={() =>
                          setSelectedProcessId(process.id)
                        }
                      >
                        <strong>{process.command_preview}</strong>
                        <span>{process.status}</span>
                        <small>
                          {shellLabel(process.shell)} · PID{" "}
                          {process.pid ?? "—"}
                        </small>
                      </button>
                    ))
                  )}
                </div>
              </aside>

              <section className="runtime-process-panel">
                <header className="runtime-panel-head">
                  <div>
                    <strong>
                      {selectedProcess?.command_preview ?? "No process selected"}
                    </strong>
                    <span>
                      {selectedProcess
                        ? `${selectedProcess.shell} · ${selectedProcess.status} · exit ${selectedProcess.exit_code ?? "—"}`
                        : selectedScope?.device_root_path}
                    </span>
                  </div>

                  {selectedProcess && (
                    <div className="runtime-panel-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={
                          busy
                          || FINAL_PROCESS_STATUSES.has(
                            selectedProcess.status,
                          )
                        }
                        onClick={() => void stopProcess(false)}
                      >
                        Stop
                      </button>
                      <button
                        type="button"
                        className="danger-button"
                        disabled={
                          busy
                          || FINAL_PROCESS_STATUSES.has(
                            selectedProcess.status,
                          )
                        }
                        onClick={() => void stopProcess(true)}
                      >
                        Force stop
                      </button>
                    </div>
                  )}
                </header>

                <pre className="runtime-process-output">
                  {selectedProcess
                    ? processOutputText(processOutput)
                      || "No output yet."
                    : "Select a process to inspect durable output."}
                </pre>

                {selectedProcess && (
                  <footer className="runtime-process-meta">
                    <span>Started {formatDate(selectedProcess.started_at)}</span>
                    <span>
                      Completed {formatDate(selectedProcess.completed_at)}
                    </span>
                    <span>
                      {selectedProcess.output_bytes.toLocaleString()} output bytes
                    </span>
                    {selectedProcess.output_truncated && (
                      <strong>Output truncated</strong>
                    )}
                  </footer>
                )}
              </section>
            </div>
          )}
        </>
      )}
    </section>
  );
}
