import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  FormEvent,
  KeyboardEvent,
} from "react";

import {
  createConversation,
  deleteConversation,
  getConversation,
  getConversations,
  getHealth,
  getModels,
  sendChatStream,
  updateConversation,
} from "./api";

import type {
  ApiGenerationStats,
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  GenerationStats,
  ModelInfo,
  StreamDoneEvent,
} from "./types";

import "./styles.css";


type ConnectionState =
  | "checking"
  | "online"
  | "backend-offline"
  | "ollama-offline";


const DEFAULT_SYSTEM_PROMPT = `You are Jace, a personal AI assistant running locally on the user's computer.

Your role:
- Help the user think, research, create, solve problems and manage information.
- Be useful, accurate and clear.
- Prefer practical answers over unnecessary verbosity.
- Clearly distinguish known facts from assumptions or uncertainty.
- Do not claim to have performed actions that you have not actually performed.
- Do not claim to have access to tools, files, memory, websites or services unless they have actually been provided to you.
- Respect the user's privacy and control over their data.

You are the beginning of a larger personal AI system. Your capabilities will expand over time through explicitly provided tools and memory.`;


function createLocalMessage(
  role:
    "user" | "assistant",
  content: string,
): ChatMessage {
  return {
    id:
      crypto.randomUUID(),

    role,
    content,
  };
}


function mapStats(
  stats:
    ApiGenerationStats | null,
):
GenerationStats | undefined {
  if (!stats) {
    return undefined;
  }

  return {
    timeToFirstTokenMs:
      stats.time_to_first_token_ms,

    totalDurationMs:
      stats.total_duration_ms,

    loadDurationMs:
      stats.load_duration_ms,

    promptEvalCount:
      stats.prompt_eval_count,

    promptEvalCachedCount:
      stats.prompt_eval_cached_count,

    promptEvalDurationMs:
      stats.prompt_eval_duration_ms,

    evalCount:
      stats.eval_count,

    evalDurationMs:
      stats.eval_duration_ms,

    tokensPerSecond:
      stats.tokens_per_second,
  };
}


function mapConversationMessages(
  conversation:
    ConversationDetail,
): ChatMessage[] {
  return (
    conversation.messages.map(
      (message) => ({
        id:
          message.id,

        conversation_id:
          message.conversation_id,

        role:
          message.role,

        content:
          message.content,

        status:
          message.status,

        model:
          message.model,

        created_at:
          message.created_at,

        stopped:
          message.status
          === "stopped",

        stats:
          mapStats(
            message.stats
          ),
      })
    )
  );
}


function formatBytes(
  bytes:
    number | null,
): string {
  if (!bytes) {
    return "";
  }

  const gigabytes =
    bytes /
    1024 /
    1024 /
    1024;

  return (
    `${gigabytes.toFixed(1)} GB`
  );
}


function formatDuration(
  milliseconds:
    number | null,
): string {
  if (
    milliseconds === null
    ||
    milliseconds === undefined
  ) {
    return "—";
  }

  if (
    milliseconds < 1000
  ) {
    return (
      `${Math.round(
        milliseconds
      )} ms`
    );
  }

  return (
    `${(
      milliseconds / 1000
    ).toFixed(1)} s`
  );
}


function formatConversationDate(
  date: string,
): string {
  const value =
    new Date(date);

  const today =
    new Date();

  if (
    value.toDateString()
    === today.toDateString()
  ) {
    return value.toLocaleTimeString(
      [],
      {
        hour: "2-digit",
        minute: "2-digit",
      }
    );
  }

  return value.toLocaleDateString(
    [],
    {
      day: "2-digit",
      month: "short",
    }
  );
}


function App() {
  const [
    messages,
    setMessages,
  ] =
    useState<ChatMessage[]>(
      []
    );

  const [
    input,
    setInput,
  ] =
    useState("");

  const [
    models,
    setModels,
  ] =
    useState<ModelInfo[]>(
      []
    );

  const [
    selectedModel,
    setSelectedModel,
  ] =
    useState("");

  const [
    defaultModel,
    setDefaultModel,
  ] =
    useState("");

  const [
    systemPrompt,
    setSystemPrompt,
  ] =
    useState(
      DEFAULT_SYSTEM_PROMPT
    );

  const [
    conversations,
    setConversations,
  ] =
    useState<
      ConversationSummary[]
    >([]);

  const [
    activeConversationId,
    setActiveConversationId,
  ] =
    useState<
      string | null
    >(null);

  const [
    search,
    setSearch,
  ] =
    useState("");

  const [
    connectionState,
    setConnectionState,
  ] =
    useState<ConnectionState>(
      "checking"
    );

  const [
    error,
    setError,
  ] =
    useState<
      string | null
    >(null);

  const [
    isGenerating,
    setIsGenerating,
  ] =
    useState(false);


  const messagesEndRef =
    useRef<
      HTMLDivElement | null
    >(null);

  const inputRef =
    useRef<
      HTMLTextAreaElement | null
    >(null);

  const abortControllerRef =
    useRef<
      AbortController | null
    >(null);


  const filteredConversations =
    useMemo(
      () => {
        const value =
          search
            .trim()
            .toLowerCase();

        if (!value) {
          return conversations;
        }

        return conversations.filter(
          (conversation) =>
            conversation.title
              .toLowerCase()
              .includes(value)
        );
      },
      [
        conversations,
        search,
      ]
    );


  const refreshConversations =
    useCallback(
      async () => {
        const response =
          await getConversations();

        setConversations(
          response.conversations
        );

        return (
          response.conversations
        );
      },
      []
    );


  const loadConversation =
    useCallback(
      async (
        conversationId: string,
      ) => {
        try {
          const conversation =
            await getConversation(
              conversationId
            );

          setActiveConversationId(
            conversation.id
          );

          setMessages(
            mapConversationMessages(
              conversation
            )
          );

          setSystemPrompt(
            conversation.system_prompt
            ||
            DEFAULT_SYSTEM_PROMPT
          );

          setSelectedModel(
            conversation.model
          );

          setError(null);
        } catch (
          loadError
        ) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "Could not load conversation."
          );
        }
      },
      []
    );


  const initialise =
    useCallback(
      async () => {
        setConnectionState(
          "checking"
        );

        try {
          const [
            health,
            modelResponse,
            conversationResponse,
          ] =
            await Promise.all([
              getHealth(),
              getModels(),
              getConversations(),
            ]);


          if (
            !health.ollama_connected
          ) {
            setConnectionState(
              "ollama-offline"
            );

            return;
          }


          setModels(
            modelResponse.models
          );

          setDefaultModel(
            health.default_model
          );

          setSelectedModel(
            health.default_model
          );

          setConversations(
            conversationResponse
              .conversations
          );

          setConnectionState(
            "online"
          );


          if (
            conversationResponse
              .conversations
              .length > 0
          ) {
            await loadConversation(
              conversationResponse
                .conversations[0]
                .id
            );
          }
        } catch (
          initialiseError
        ) {
          setConnectionState(
            "backend-offline"
          );

          setError(
            initialiseError
              instanceof Error
              ? initialiseError
                  .message
              : "Could not initialise Jace."
          );
        }
      },
      [
        loadConversation,
      ]
    );


  useEffect(() => {
    void initialise();
  }, [
    initialise,
  ]);


  useEffect(() => {
    messagesEndRef.current
      ?.scrollIntoView({
        behavior:
          "smooth",
      });
  }, [
    messages,
  ]);


  async function ensureConversation():
  Promise<string> {
    if (
      activeConversationId
    ) {
      return (
        activeConversationId
      );
    }

    const conversation =
      await createConversation(
        {
          model:
            selectedModel,

          system_prompt:
            systemPrompt,
        }
      );

    setActiveConversationId(
      conversation.id
    );

    await refreshConversations();

    return conversation.id;
  }


  function updateAssistantMessage(
    assistantId: string,
    updater: (
      message: ChatMessage,
    ) => ChatMessage,
  ) {
    setMessages(
      (currentMessages) =>
        currentMessages.map(
          (message) =>
            message.id ===
            assistantId
              ? updater(
                  message
                )
              : message
        )
    );
  }


  async function handleSubmit(
    event?:
      FormEvent<HTMLFormElement>,
  ) {
    event?.preventDefault();

    const text =
      input.trim();

    if (
      !text
      ||
      isGenerating
      ||
      connectionState
        !== "online"
      ||
      !selectedModel
    ) {
      return;
    }


    let conversationId:
      string;

    try {
      conversationId =
        await ensureConversation();
    } catch (
      conversationError
    ) {
      setError(
        conversationError
          instanceof Error
          ? conversationError
              .message
          : "Could not create conversation."
      );

      return;
    }


    const userMessage =
      createLocalMessage(
        "user",
        text
      );

    const assistantMessage:
      ChatMessage = {
        ...createLocalMessage(
          "assistant",
          ""
        ),

        isStreaming:
          true,
      };


    setMessages(
      (current) => [
        ...current,
        userMessage,
        assistantMessage,
      ]
    );

    setInput("");

    setError(null);

    setIsGenerating(
      true
    );


    const controller =
      new AbortController();

    abortControllerRef.current =
      controller;


    try {
      await sendChatStream(
        {
          conversation_id:
            conversationId,

          message:
            text,

          model:
            selectedModel,

          system_prompt:
            systemPrompt,
        },

        {
          onToken:
            (content) => {
              updateAssistantMessage(
                assistantMessage.id,

                (message) => ({
                  ...message,

                  content:
                    message.content
                    + content,
                })
              );
            },


          onDone:
            (
              event:
                StreamDoneEvent,
            ) => {
              updateAssistantMessage(
                assistantMessage.id,

                (message) => ({
                  ...message,

                  isStreaming:
                    false,

                  stats: {
                    timeToFirstTokenMs:
                      event.metrics
                        .time_to_first_token_ms,

                    totalDurationMs:
                      event.metrics
                        .total_duration_ms,

                    loadDurationMs:
                      event.metrics
                        .load_duration_ms,

                    promptEvalCount:
                      event.metrics
                        .prompt_eval_count,

                    promptEvalCachedCount:
                      event.metrics
                        .prompt_eval_cached_count,

                    promptEvalDurationMs:
                      event.metrics
                        .prompt_eval_duration_ms,

                    evalCount:
                      event.metrics
                        .eval_count,

                    evalDurationMs:
                      event.metrics
                        .eval_duration_ms,

                    tokensPerSecond:
                      event.metrics
                        .tokens_per_second,
                  },
                })
              );
            },
        },

        controller.signal
      );


      await refreshConversations();

      await loadConversation(
        conversationId
      );
    } catch (
      chatError
    ) {
      if (
        controller.signal
          .aborted
      ) {
        updateAssistantMessage(
          assistantMessage.id,

          (message) => ({
            ...message,

            isStreaming:
              false,

            stopped:
              true,
          })
        );

        await refreshConversations();
      } else {
        updateAssistantMessage(
          assistantMessage.id,

          (message) => ({
            ...message,

            isStreaming:
              false,
          })
        );

        setError(
          chatError
            instanceof Error
            ? chatError.message
            : "Jace could not generate a response."
        );
      }
    } finally {
      abortControllerRef.current =
        null;

      setIsGenerating(
        false
      );
    }
  }


  function stopGeneration() {
    abortControllerRef.current
      ?.abort();
  }


  function handleKeyDown(
    event:
      KeyboardEvent<
        HTMLTextAreaElement
      >,
  ) {
    if (
      event.key === "Enter"
      &&
      !event.shiftKey
    ) {
      event.preventDefault();

      void handleSubmit();
    }
  }


  function handleNewChat() {
    if (isGenerating) {
      return;
    }

    setActiveConversationId(
      null
    );

    setMessages([]);

    setInput("");

    setSearch("");

    setSystemPrompt(
      DEFAULT_SYSTEM_PROMPT
    );

    setSelectedModel(
      defaultModel
      ||
      models[0]?.name
      ||
      ""
    );

    setError(null);

    window.setTimeout(
      () =>
        inputRef.current
          ?.focus(),
      0
    );
  }


  async function handleRename(
    conversation:
      ConversationSummary,
  ) {
    if (isGenerating) {
      return;
    }

    const title =
      window.prompt(
        "Rename conversation",
        conversation.title
      );

    if (
      title === null
      ||
      !title.trim()
    ) {
      return;
    }

    try {
      await updateConversation(
        conversation.id,
        {
          title:
            title.trim(),
        }
      );

      await refreshConversations();
    } catch (
      renameError
    ) {
      setError(
        renameError
          instanceof Error
          ? renameError.message
          : "Could not rename conversation."
      );
    }
  }


  async function handleDelete(
    conversation:
      ConversationSummary,
  ) {
    if (isGenerating) {
      return;
    }

    const confirmed =
      window.confirm(
        `Delete "${conversation.title}"?`
      );

    if (!confirmed) {
      return;
    }

    try {
      await deleteConversation(
        conversation.id
      );

      const remaining =
        await refreshConversations();


      if (
        activeConversationId
        === conversation.id
      ) {
        if (
          remaining.length
          > 0
        ) {
          await loadConversation(
            remaining[0].id
          );
        } else {
          handleNewChat();
        }
      }
    } catch (
      deleteError
    ) {
      setError(
        deleteError
          instanceof Error
          ? deleteError.message
          : "Could not delete conversation."
      );
    }
  }


  async function handleModelChange(
    model: string,
  ) {
    setSelectedModel(
      model
    );

    if (
      !activeConversationId
    ) {
      return;
    }

    try {
      await updateConversation(
        activeConversationId,
        {
          model,
        }
      );

      await refreshConversations();
    } catch (
      updateError
    ) {
      setError(
        updateError
          instanceof Error
          ? updateError.message
          : "Could not update model."
      );
    }
  }


  async function saveSystemPrompt() {
    if (
      !activeConversationId
    ) {
      return;
    }

    try {
      await updateConversation(
        activeConversationId,
        {
          system_prompt:
            systemPrompt,
        }
      );
    } catch (
      updateError
    ) {
      setError(
        updateError
          instanceof Error
          ? updateError.message
          : "Could not save Jace identity."
      );
    }
  }


  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            J
          </div>

          <div>
            <div className="brand-name">
              Jace
            </div>

            <div className="brand-version">
              v0.2.0
            </div>
          </div>
        </div>


        <button
          className="new-chat-button"
          onClick={
            handleNewChat
          }
          disabled={
            isGenerating
          }
        >
          <span className="new-chat-icon">
            +
          </span>

          New chat
        </button>


        <div className="conversation-search">
          <input
            type="text"
            placeholder="Search conversations..."
            value={
              search
            }
            onChange={
              (event) =>
                setSearch(
                  event.target.value
                )
            }
          />
        </div>


        <div className="sidebar-section conversation-section">
          <span className="sidebar-heading">
            Conversations
          </span>

          <div className="conversation-list">
            {filteredConversations
              .length === 0 ? (
              <div className="empty-history">
                <p>
                  No conversations
                  yet.
                </p>

                <small>
                  Start talking to
                  Jace to create one.
                </small>
              </div>
            ) : (
              filteredConversations.map(
                (conversation) => (
                  <div
                    key={
                      conversation.id
                    }
                    className={
                      "conversation-row"
                      +
                      (
                        activeConversationId
                        === conversation.id
                          ? " active"
                          : ""
                      )
                    }
                  >
                    <button
                      className="conversation-select"
                      onClick={
                        () =>
                          void loadConversation(
                            conversation.id
                          )
                      }
                      disabled={
                        isGenerating
                      }
                    >
                      <span className="conversation-title">
                        {
                          conversation.title
                        }
                      </span>

                      <span className="conversation-meta">
                        {
                          conversation.message_count
                        }{" "}
                        messages ·{" "}
                        {
                          formatConversationDate(
                            conversation.updated_at
                          )
                        }
                      </span>
                    </button>

                    <div className="conversation-actions">
                      <button
                        title="Rename"
                        onClick={
                          () =>
                            void handleRename(
                              conversation
                            )
                        }
                      >
                        ✎
                      </button>

                      <button
                        title="Delete"
                        onClick={
                          () =>
                            void handleDelete(
                              conversation
                            )
                        }
                      >
                        ×
                      </button>
                    </div>
                  </div>
                )
              )
            )}
          </div>
        </div>


        <div className="sidebar-spacer" />


        <div className="settings-panel">
          <label className="field-label">
            Model
          </label>

          <select
            className="model-select"
            value={
              selectedModel
            }
            disabled={
              isGenerating
            }
            onChange={
              (event) =>
                void handleModelChange(
                  event.target.value
                )
            }
          >
            {models.map(
              (model) => (
                <option
                  key={
                    model.name
                  }
                  value={
                    model.name
                  }
                >
                  {
                    model.name
                  }

                  {model.parameter_size
                    ? ` · ${model.parameter_size}`
                    : ""}
                </option>
              )
            )}
          </select>


          {selectedModel && (
            <div className="model-meta">
              {(() => {
                const model =
                  models.find(
                    (item) =>
                      item.name
                      === selectedModel
                  );

                if (!model) {
                  return null;
                }

                return (
                  <>
                    {model.size && (
                      <span>
                        {
                          formatBytes(
                            model.size
                          )
                        }
                      </span>
                    )}

                    {model.quantization_level && (
                      <span>
                        {
                          model.quantization_level
                        }
                      </span>
                    )}
                  </>
                );
              })()}
            </div>
          )}


          <details className="advanced-settings">
            <summary>
              Jace identity
            </summary>

            <div className="advanced-settings-body">
              <label className="field-label">
                System prompt
              </label>

              <textarea
                className="system-prompt"
                value={
                  systemPrompt
                }
                onChange={
                  (event) =>
                    setSystemPrompt(
                      event.target.value
                    )
                }
                onBlur={
                  () =>
                    void saveSystemPrompt()
                }
                disabled={
                  isGenerating
                }
              />

              <button
                className="reset-prompt-button"
                onClick={
                  () => {
                    setSystemPrompt(
                      DEFAULT_SYSTEM_PROMPT
                    );
                  }
                }
              >
                Reset prompt
              </button>
            </div>
          </details>
        </div>


        <div className="connection-card">
          <div
            className={
              `status-dot ${connectionState}`
            }
          />

          <div className="connection-copy">
            <strong>
              {connectionState
              === "online"
                ? "Local AI online"
                : "Jace unavailable"}
            </strong>

            <span>
              Private · local
            </span>
          </div>
        </div>
      </aside>


      <section className="chat-panel">
        <header className="topbar">
          <div>
            <h1>
              {activeConversationId
                ? (
                    conversations.find(
                      (item) =>
                        item.id
                        === activeConversationId
                    )?.title
                    ?? "Jace"
                  )
                : "New conversation"}
            </h1>

            <p>
              Running entirely
              on this computer
            </p>
          </div>

          <div className="local-badge">
            <span className="local-badge-dot" />

            Local
          </div>
        </header>


        <div className="conversation">
          {messages.length
          === 0 ? (
            <div className="welcome">
              <div className="welcome-logo">
                J
              </div>

              <h2>
                How can I help?
              </h2>

              <p>
                Conversations are now
                stored locally and will
                remain available after
                Jace is restarted.
              </p>

              <div className="suggestion-grid">
                <button
                  onClick={
                    () =>
                      setInput(
                        "Explain what capabilities you currently have."
                      )
                  }
                >
                  <span>
                    Capabilities
                  </span>

                  What can you do?
                </button>

                <button
                  onClick={
                    () =>
                      setInput(
                        "Help me plan the next stages of Project Jace."
                      )
                  }
                >
                  <span>
                    Planning
                  </span>

                  Plan Project Jace
                </button>

                <button
                  onClick={
                    () =>
                      setInput(
                        "Explain how your current architecture works."
                      )
                  }
                >
                  <span>
                    Architecture
                  </span>

                  Explain Jace
                </button>
              </div>
            </div>
          ) : (
            <div className="messages">
              {messages.map(
                (message) => (
                  <article
                    key={
                      message.id
                    }
                    className={
                      `message ${message.role}`
                      +
                      (
                        message.isStreaming
                          ? " streaming"
                          : ""
                      )
                    }
                  >
                    <div className="message-avatar">
                      {message.role
                      === "user"
                        ? "B"
                        : "J"}
                    </div>

                    <div className="message-body">
                      <div className="message-author">
                        {message.role
                        === "user"
                          ? "You"
                          : "Jace"}
                      </div>

                      <div className="message-content">
                        {
                          message.content
                        }
                      </div>


                      {message.stopped && (
                        <div className="generation-stats">
                          <span className="generation-stopped">
                            ■ Stopped
                          </span>
                        </div>
                      )}


                      {message.stats && (
                        <div className="generation-stats">
                          {message.stats
                            .tokensPerSecond
                            !== null && (
                            <span>
                              {
                                message.stats
                                  .tokensPerSecond
                                  .toFixed(1)
                              }{" "}
                              tok/s
                            </span>
                          )}

                          {message.stats
                            .timeToFirstTokenMs
                            !== null && (
                            <span>
                              First token{" "}
                              {
                                formatDuration(
                                  message.stats
                                    .timeToFirstTokenMs
                                )
                              }
                            </span>
                          )}

                          {message.stats
                            .evalCount
                            !== null && (
                            <span>
                              {
                                message.stats
                                  .evalCount
                              }{" "}
                              output tokens
                            </span>
                          )}

                          {message.stats
                            .promptEvalCount
                            !== null && (
                            <span>
                              {
                                message.stats
                                  .promptEvalCount
                              }{" "}
                              prompt tokens
                            </span>
                          )}

                          {message.stats
                            .totalDurationMs
                            !== null && (
                            <span>
                              Total{" "}
                              {
                                formatDuration(
                                  message.stats
                                    .totalDurationMs
                                )
                              }
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </article>
                )
              )}

              <div
                ref={
                  messagesEndRef
                }
              />
            </div>
          )}
        </div>


        <div className="composer-area">
          {error && (
            <div className="error-banner">
              <span>
                !
              </span>

              <div>
                <strong>
                  Jace encountered
                  a problem
                </strong>

                <p>
                  {error}
                </p>
              </div>

              <button
                onClick={
                  () =>
                    setError(
                      null
                    )
                }
              >
                ×
              </button>
            </div>
          )}


          <form
            className="composer"
            onSubmit={
              handleSubmit
            }
          >
            <textarea
              ref={
                inputRef
              }
              value={
                input
              }
              onChange={
                (event) =>
                  setInput(
                    event.target.value
                  )
              }
              onKeyDown={
                handleKeyDown
              }
              placeholder={
                isGenerating
                  ? "Jace is responding..."
                  : "Message Jace..."
              }
              disabled={
                connectionState
                !== "online"
                ||
                isGenerating
              }
              rows={1}
            />


            {isGenerating ? (
              <button
                type="button"
                className="stop-button"
                onClick={
                  stopGeneration
                }
                title="Stop generating"
              >
                <span />
              </button>
            ) : (
              <button
                type="submit"
                className="send-button"
                disabled={
                  !input.trim()
                  ||
                  !selectedModel
                }
              >
                ↑
              </button>
            )}
          </form>


          <div className="composer-footer">
            <span>
              {isGenerating
                ? "Press Stop to cancel generation"
                : "Enter to send · Shift + Enter for a new line"}
            </span>

            <span>
              {
                selectedModel
              }
            </span>
          </div>
        </div>
      </section>
    </main>
  );
}


export default App;