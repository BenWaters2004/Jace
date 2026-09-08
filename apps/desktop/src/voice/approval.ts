export type SpokenApprovalIntent = "allow_once" | "deny_once" | "details" | "unknown";

function normalizeSpokenDecision(text: string): string {
  return text
    .toLowerCase()
    .replace(/[.!?,;:]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function classifySpokenApproval(text: string): SpokenApprovalIntent {
  const value = normalizeSpokenDecision(text);
  if (!value) return "unknown";

  if (/^(?:yes|yeah|yep|yup|sure|okay|ok|approve|allow|go ahead|continue|do it)(?: please)?$/.test(value)) {
    return "allow_once";
  }

  if (/^(?:no|nope|deny|cancel|stop|don't|do not)(?: thanks| thank you)?$/.test(value)) {
    return "deny_once";
  }

  if (/^(?:details|more details|tell me more|what is it|what does that do|explain(?: it)?|why)$/.test(value)) {
    return "details";
  }

  return "unknown";
}
