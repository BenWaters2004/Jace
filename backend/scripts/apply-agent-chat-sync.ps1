$ErrorActionPreference = "Stop"

# This script is intentionally in backend/scripts because that is where the
# existing Jace maintenance/test scripts live. It patches the current local
# App.tsx in-place instead of replacing the entire 1,200+ line file, so any
# newer local changes are preserved.

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$appPath = Join-Path $repoRoot "apps\desktop\src\App.tsx"

if (-not (Test-Path $appPath)) {
    throw "Could not find App.tsx at $appPath"
}

$content = Get-Content -Raw -Path $appPath
$usedCrLf = $content.Contains("`r`n")
$content = $content.Replace("`r`n", "`n")
$marker = "// 11B.3D: keep completed background-agent handoffs in sync with the open chat."

if ($content.Contains($marker)) {
    Write-Host "App.tsx already contains the 11B.3D agent chat sync fix." -ForegroundColor Green
    exit 0
}

$anchor = @'
  const refreshMemories = useCallback(async () => {
    const response = await getMemories(false);
    setMemories(response.memories);
    return response.memories;
  }, []);
'@

if (-not $content.Contains($anchor)) {
    throw @"
Could not find the expected refreshMemories block in App.tsx.
No changes were made. Your App.tsx has likely changed from the current Jace layout.
"@
}

$insert = @'

  // 11B.3D: keep completed background-agent handoffs in sync with the open chat.
  // The backend persists the specialist result first, then publishes
  // agent.task.completed with the originating conversation/message IDs.
  const activeConversationIdRef = useRef<string | null>(activeConversationId);
  const handledAgentHandoffsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
  }, [activeConversationId]);

  useEffect(() => {
    const event = runtime.lastEvent;
    if (!event || event.type !== "agent.task.completed") return;

    const conversationId = event.conversation_id;
    if (!conversationId) return;

    // React StrictMode can run effects twice in development. Prefer the
    // persisted handoff message ID as the idempotency key, then fall back to
    // task/event identity if an older backend did not send it.
    const handoffKey =
      event.handoff_message_id
      ?? `${event.task_id ?? "agent-task"}:${event.sequence ?? event.timestamp ?? "completed"}`;

    if (handledAgentHandoffsRef.current.has(handoffKey)) return;
    handledAgentHandoffsRef.current.add(handoffKey);

    void (async () => {
      try {
        // Update the drawer/message counts even when the completed task belongs
        // to a conversation that is not currently open.
        await refreshConversations();

        if (activeConversationIdRef.current !== conversationId) return;

        // A specialist only starts once foreground chat becomes idle, but the
        // browser may still be finishing the final stream callbacks. Avoid
        // racing submit()'s own final conversation reload.
        for (let attempt = 0; attempt < 30 && isGeneratingRef.current; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 50));
        }

        if (activeConversationIdRef.current !== conversationId) return;

        const saved = await getConversation(conversationId);

        // The user may have switched chats while the REST request was in flight.
        if (activeConversationIdRef.current !== conversationId) return;

        setMessages(mapMessages(saved));
        setSelectedModel(saved.model);
        setConversationPrompt(saved.system_prompt);

        // Agent completion can also schedule the stricter agent-memory
        // extractor introduced in 11B.3D. Refresh memory shortly afterwards so
        // any accepted durable finding appears without reopening the app.
        window.setTimeout(() => {
          void refreshMemories();
        }, 500);
      } catch (handoffError) {
        // The handoff is already persisted server-side, so this is a display
        // sync failure only. Do not replace the user's chat with a fatal error.
        console.warn("Could not sync completed agent handoff into chat.", handoffError);
      }
    })();
  }, [runtime.lastEvent, refreshConversations, refreshMemories]);
'@

$content = $content.Replace($anchor, $anchor + $insert)
if ($usedCrLf) {
    $content = $content.Replace("`n", "`r`n")
}
Set-Content -Path $appPath -Value $content -Encoding UTF8

Write-Host "Patched apps/desktop/src/App.tsx with live agent handoff chat sync." -ForegroundColor Green
