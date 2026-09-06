import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type {
  FormEvent,
  KeyboardEvent,
} from "react";

import {
  getHealth,
  getModels,
  sendChatStream,
} from "./api";

import type {
  ChatMessage,
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


function createMessage(
  role: "user" | "assistant",
  content: string,
): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
  };
}


function formatBytes(
  bytes: number | null,
): string {
  if (!bytes) {
    return "";
  }

  const gigabytes =
    bytes /
    1024 /
    1024 /
    1024;

  if (gigabytes >= 1) {
    return (
      `${gigabytes.toFixed(1)} GB`
    );
  }

  const megabytes =
    bytes /
    1024 /
    1024;

  return (
    `${megabytes.toFixed(0)} MB`
  );
}


function formatDuration(
  milliseconds:
    number | null,
): string {
  if (
    milliseconds === null ||
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
    systemPrompt,
    setSystemPrompt,
  ] =
    useState(
      DEFAULT_SYSTEM_PROMPT
    );

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
    useRef<HTMLDivElement | null>(
      null
    );

  const inputRef =
    useRef<HTMLTextAreaElement | null>(
      null
    );

  const abortControllerRef =
    useRef<
      AbortController | null
    >(null);

  const activeAssistantIdRef =
    useRef<
      string | null
    >(null);


  const checkConnection =
    useCallback(
      async () => {
        setConnectionState(
          "checking"
        );

        setError(null);

        try {
          const health =
            await getHealth();

          if (
            !health.ollama_connected
          ) {
            setConnectionState(
              "ollama-offline"
            );

            setModels([]);

            return;
          }

          const modelResponse =
            await getModels();

          setModels(
            modelResponse.models
          );

          if (
            modelResponse.models
              .length === 0
          ) {
            setConnectionState(
              "ollama-offline"
            );

            setError(
              "Ollama is running, but no local models are installed."
            );

            return;
          }

          setSelectedModel(
            (
              currentModel,
            ) => {
              if (
                currentModel &&
                modelResponse.models
                  .some(
                    (model) =>
                      model.name ===
                      currentModel
                  )
              ) {
                return currentModel;
              }

              const configuredDefault =
                modelResponse.models
                  .find(
                    (model) =>
                      model.name ===
                      health.default_model
                  );

              return (
                configuredDefault
                  ?.name ??
                modelResponse
                  .models[0]
                  .name
              );
            }
          );

          setConnectionState(
            "online"
          );
        } catch (
          connectionError
        ) {
          setConnectionState(
            "backend-offline"
          );

          setError(
            connectionError
              instanceof Error
              ? connectionError
                  .message
              : "Could not connect to the Jace backend."
          );
        }
      },
      []
    );


  useEffect(() => {
    void checkConnection();
  }, [
    checkConnection,
  ]);


  useEffect(() => {
    messagesEndRef.current
      ?.scrollIntoView({
        behavior: "smooth",
      });
  }, [
    messages,
  ]);


  useEffect(() => {
    if (!isGenerating) {
      inputRef.current
        ?.focus();
    }
  }, [
    isGenerating,
  ]);


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

    const trimmedInput =
      input.trim();

    if (
      !trimmedInput ||
      isGenerating ||
      connectionState !==
        "online" ||
      !selectedModel
    ) {
      return;
    }


    const userMessage =
      createMessage(
        "user",
        trimmedInput
      );


    const assistantMessage:
      ChatMessage = {
        id:
          crypto.randomUUID(),

        role:
          "assistant",

        content:
          "",

        isStreaming:
          true,
      };


    const conversation = [
      ...messages,
      userMessage,
    ];


    setMessages([
      ...conversation,
      assistantMessage,
    ]);

    setInput("");

    setError(null);

    setIsGenerating(
      true
    );


    const controller =
      new AbortController();

    abortControllerRef.current =
      controller;

    activeAssistantIdRef.current =
      assistantMessage.id;


    const startedAt =
      performance.now();

    let firstTokenAt:
      number | null =
        null;


    try {
      await sendChatStream(
        {
          model:
            selectedModel,

          system_prompt:
            systemPrompt,

          messages:
            conversation.map(
              (message) => ({
                role:
                  message.role,

                content:
                  message.content,
              })
            ),
        },

        {
          onToken:
            (
              content,
            ) => {
              if (
                firstTokenAt ===
                null
              ) {
                firstTokenAt =
                  performance.now();
              }


              updateAssistantMessage(
                assistantMessage.id,

                (
                  message,
                ) => ({
                  ...message,

                  content:
                    message.content +
                    content,
                })
              );
            },


          onDone:
            (
              event:
                StreamDoneEvent,
            ) => {
              const timeToFirstToken =
                firstTokenAt !==
                null
                  ? firstTokenAt -
                    startedAt
                  : null;


              const stats:
                GenerationStats =
              {
                timeToFirstTokenMs:
                  timeToFirstToken,

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
              };


              updateAssistantMessage(
                assistantMessage.id,

                (
                  message,
                ) => ({
                  ...message,

                  isStreaming:
                    false,

                  stats,
                })
              );
            },
        },

        controller.signal
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

          (
            message,
          ) => ({
            ...message,

            isStreaming:
              false,

            stopped:
              true,
          })
        );
      } else {
        updateAssistantMessage(
          assistantMessage.id,

          (
            message,
          ) => ({
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
      if (
        abortControllerRef
          .current ===
        controller
      ) {
        abortControllerRef
          .current =
          null;
      }

      activeAssistantIdRef
        .current =
        null;

      setIsGenerating(
        false
      );
    }
  }


  function stopGeneration() {
    if (
      !abortControllerRef
        .current
    ) {
      return;
    }

    abortControllerRef.current
      .abort();
  }


  function handleKeyDown(
    event:
      KeyboardEvent<HTMLTextAreaElement>,
  ) {
    if (
      event.key ===
        "Enter" &&
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

    setMessages([]);

    setInput("");

    setError(null);

    window.setTimeout(
      () => {
        inputRef.current
          ?.focus();
      },
      0
    );
  }


  function connectionLabel() {
    switch (
      connectionState
    ) {
      case "online":
        return (
          "Local AI online"
        );

      case "checking":
        return "Connecting";

      case "ollama-offline":
        return (
          "Ollama unavailable"
        );

      case "backend-offline":
        return (
          "Backend offline"
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
              v0.1.1
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


        <div className="sidebar-section">
          <span className="sidebar-heading">
            Conversations
          </span>

          <div className="empty-history">
            <div className="empty-history-icon">
              ◇
            </div>

            <p>
              Conversations are
              currently
              session-only.
            </p>

            <small>
              Persistent history
              arrives in Phase 2.
            </small>
          </div>
        </div>


        <div className="sidebar-spacer" />


        <div className="settings-panel">
          <label
            className="field-label"
            htmlFor="model-select"
          >
            Model
          </label>

          <select
            id="model-select"
            className="model-select"
            value={
              selectedModel
            }
            onChange={
              (event) =>
                setSelectedModel(
                  event.target
                    .value
                )
            }
            disabled={
              connectionState !==
                "online" ||
              isGenerating
            }
          >
            {models.length ===
              0 && (
              <option value="">
                No model
                available
              </option>
            )}

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
                  {model.name}

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
                      item.name ===
                      selectedModel
                  );

                if (!model) {
                  return null;
                }

                return (
                  <>
                    {model.size && (
                      <span>
                        {formatBytes(
                          model.size
                        )}
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
              <label
                className="field-label"
                htmlFor="system-prompt"
              >
                System prompt
              </label>

              <textarea
                id="system-prompt"
                className="system-prompt"
                value={
                  systemPrompt
                }
                onChange={
                  (event) =>
                    setSystemPrompt(
                      event.target
                        .value
                    )
                }
                disabled={
                  isGenerating
                }
              />

              <button
                className="reset-prompt-button"
                onClick={
                  () =>
                    setSystemPrompt(
                      DEFAULT_SYSTEM_PROMPT
                    )
                }
                disabled={
                  isGenerating
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
              {
                connectionLabel()
              }
            </strong>

            <span>
              Private · local
            </span>
          </div>

          {connectionState !==
            "online" && (
            <button
              className="retry-button"
              onClick={
                () =>
                  void checkConnection()
              }
              title="Retry connection"
            >
              ↻
            </button>
          )}
        </div>
      </aside>


      <section className="chat-panel">
        <header className="topbar">
          <div>
            <h1>
              {messages.length ===
              0
                ? "New conversation"
                : "Jace"}
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
          {messages.length ===
          0 ? (
            <div className="welcome">
              <div className="welcome-logo">
                J
              </div>

              <h2>
                How can I help?
              </h2>

              <p>
                Jace is running
                locally using your
                own AI model.
                Nothing in this
                conversation is
                being sent to an
                external AI
                provider.
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

                  Tell me what
                  you can do
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

                  Plan Project
                  Jace
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

                  Explain the
                  system
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
                      `message ${message.role}` +
                      (
                        message.isStreaming
                          ? " streaming"
                          : ""
                      )
                    }
                  >
                    <div className="message-avatar">
                      {message.role ===
                      "user"
                        ? "B"
                        : "J"}
                    </div>

                    <div className="message-body">
                      <div className="message-author">
                        {message.role ===
                        "user"
                          ? "You"
                          : "Jace"}
                      </div>

                      <div className="message-content">
                        {message.content}

                        {!message.content &&
                          message.stopped &&
                          "Generation stopped."}
                      </div>


                      {message.role ===
                        "assistant" &&
                        !message.isStreaming &&
                        (
                          message.stats ||
                          message.stopped
                        ) && (
                          <div className="generation-stats">
                            {message.stopped && (
                              <span className="generation-stopped">
                                ■ Stopped
                              </span>
                            )}

                            {message.stats
                              ?.tokensPerSecond !==
                              null &&
                              message.stats
                                ?.tokensPerSecond !==
                                undefined && (
                                <span>
                                  {message.stats
                                    .tokensPerSecond
                                    .toFixed(
                                      1
                                    )}
                                  {" "}tok/s
                                </span>
                              )}

                            {message.stats
                              ?.timeToFirstTokenMs !==
                              null &&
                              message.stats
                                ?.timeToFirstTokenMs !==
                                undefined && (
                                <span>
                                  First token{" "}
                                  {formatDuration(
                                    message.stats
                                      .timeToFirstTokenMs
                                  )}
                                </span>
                              )}

                            {message.stats
                              ?.evalCount !==
                              null &&
                              message.stats
                                ?.evalCount !==
                                undefined && (
                                <span>
                                  {
                                    message.stats
                                      .evalCount
                                  }{" "}
                                  output tokens
                                </span>
                              )}

                            {message.stats
                              ?.promptEvalCount !==
                              null &&
                              message.stats
                                ?.promptEvalCount !==
                                undefined && (
                                <span>
                                  {
                                    message.stats
                                      .promptEvalCount
                                  }{" "}
                                  prompt tokens
                                </span>
                              )}

                            {message.stats
                              ?.totalDurationMs !==
                              null &&
                              message.stats
                                ?.totalDurationMs !==
                                undefined && (
                                <span>
                                  Total{" "}
                                  {formatDuration(
                                    message.stats
                                      .totalDurationMs
                                  )}
                                </span>
                              )}

                            {message.stats
                              ?.loadDurationMs !==
                              null &&
                              message.stats
                                ?.loadDurationMs !==
                                undefined &&
                              message.stats
                                .loadDurationMs >
                                100 && (
                                <span
                                  title="Time Ollama spent loading the model"
                                >
                                  Load{" "}
                                  {formatDuration(
                                    message.stats
                                      .loadDurationMs
                                  )}
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
                    event.target
                      .value
                  )
              }
              onKeyDown={
                handleKeyDown
              }
              placeholder={
                connectionState ===
                "online"
                  ? (
                      isGenerating
                        ? "Jace is responding..."
                        : "Message Jace..."
                    )
                  : "Waiting for Jace..."
              }
              disabled={
                connectionState !==
                "online" ||
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
                  !input.trim() ||
                  connectionState !==
                    "online" ||
                  !selectedModel
                }
                title="Send"
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
              {selectedModel ||
                "No model selected"}
            </span>
          </div>
        </div>
      </section>
    </main>
  );
}


export default App;