import type {
  ChatRequest,
  ChatStreamEvent,
  ConversationCreateRequest,
  ConversationDetail,
  ConversationListResponse,
  ConversationUpdateRequest,
  HealthResponse,
  ModelsResponse,
  StreamDoneEvent,
} from "./types";


const API_BASE_URL =
  "http://127.0.0.1:8000";


async function getErrorMessage(
  response: Response,
): Promise<string> {
  try {
    const body =
      await response.json();

    if (
      typeof body?.detail ===
      "string"
    ) {
      return body.detail;
    }
  } catch {
    // Use HTTP status below.
  }

  return (
    `${response.status} ` +
    response.statusText
  );
}


async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response =
    await fetch(
      `${API_BASE_URL}${path}`,
      {
        ...options,

        headers: {
          "Content-Type":
            "application/json",

          ...(options?.headers ??
            {}),
        },
      }
    );

  if (!response.ok) {
    throw new Error(
      await getErrorMessage(
        response
      )
    );
  }

  return response.json() as Promise<T>;
}


export function getHealth():
Promise<HealthResponse> {
  return request<HealthResponse>(
    "/health"
  );
}


export function getModels():
Promise<ModelsResponse> {
  return request<ModelsResponse>(
    "/models"
  );
}


export function getConversations():
Promise<ConversationListResponse> {
  return request<
    ConversationListResponse
  >(
    "/conversations"
  );
}


export function getConversation(
  id: string,
):
Promise<ConversationDetail> {
  return request<
    ConversationDetail
  >(
    `/conversations/${id}`
  );
}


export function createConversation(
  payload:
    ConversationCreateRequest,
):
Promise<ConversationDetail> {
  return request<
    ConversationDetail
  >(
    "/conversations",
    {
      method: "POST",

      body:
        JSON.stringify(
          payload
        ),
    }
  );
}


export function updateConversation(
  id: string,
  payload:
    ConversationUpdateRequest,
):
Promise<ConversationDetail> {
  return request<
    ConversationDetail
  >(
    `/conversations/${id}`,
    {
      method: "PATCH",

      body:
        JSON.stringify(
          payload
        ),
    }
  );
}


export async function deleteConversation(
  id: string,
): Promise<void> {
  await request(
    `/conversations/${id}`,
    {
      method: "DELETE",
    }
  );
}


interface StreamCallbacks {
  onToken: (
    content: string,
  ) => void;

  onDone: (
    event: StreamDoneEvent,
  ) => void;
}


export async function sendChatStream(
  payload: ChatRequest,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): Promise<void> {
  const response =
    await fetch(
      `${API_BASE_URL}/chat/stream`,
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json",
        },

        body:
          JSON.stringify(
            payload
          ),

        signal,
      }
    );


  if (!response.ok) {
    throw new Error(
      await getErrorMessage(
        response
      )
    );
  }


  if (!response.body) {
    throw new Error(
      "The Jace backend did not provide a response stream."
    );
  }


  const reader =
    response.body.getReader();

  const decoder =
    new TextDecoder();

  let buffer = "";


  function processLine(
    line: string,
  ) {
    const trimmed =
      line.trim();

    if (!trimmed) {
      return;
    }

    const event:
      ChatStreamEvent =
        JSON.parse(
          trimmed
        );


    switch (event.type) {
      case "token":
        callbacks.onToken(
          event.content
        );

        break;


      case "done":
        callbacks.onDone(
          event
        );

        break;


      case "error":
        throw new Error(
          event.message
        );
    }
  }


  try {
    while (true) {
      const {
        done,
        value,
      } =
        await reader.read();

      if (done) {
        break;
      }

      buffer +=
        decoder.decode(
          value,
          {
            stream: true,
          }
        );

      const lines =
        buffer.split("\n");

      buffer =
        lines.pop() ?? "";

      for (
        const line
        of lines
      ) {
        processLine(
          line
        );
      }
    }

    buffer +=
      decoder.decode();

    if (buffer.trim()) {
      processLine(
        buffer
      );
    }
  } finally {
    reader.releaseLock();
  }
}